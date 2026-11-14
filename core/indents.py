"""Build, validate, submit, correct and freeze indents (spec 5.6, 5.7, 8).

Indent_Lines is append-only. The current version of an indent is the row
group with the highest `version` for that `indent_id`.

Concurrency: the id / version is computed right before writing, then the tab
is read again. If someone else wrote the same (indent_id, version) earlier,
the app removes only the rows it has just written and either retries with
the next number (new indent) or reports a conflict (correction / freeze).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from core import changelog, config
from core.lots import lot_size, normalize_lot
from core.masters import Masters
from core.models import IndentHeader, IndentLine, IndentSnapshot, fmt_num, to_number
from core.schema import (CHANGE_LOG, INDENT_LINES, LOTS, PO_FREEZE, STATUS_CANCELLED,
                         STATUS_FROZEN, STATUS_SUBMITTED)
from core.sheets import SheetError, get_backend


class ConflictError(SheetError):
    """Someone else changed the indent between load and save."""


class FrozenError(SheetError):
    """The indent is frozen with a PO and cannot be changed."""


class NothingChangedError(SheetError):
    pass


class CutoffError(SheetError):
    """The edit window of the indent has closed."""


class DuplicateError(SheetError):
    """An indent already exists for this store and delivery date."""

    def __init__(self, msg: str, indent_id: str):
        super().__init__(msg)
        self.indent_id = indent_id


def _norm(v) -> str:
    return " ".join(str(v or "").split()).casefold()


def find_duplicate(df: pd.DataFrame, header: IndentHeader, exclude_id: str = "") -> str | None:
    """The indent already placed for the same store (city + customer + store)
    and delivery date, if any. Only current versions count."""
    if df is None or df.empty or not (header.delivery_date and header.store):
        return None
    cur = current_rows(df)
    m = cur[(cur["delivery_date"].astype(str) == header.delivery_date)
            & (cur["store"].map(_norm) == _norm(header.store))
            & (cur["customer"].map(_norm) == _norm(header.customer))
            & (cur["city"].map(_norm) == _norm(header.city))
            & (cur["indent_id"] != exclude_id)]
    return None if m.empty else str(m["indent_id"].iloc[0])


def duplicate_message(indent_id: str, header: IndentHeader) -> str:
    return (f"An indent for {header.store} on {header.delivery_date} is already placed "
            f"({indent_id}). Only one indent per store per delivery date: edit that one instead.")


# ----------------------------------------------------------- time rules

def _ist(iso: str) -> datetime:
    dt = datetime.fromisoformat(str(iso))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.IST)
    return dt.astimezone(config.IST)


def edit_deadline(created_iso: str) -> datetime:
    """Indents can be edited until `edit_cutoff_hour` (12:00) IST on the day
    after they were created (`edit_cutoff_days` = 1)."""
    d = _ist(created_iso).date() + timedelta(days=config.edit_cutoff_days())
    return datetime(d.year, d.month, d.day, config.edit_cutoff_hour(), tzinfo=config.IST)


def can_edit(created_iso: str, now: datetime | None = None) -> bool:
    try:
        return (now or config.now_ist()) < edit_deadline(created_iso)
    except (TypeError, ValueError):
        return False


def min_delivery_date(created_iso: str | None = None) -> date:
    """Delivery must be after today (new indent) or after the day the indent
    was created (corrections), so a saved date stays valid while editing."""
    base = _ist(created_iso).date() if created_iso else config.now_ist().date()
    return base + timedelta(days=1)


def created_at(df: pd.DataFrame, indent_id: str) -> str:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return ""
    return sub.sort_values(["version", "_row"]).iloc[0]["submitted_at"]


# ------------------------------------------------------------------ reading

@st.cache_data(ttl=15, show_spinner=False)
def _cached_tab(tab: str) -> pd.DataFrame:
    return get_backend().read(tab)


def read_lines(fresh: bool = False) -> pd.DataFrame:
    df = get_backend().read(INDENT_LINES) if fresh else _cached_tab(INDENT_LINES)
    return prepare(df)


def read_change_log() -> pd.DataFrame:
    return _cached_tab(CHANGE_LOG)


def read_po_freeze() -> pd.DataFrame:
    return _cached_tab(PO_FREEZE)


def clear_cache() -> None:
    _cached_tab.clear()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df[df["indent_id"].astype(str).str.strip() != ""]
    df["version"] = pd.to_numeric(df["version"], errors="coerce").fillna(0).astype(int)
    for c in ("qty", "price", "amount"):
        df[c] = df[c].map(to_number)
    df["lot"] = df["lot"].map(normalize_lot)  # rows saved as "gms" read as "Pack"
    return df


def current_rows(df: pd.DataFrame, include_cancelled: bool = False) -> pd.DataFrame:
    """Only the rows of the current (highest) version of each indent.
    Cancelled (deleted) indents are left out unless asked for."""
    if df.empty:
        return df
    top = df.groupby("indent_id")["version"].transform("max")
    cur = df[df["version"] == top]
    if not include_cancelled:
        cur = cur[cur["status"] != STATUS_CANCELLED]
    return cur


def summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per indent (current version) for the My indents table."""
    cols = ["indent_id", "version", "status", "delivery_date", "city", "customer", "store",
            "expected_time", "lines", "total_amount", "last_edited_at", "last_edited_by",
            "created_by", "created_at", "can_edit"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    first = (df.sort_values(["indent_id", "version", "_row"])
               .groupby("indent_id").first()[["submitted_by", "submitted_at"]]
               .rename(columns={"submitted_by": "created_by", "submitted_at": "created_at"}))
    cur = current_rows(df, include_cancelled=True)
    agg = (cur.sort_values("_row").groupby("indent_id")
              .agg(version=("version", "first"), status=("status", "first"),
                   delivery_date=("delivery_date", "first"), city=("city", "first"),
                   customer=("customer", "first"), store=("store", "first"),
                   expected_time=("expected_time", "first"),
                   lines=("customer_sku_name", "count"), total_amount=("amount", "sum"),
                   last_edited_at=("submitted_at", "first"),
                   last_edited_by=("submitted_by", "first")))
    out = agg.join(first).reset_index()
    out["total_amount"] = out["total_amount"].round(2)
    out["can_edit"] = (out["created_at"].map(can_edit)
                       & ~out["status"].isin([STATUS_FROZEN, STATUS_CANCELLED]))
    return out.sort_values("last_edited_at", ascending=False)[cols].reset_index(drop=True)


def versions(df: pd.DataFrame, indent_id: str) -> pd.DataFrame:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return pd.DataFrame(columns=["version", "status", "submitted_at", "submitted_by", "lines", "amount"])
    g = (sub.sort_values("_row").groupby("version")
            .agg(status=("status", "first"), submitted_at=("submitted_at", "first"),
                 submitted_by=("submitted_by", "first"), lines=("customer_sku_name", "count"),
                 amount=("amount", "sum")).reset_index())
    g["amount"] = g["amount"].round(2)
    return g.sort_values("version", ascending=False).reset_index(drop=True)


def snapshot(df: pd.DataFrame, indent_id: str, version: int | None = None) -> IndentSnapshot | None:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return None
    v = int(sub["version"].max()) if version is None else int(version)
    sub = sub[sub["version"] == v].sort_values("_row")
    if sub.empty:
        return None
    r = sub.iloc[0]
    header = IndentHeader(delivery_date=r["delivery_date"], city=r["city"], customer=r["customer"],
                          store=r["store"], expected_time=r["expected_time"])
    lines = [IndentLine(parent_sku=x["parent_sku"], customer_sku_name=x["customer_sku_name"],
                        variety=x["variety"], lot=x["lot"], qty=to_number(x["qty"]),
                        price=to_number(x["price"]))
             for _, x in sub.iterrows() if str(x["customer_sku_name"]).strip()]
    return IndentSnapshot(indent_id=indent_id, version=v, status=r["status"] or STATUS_SUBMITTED,
                          submitted_at=r["submitted_at"], submitted_by=r["submitted_by"],
                          header=header, lines=lines)


# --------------------------------------------------------------- validation

def validate(header: IndentHeader, lines: list[IndentLine], m: Masters,
             min_date: date | None = None) -> list[str]:
    errors: list[str] = []
    missing = header.missing()
    if missing:
        errors.append("Delivery details missing: " + ", ".join(missing) + ".")
    if min_date and header.delivery_date and header.delivery_date < min_date.isoformat():
        errors.append(f"Delivery date must be on or after {min_date:%d %b %Y}.")
    start, end = config.delivery_window()
    if header.expected_time and not start <= header.expected_time <= end:
        errors.append(f"Expected delivery time must be between {start} and {end}.")
    if header.city and header.customer and header.store:
        if header.store not in m.stores_for(header.city, header.customer):
            errors.append(f"Store '{header.store}' is not mapped to {header.customer} in {header.city}.")
    if not lines:
        errors.append("Add at least one item.")
    seen: set[str] = set()
    for line in lines:
        name = line.customer_sku_name
        k = name.strip().casefold()
        if k in seen:
            errors.append(f"'{name}' is added more than once.")
        seen.add(k)
        valid_names = {n.casefold() for n in m.sku_names(header.city, header.customer, line.parent_sku)}
        if k not in valid_names:
            errors.append(f"'{name}' is not mapped under {line.parent_sku} for "
                          f"{header.customer} in {header.city}.")
        varieties = m.varieties_for(line.parent_sku)
        if varieties and line.variety not in varieties:
            errors.append(f"Choose a variety for '{name}'.")
        if line.lot not in LOTS:
            errors.append(f"Choose a lot for '{name}'.")
        if to_number(line.qty) <= 0:
            errors.append(f"Qty for '{name}' must be greater than 0.")
        elif not float(to_number(line.qty)).is_integer():
            errors.append(f"Qty for '{name}' must be a whole number (no decimals).")
        if to_number(line.price) <= 0:
            errors.append(f"Price for '{name}' must be greater than 0.")
    return errors


# ------------------------------------------------------------------ writing

def city_code(city: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", city or "").upper()
    return (letters[:3] or "XXX").ljust(3, "X")


def next_indent_id(existing_ids, city: str, on: date) -> str:
    nums = []
    for i in existing_ids:
        m = re.search(r"-(\d{4,})$", str(i))
        if m:
            nums.append(int(m.group(1)))
    n = max(nums, default=0) + 1
    return f"IND-{on:%Y%m%d}-{city_code(city)}-{n:04d}"


def build_rows(indent_id: str, version: int, status: str, submitted_at: str, submitted_by: str,
               header: IndentHeader, lines: list[IndentLine]) -> list[dict]:
    rows = []
    for line in lines:
        rows.append({
            "indent_id": indent_id, "version": version, "status": status,
            "submitted_at": submitted_at, "submitted_by": submitted_by,
            **header.to_dict(),
            "parent_sku": line.parent_sku, "customer_sku_name": line.customer_sku_name,
            "variety": line.variety, "lot": line.lot, "lot_size": lot_size(line.customer_sku_name),
            "qty": to_number(line.qty), "price": to_number(line.price), "amount": line.amount,
        })
    return rows


def _append_verified(backend, rows: list[dict], indent_id: str, version: int,
                     stamp: str, user: str) -> bool:
    """Append rows, then make sure nobody else wrote the same id+version.
    Returns False (after removing our rows) if we lost the race."""
    first, last = backend.append_dicts(INDENT_LINES, rows)
    df = prepare(backend.read(INDENT_LINES))
    same = df[(df["indent_id"] == indent_id) & (df["version"] == version)]
    earlier = same[same["_row"] < first]
    if earlier.empty:
        return True
    backend.delete_rows(INDENT_LINES, first, last)
    # The earlier rows may be our own write, repeated after a network retry.
    mine = (earlier["submitted_at"] == stamp).all() and (earlier["submitted_by"] == user).all()
    return bool(mine)


def submit_new(header: IndentHeader, lines: list[IndentLine], user: str) -> str:
    if header.delivery_date < min_delivery_date().isoformat():
        raise SheetError("The delivery date must be after today.")
    backend = get_backend()
    for _ in range(3):
        df = prepare(backend.read(INDENT_LINES))
        dup = find_duplicate(df, header)
        if dup:
            raise DuplicateError(duplicate_message(dup, header), dup)
        now = config.now_ist()
        indent_id = next_indent_id(df["indent_id"], header.city, now.date())
        stamp = now.isoformat()
        rows = build_rows(indent_id, 1, STATUS_SUBMITTED, stamp, user, header, lines)
        if _append_verified(backend, rows, indent_id, 1, stamp, user):
            clear_cache()
            return indent_id
    clear_cache()
    raise SheetError("Could not reserve a unique indent number because others were saving at "
                     "the same moment. Your draft is safe; please press Submit again.")


def _check_editable(cur: IndentSnapshot | None, indent_id: str, base_version: int) -> None:
    if cur is None:
        raise SheetError(f"Indent {indent_id} was not found in the sheet.")
    if cur.status == STATUS_FROZEN:
        raise FrozenError(f"{indent_id} is frozen with a PO and can no longer be changed.")
    if cur.status == STATUS_CANCELLED:
        raise FrozenError(f"{indent_id} was deleted and can no longer be changed.")
    if cur.version != int(base_version):
        raise ConflictError(f"{indent_id} was changed by {cur.submitted_by} at {cur.submitted_at} "
                            f"(now version {cur.version}). Open it again from My indents and "
                            "re-apply your changes.")


def submit_update(indent_id: str, base_version: int, header: IndentHeader,
                  lines: list[IndentLine], user: str) -> tuple[int, bool]:
    """Append version N+1 and its Change_Log rows.
    Returns (new_version, change_log_saved)."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    _check_editable(cur, indent_id, base_version)
    created = created_at(df, indent_id)
    if not can_edit(created):
        raise CutoffError(f"{indent_id} can no longer be edited: the edit window closed at "
                          f"{edit_deadline(created):%d %b %Y, %I:%M %p}.")
    if header.delivery_date < min_delivery_date(created).isoformat():
        raise SheetError(f"The delivery date must be on or after {min_delivery_date(created):%d %b %Y}.")
    dup = find_duplicate(df, header, exclude_id=indent_id)
    if dup:
        raise DuplicateError(duplicate_message(dup, header), dup)
    changes = changelog.diff(cur.header, cur.lines, header, lines)
    if not changes:
        raise NothingChangedError("Nothing changed compared with the saved version.")
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(indent_id, new_v, STATUS_SUBMITTED, stamp, user, header, lines)
    if not _append_verified(backend, rows, indent_id, new_v, stamp, user):
        clear_cache()
        raise ConflictError(f"Someone else saved {indent_id} at the same moment. "
                            "Open it again from My indents and re-apply your changes.")
    log_ok = True
    try:
        backend.append_dicts(CHANGE_LOG, changelog.to_rows(
            changes, indent_id=indent_id, from_version=cur.version, to_version=new_v,
            changed_by=user, changed_at=stamp))
    except SheetError:
        log_ok = False
    clear_cache()
    return new_v, log_ok


def freeze(indent_id: str, base_version: int, po_file_name: str, user: str,
           po_file_link: str = "") -> int:
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    _check_editable(cur, indent_id, base_version)
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(indent_id, new_v, STATUS_FROZEN, stamp, user, cur.header, cur.lines)
    if not _append_verified(backend, rows, indent_id, new_v, stamp, user):
        clear_cache()
        raise ConflictError(f"Someone else saved {indent_id} at the same moment. Please try again.")
    backend.append_dicts(PO_FREEZE, [{
        "indent_id": indent_id, "version": new_v, "po_file_name": po_file_name,
        "po_customer": cur.header.customer, "po_store": cur.header.store,
        "confirmed_by": user, "confirmed_at": stamp, "po_file_link": po_file_link}])
    try:
        backend.append_dicts(CHANGE_LOG, changelog.to_rows(
            [{"change_type": "header_changed", "customer_sku_name": "", "field": "status",
              "old_value": STATUS_SUBMITTED, "new_value": STATUS_FROZEN}],
            indent_id=indent_id, from_version=cur.version, to_version=new_v,
            changed_by=user, changed_at=stamp))
    except SheetError:
        pass
    clear_cache()
    return new_v


__all__ = ["find_duplicate", "DuplicateError", "edit_deadline", "can_edit", "min_delivery_date", "created_at", "CutoffError", "read_lines", "current_rows", "summary", "versions", "snapshot", "validate",
           "submit_new", "submit_update", "freeze", "next_indent_id", "build_rows",
           "ConflictError", "FrozenError", "NothingChangedError", "fmt_num"]


def cancel(indent_id: str, base_version: int, user: str) -> int:
    """'Delete' an indent: append a copy of the current version with status
    Cancelled. It disappears from production, the store/date becomes free,
    and every earlier version stays in the sheet."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    _check_editable(cur, indent_id, base_version)
    created = created_at(df, indent_id)
    if not can_edit(created):
        raise CutoffError(f"{indent_id} can no longer be deleted: the edit window closed at "
                          f"{edit_deadline(created):%d %b %Y, %I:%M %p}.")
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(indent_id, new_v, STATUS_CANCELLED, stamp, user, cur.header, cur.lines)
    if not _append_verified(backend, rows, indent_id, new_v, stamp, user):
        clear_cache()
        raise ConflictError(f"Someone else saved {indent_id} at the same moment. Please try again.")
    try:
        backend.append_dicts(CHANGE_LOG, changelog.to_rows(
            [{"change_type": "header_changed", "customer_sku_name": "", "field": "status",
              "old_value": cur.status, "new_value": STATUS_CANCELLED}],
            indent_id=indent_id, from_version=cur.version, to_version=new_v,
            changed_by=user, changed_at=stamp))
    except SheetError:
        pass
    clear_cache()
    return new_v
