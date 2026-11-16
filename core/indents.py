"""Build, validate, submit, correct and freeze indents (spec 5.6, 5.7, 8).

Indent_Lines is append-only. The current version of an indent is the row
group with the highest `version` for that `indent_id`.

Concurrency: the id / version is computed right before writing, then the tab
is read again. If someone else wrote the same (indent_id, version) earlier,
the app removes only the rows it has just written and either retries with
the next number (new indent) or reports a conflict (correction / freeze).
"""
from __future__ import annotations

import json

import re
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from core import changelog, config
from core.lots import lot_size, normalize_lot
from core.masters import Masters
from core.models import IndentHeader, IndentLine, IndentSnapshot, fmt_num, to_number
from core.schema import (CHANGE_LOG, DRAFTS, INDENT_LINES, LOTS, PO_END, PO_FREEZE, PO_KIND,
                         STATUS_CANCELLED, STATUS_FROZEN, STATUS_LOCKED, STATUS_SUBMITTED, TABS)
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


def cutoff_hour(customer: str = "") -> int:
    """Edit cutoff hour on the delivery day: the customer's own (Zepto: 1 AM) or
    the general `edit_cutoff_hour` (2 PM)."""
    return config.customer_cutoff_hours().get(str(customer or "").strip().casefold(),
                                              config.edit_cutoff_hour())


def edit_deadline(delivery_date: str, customer: str = "") -> datetime:
    """An indent can be edited / deleted until its cutoff hour IST on its
    DELIVERY date (`edit_cutoff_days` = 0): 2:00 PM, Zepto 1:00 AM."""
    d = date.fromisoformat(str(delivery_date)[:10]) + timedelta(days=config.edit_cutoff_days())
    return datetime(d.year, d.month, d.day, cutoff_hour(customer), tzinfo=config.IST)


def can_edit(delivery_date: str, now: datetime | None = None, customer: str = "") -> bool:
    try:
        return (now or config.now_ist()) < edit_deadline(delivery_date, customer)
    except (TypeError, ValueError):
        return False


def deadline_text(delivery_date: str, customer: str = "") -> str:
    try:
        return edit_deadline(delivery_date, customer).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return ""


def delivery_bounds(keep: str | None = None) -> tuple[date, date]:
    """Allowed delivery dates: today (T) and tomorrow (T+1). When correcting an
    indent, its saved date (`keep`) stays allowed even if it has passed."""
    today = config.now_ist().date()
    lo, hi = today, today + timedelta(days=config.delivery_days_ahead())
    if keep:
        try:
            lo = min(lo, date.fromisoformat(keep))
        except ValueError:
            pass
    return lo, hi


def date_allowed(delivery_date: str, keep: str | None = None, customer: str = "") -> bool:
    """T or T+1, and not after that date's cutoff (2 PM; Zepto 1 AM). A correction
    may keep its own date (its cutoff is checked separately)."""
    if keep and delivery_date == keep:
        return True
    lo, hi = delivery_bounds()
    return lo.isoformat() <= str(delivery_date) <= hi.isoformat() and can_edit(delivery_date,
                                                                              customer=customer)


def date_rule_text() -> str:
    lo, hi = delivery_bounds()
    base = (f"today ({lo:%d %b}) or tomorrow ({hi:%d %b})" if (hi - lo).days == 1
            else f"{lo:%d %b} to {hi:%d %b}")
    return base + f", before {config.edit_cutoff_hour() % 12 or 12}:00 " \
        + ("PM" if config.edit_cutoff_hour() >= 12 else "AM") + " on the delivery day"


def creator_of(df: pd.DataFrame, indent_id: str) -> str:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return ""
    return str(sub.sort_values(["version", "_row"]).iloc[0]["submitted_by"])


def created_at(df: pd.DataFrame, indent_id: str) -> str:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return ""
    return sub.sort_values(["version", "_row"]).iloc[0]["submitted_at"]


# ------------------------------------------------------------------ reading

CACHE_SECONDS = 60   # other users' changes show within a minute; your own saves clear it at once


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _cached_tab(tab: str) -> pd.DataFrame:
    return get_backend().read(tab)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _cached_lines() -> pd.DataFrame:
    return prepare(get_backend().read(INDENT_LINES))


def read_lines(fresh: bool = False) -> pd.DataFrame:
    return prepare(get_backend().read(INDENT_LINES)) if fresh else _cached_lines()


def read_change_log() -> pd.DataFrame:
    return _cached_tab(CHANGE_LOG)


def read_po_freeze() -> pd.DataFrame:
    return _cached_tab(PO_FREEZE)


def clear_cache() -> None:
    _cached_tab.clear()
    _cached_lines.clear()


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
    out["can_edit"] = (pd.Series([can_edit(d, customer=c) for d, c in zip(out["delivery_date"], out["customer"])],
                                 index=out.index, dtype=bool)
                       & ~out["status"].isin([STATUS_FROZEN, STATUS_LOCKED, STATUS_CANCELLED]))
    return open_first(out[cols])


STATUS_ORDER = {STATUS_SUBMITTED: 0, STATUS_LOCKED: 0, STATUS_FROZEN: 1, STATUS_CANCELLED: 2}


def open_first(df: pd.DataFrame, then: list[str] | None = None,
               ascending: list[bool] | None = None) -> pd.DataFrame:
    """Open (Submitted) indents on top, then PO-frozen, then deleted; within
    each group by `then` (default: most recently edited first)."""
    if df is None or df.empty:
        return df
    then = then or ["last_edited_at"]
    ascending = ascending if ascending is not None else [False] * len(then)
    out = df.assign(_rank=df["status"].map(STATUS_ORDER).fillna(0))
    return out.sort_values(["_rank"] + then, ascending=[True] + ascending).drop(columns="_rank") \
              .reset_index(drop=True)


def visible_to(summ: pd.DataFrame, user) -> pd.DataFrame:
    """Indents this user may see and work on: owner all; a sales user with
    cities every indent in those cities; otherwise the ones they created."""
    if summ is None or summ.empty or user.is_owner:
        return summ
    if user.cities:
        norm = lambda col: summ[col].astype(str).map(lambda v: " ".join(v.split()).casefold())  # noqa: E731
        out = summ[norm("city").isin({c.casefold() for c in user.cities})]
        if user.stores:
            out = out[norm("store").loc[out.index].isin({x.casefold() for x in user.stores})]
        return out
    if getattr(user, "is_warehouse", False):
        return summ                      # warehouse without cities: every city
    return summ[summ["created_by"].astype(str).str.lower() == user.email]


def scope_text(user) -> str:
    if user.is_owner or (getattr(user, "is_warehouse", False) and not user.cities):
        return "all indents"
    if user.cities:
        return ("indents of " + ", ".join(user.stores) if user.stores
                else "all indents in " + ", ".join(user.cities))
    return "indents you created"


def versions(df: pd.DataFrame, indent_id: str) -> pd.DataFrame:
    sub = df[df["indent_id"] == indent_id]
    if sub.empty:
        return pd.DataFrame(columns=["version", "status", "submitted_at", "submitted_by", "lines", "amount",
                                     "change_note"])
    if "change_note" not in sub.columns:
        sub = sub.assign(change_note="")
    g = (sub.sort_values("_row").groupby("version")
            .agg(status=("status", "first"), submitted_at=("submitted_at", "first"),
                 submitted_by=("submitted_by", "first"), lines=("customer_sku_name", "count"),
                 amount=("amount", "sum"), change_note=("change_note", "first")).reset_index())
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
             check_date: bool = False, keep_date: str | None = None,
             zero_ok: set[str] | None = None) -> list[str]:
    """zero_ok: SKU names (casefolded) already saved on the indent; their qty
    may be set to 0 (items are never removed from a saved indent)."""
    zero_ok = {n.strip().casefold() for n in (zero_ok or set())}
    errors: list[str] = []
    missing = header.missing()
    if missing:
        errors.append("Delivery details missing: " + ", ".join(missing) + ".")
    if check_date and header.delivery_date and not date_allowed(header.delivery_date, keep_date,
                                                                header.customer):
        errors.append(f"Delivery date must be {date_rule_text()}."
                      + (f" {header.customer} orders for {header.delivery_date} closed at "
                         f"{deadline_text(header.delivery_date, header.customer)}."
                         if cutoff_hour(header.customer) != config.edit_cutoff_hour() else ""))
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
        fixed = m.variety_from_name(line.parent_sku, name)
        if fixed and line.variety != fixed:
            errors.append(f"Variety for '{name}' must be {fixed} (it is in the SKU name).")
        elif varieties and line.variety not in varieties:
            errors.append(f"Choose a variety for '{name}'.")
        if line.lot not in LOTS:
            errors.append(f"Choose a lot for '{name}'.")
        if to_number(line.qty) < 0 or (to_number(line.qty) == 0 and k not in zero_ok):
            errors.append(f"Qty for '{name}' must be greater than 0." if k not in zero_ok
                          else f"Qty for '{name}' cannot be negative.")
        elif not float(to_number(line.qty)).is_integer():
            errors.append(f"Qty for '{name}' must be a whole number (no decimals).")
        if to_number(line.price) <= 0:
            errors.append(f"Price for '{name}' must be greater than 0.")
    return errors


# ------------------------------------------------------------------ writing


ID_PREFIX = "IN-"


def next_indent_id(existing_ids, city: str = "", on: date | None = None) -> str:
    """One running number for every indent, never reset by day or city:
    IN-001, IN-002, … IN-999, IN-1000 … (indents saved before this rule keep
    their old IND-yyyymmdd-CITY-nnnn numbers)."""
    nums = []
    for i in existing_ids:
        m = re.fullmatch(r"IN-(\d+)", str(i).strip())
        if m:
            nums.append(int(m.group(1)))
    return f"{ID_PREFIX}{max(nums, default=0) + 1:03d}"


def _who(user: str, creator: str) -> str:
    if not creator or user.lower() == creator.lower():
        return "same user"
    return f"other user; created by {creator}"


def _when(stamp: str) -> str:
    try:
        return _ist(stamp).strftime("%d %b %Y %H:%M")
    except ValueError:
        return stamp


def summarize_changes(changes: list[dict], limit: int = 900) -> str:
    parts = []
    for c in changes:
        t, sku, f = c["change_type"], c.get("customer_sku_name", ""), c.get("field", "")
        if t == "header_changed":
            parts.append(f"{f.replace('_', ' ')} {c['old_value']} → {c['new_value']}")
        elif t == "line_added":
            parts.append(f"added {sku}")
        elif t == "line_removed":
            parts.append(f"deleted {sku}")
        else:
            parts.append(f"{sku}: {f} {c['old_value']} → {c['new_value']}")
    text = "; ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def change_note(action: str, user: str, creator: str, stamp: str, detail: str = "") -> str:
    """One-cell history note written on every row of a version, e.g.
    'Edited by b@x (other user; created by a@x) on 15 Nov 2026 10:05: qty …'."""
    who = f"{action} by {user}" + ("" if action == "Created" else f" ({_who(user, creator)})")
    return f"{who} on {_when(stamp)}" + (f": {detail}" if detail else "")


def build_rows(indent_id: str, version: int, status: str, submitted_at: str, submitted_by: str,
               header: IndentHeader, lines: list[IndentLine], note: str = "") -> list[dict]:
    rows = []
    for line in lines:
        rows.append({
            "indent_id": indent_id, "version": version, "status": status,
            "submitted_at": submitted_at, "submitted_by": submitted_by,
            **header.to_dict(),
            "parent_sku": line.parent_sku, "customer_sku_name": line.customer_sku_name,
            "variety": line.variety, "lot": line.lot, "lot_size": lot_size(line.customer_sku_name),
            "qty": to_number(line.qty), "price": to_number(line.price), "amount": line.amount,
            "change_note": note,
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
    if not date_allowed(header.delivery_date, customer=header.customer):
        raise SheetError(f"The delivery date must be {date_rule_text()}.")
    backend = get_backend()
    for _ in range(3):
        df = prepare(backend.read(INDENT_LINES))
        dup = find_duplicate(df, header)
        if dup:
            raise DuplicateError(duplicate_message(dup, header), dup)
        now = config.now_ist()
        indent_id = next_indent_id(df["indent_id"], header.city, now.date())
        stamp = now.isoformat()
        rows = build_rows(indent_id, 1, STATUS_SUBMITTED, stamp, user, header, lines,
                          note=change_note("Created", user, user, stamp))
        if _append_verified(backend, rows, indent_id, 1, stamp, user):
            clear_cache()
            return indent_id
    clear_cache()
    raise SheetError("Could not reserve a unique indent number because others were saving at "
                     "the same moment. Your draft is safe; please press Submit again.")


def _check_editable(cur: IndentSnapshot | None, indent_id: str, base_version: int,
                    allow_locked: bool = False) -> None:
    if cur is None:
        raise SheetError(f"Indent {indent_id} was not found in the sheet.")
    if cur.status == STATUS_LOCKED and not allow_locked:
        raise FrozenError(f"{indent_id} is locked (processing started) and can no longer be changed.")
    if cur.status == STATUS_FROZEN:
        raise FrozenError(f"{indent_id} is frozen with a PO and can no longer be changed.")
    if cur.status == STATUS_CANCELLED:
        raise FrozenError(f"{indent_id} was deleted and can no longer be changed.")
    if cur.version != int(base_version):
        raise ConflictError(f"{indent_id} was changed by {cur.submitted_by} at {cur.submitted_at} "
                            f"(now version {cur.version}). Open it again from My indents and "
                            "re-apply your changes.")


LOCKED_FIELDS = ("city", "customer", "store", "delivery_date")


def submit_update(indent_id: str, base_version: int, header: IndentHeader,
                  lines: list[IndentLine], user: str, po_fix: bool = False) -> tuple[int, bool]:
    """Append version N+1 and its Change_Log rows.
    Saved indents keep their city, customer, store, delivery date and items
    (qty may go to 0). po_fix=True: a correction to match the customer's PO,
    allowed after the edit cutoff.
    Returns (new_version, change_log_saved)."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    _check_editable(cur, indent_id, base_version, allow_locked=po_fix)
    saved_date = cur.header.delivery_date
    if not po_fix and not can_edit(saved_date, customer=cur.header.customer):
        raise CutoffError(f"{indent_id} can no longer be edited: editing closed at "
                          f"{deadline_text(saved_date, cur.header.customer)} (delivery day cutoff).")
    locked = [f.replace("_", " ") for f in LOCKED_FIELDS
              if str(getattr(header, f, "")).strip() != str(getattr(cur.header, f, "")).strip()]
    if locked:
        raise SheetError(f"The {', '.join(locked)} of a saved indent cannot be changed.")
    kept = {x.customer_sku_name.strip().casefold() for x in lines}
    gone = [x.customer_sku_name for x in cur.lines if x.customer_sku_name.strip().casefold() not in kept]
    if gone:
        raise SheetError("Items cannot be removed from a saved indent; set their qty to 0 instead: "
                         + ", ".join(gone) + ".")
    if not date_allowed(header.delivery_date, keep=cur.header.delivery_date, customer=header.customer):
        raise SheetError(f"The delivery date must be {date_rule_text()}.")
    dup = find_duplicate(df, header, exclude_id=indent_id)
    if dup:
        raise DuplicateError(duplicate_message(dup, header), dup)
    changes = changelog.diff(cur.header, cur.lines, header, lines)
    if not changes:
        raise NothingChangedError("Nothing changed compared with the saved version.")
    new_v = cur.version + 1
    stamp = config.now_iso()
    creator = creator_of(df, indent_id)
    detail = ("to match PO: " if po_fix else "") + summarize_changes(changes)
    rows = build_rows(indent_id, new_v, STATUS_LOCKED if cur.status == STATUS_LOCKED else STATUS_SUBMITTED,
                      stamp, user, header, lines, note=change_note("Edited", user, creator, stamp, detail))
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


class POMismatchError(SheetError):
    def __init__(self, message: str, rows: list[dict]):
        super().__init__(message)
        self.rows = rows


def po_compare(lines: list[IndentLine], po_qty: dict) -> list[dict]:
    """One row per indent item: indent qty, PO qty, difference, match."""
    by = {str(k).strip().casefold(): v for k, v in (po_qty or {}).items()}
    out = []
    for x in lines:
        raw = by.get(x.customer_sku_name.strip().casefold())
        po = None if raw in (None, "") or (isinstance(raw, float) and raw != raw) else to_number(raw)
        ind = to_number(x.qty)
        out.append({"customer_sku_name": x.customer_sku_name, "lot": x.lot, "indent_qty": ind,
                    "po_qty": po, "diff": None if po is None else po - ind,
                    "ok": po is not None and abs(po - ind) < 1e-9})
    return out


def po_lines_text(lines: list[IndentLine]) -> str:
    return "; ".join(f"{x.customer_sku_name} = {fmt_num(x.qty)} {x.lot}" for x in lines)


def is_multi_po(customer: str) -> bool:
    """Customers (Swiggy) that may send several POs for one indent."""
    return str(customer or "").strip().casefold() in config.multi_po_customers()


def _status_row(backend, df, cur, new_status: str, user: str, action: str, detail: str) -> tuple[int, str]:
    """Append a copy of the current version with a new status (+ Change_Log row)."""
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(cur.indent_id, new_v, new_status, stamp, user, cur.header, cur.lines,
                      note=change_note(action, user, creator_of(df, cur.indent_id), stamp, detail))
    if not _append_verified(backend, rows, cur.indent_id, new_v, stamp, user):
        clear_cache()
        raise ConflictError(f"Someone else saved {cur.indent_id} at the same moment. Please try again.")
    try:
        backend.append_dicts(CHANGE_LOG, changelog.to_rows(
            [{"change_type": "header_changed", "customer_sku_name": "", "field": "status",
              "old_value": cur.status, "new_value": new_status}],
            indent_id=cur.indent_id, from_version=cur.version, to_version=new_v,
            changed_by=user, changed_at=stamp))
    except SheetError:
        pass
    return new_v, stamp


def _po_row(cur, version: int, kind: str, user: str, stamp: str, file_name: str = "", link: str = "",
            po_number: str = "", po_qty: dict | None = None) -> dict:
    qty = {k: float(v) for k, v in (po_qty or {}).items() if v is not None}
    return {"indent_id": cur.indent_id, "version": version, "po_file_name": file_name,
            "po_customer": cur.header.customer, "po_store": cur.header.store,
            "confirmed_by": user, "confirmed_at": stamp, "po_file_link": link,
            "po_number": po_number, "po_total_qty": sum(qty.values()),
            "po_lines": "; ".join(f"{k} = {fmt_num(v)}" for k, v in qty.items()),
            "kind": kind, "po_qty_json": json.dumps(qty, ensure_ascii=False)}


def lock(indent_id: str, base_version: int, user: str) -> int:
    """Freeze by hand (processing started): no more edits, still waiting for its PO."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    if cur is not None and cur.status == STATUS_LOCKED:
        raise FrozenError(f"{indent_id} is already locked.")
    _check_editable(cur, indent_id, base_version)
    new_v, _ = _status_row(backend, df, cur, STATUS_LOCKED, user, "Locked",
                           "frozen by hand: processing started")
    clear_cache()
    return new_v


def freeze(indent_id: str, base_version: int, po_file_name: str, user: str,
           po_file_link: str = "", po_qty: dict | None = None, po_number: str = "",
           po_has_extra: bool = False, replace: bool = False) -> tuple[int, bool]:
    """Record a customer's PO for the indent. A difference with the indent never
    blocks the upload; it is shown on the indent and in the hourly tracker.
    - Most customers: one PO, which freezes the indent (status Frozen).
    - Multi-PO customers (Swiggy): each PO is added; the indent stays open for
      more POs until End of POs (`end_pos`).
    Returns (indent version, frozen)."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    stamp = config.now_iso()
    if replace and cur is not None and cur.status == STATUS_FROZEN and not is_multi_po(cur.header.customer):
        # owner: a wrong PO is replaced by a new upload; only the latest PO counts
        backend.append_dicts(PO_FREEZE, [_po_row(cur, cur.version, PO_KIND, user, stamp, po_file_name,
                                                 po_file_link, po_number, po_qty)])
        clear_cache()
        return cur.version, True
    _check_editable(cur, indent_id, base_version, allow_locked=True)
    extra = " (PO has items not on the indent)" if po_has_extra else ""
    if is_multi_po(cur.header.customer):
        backend.append_dicts(PO_FREEZE, [_po_row(cur, cur.version, PO_KIND, user, stamp, po_file_name,
                                                 po_file_link, po_number, po_qty)])
        clear_cache()
        return cur.version, False
    new_v, stamp = _status_row(backend, df, cur, STATUS_FROZEN, user, "PO uploaded",
                               f"{po_file_name}; indent frozen{extra}")
    backend.append_dicts(PO_FREEZE, [_po_row(cur, new_v, PO_KIND, user, stamp, po_file_name,
                                             po_file_link, po_number, po_qty)])
    clear_cache()
    return new_v, True


def end_pos(indent_id: str, base_version: int, user: str) -> int:
    """Multi-PO customers: no more POs are coming for this indent -> freeze it."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    _check_editable(cur, indent_id, base_version, allow_locked=True)
    n = po_info(read_po_freeze(), indent_id)["pos"]
    new_v, stamp = _status_row(backend, df, cur, STATUS_FROZEN, user, "End of POs",
                               f"{n} PO(s) received; indent frozen")
    backend.append_dicts(PO_FREEZE, [_po_row(cur, new_v, PO_END, user, stamp)])
    clear_cache()
    return new_v


def _qty_json(raw) -> dict:
    try:
        d = json.loads(str(raw or "") or "{}")
        return {str(k): float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def po_info(po: pd.DataFrame | None, indent_id: str) -> dict:
    """POs of one indent: count, End of POs pressed?, PO qty per SKU (sum of all
    POs for multi-PO customers, else the latest PO; None when no PO has qty per
    item), PO numbers."""
    out = {"pos": 0, "ended": False, "qty": None, "numbers": []}
    if po is None or po.empty or "indent_id" not in po.columns:
        return out
    rows = po[po["indent_id"].astype(str) == str(indent_id)]
    kind = rows["kind"].astype(str).str.strip().str.lower() if "kind" in rows.columns else pd.Series(
        [""] * len(rows), index=rows.index)
    pos = rows[kind != PO_END]
    if len(pos) > 1 and not is_multi_po(str(pos["po_customer"].iloc[-1]) if "po_customer" in pos.columns else ""):
        pos = pos.iloc[[-1]]                     # one-PO customers: a re-upload replaces the PO
    out["pos"] = len(pos)
    out["ended"] = bool((kind == PO_END).any())
    out["numbers"] = [str(x) for x in pos.get("po_number", pd.Series(dtype=str)) if str(x or "").strip()]
    if "po_qty_json" in pos.columns and pos["po_qty_json"].astype(str).str.strip().ne("").any():
        tot: dict[str, float] = {}
        for raw in pos["po_qty_json"]:
            for k, v in _qty_json(raw).items():
                tot[k] = tot.get(k, 0.0) + v
        out["qty"] = tot
    return out


def latest_po() -> dict[str, dict]:
    """Per indent: its latest uploaded PO row, plus `_pos` (how many POs) and
    `po_number` = all PO numbers joined (multi-PO customers)."""
    try:
        po = read_po_freeze()
    except SheetError:
        return {}
    if po is None or po.empty or "indent_id" not in po.columns:
        return {}
    out: dict[str, dict] = {}
    for r in po.to_dict("records"):
        if str(r.get("kind", "") or "").strip().lower() == PO_END:
            continue
        iid = str(r.get("indent_id", ""))
        prev = out.get(iid)
        nums = ([prev["po_number"]] if prev and prev.get("po_number") else []) + \
            ([str(r.get("po_number", "") or "").strip()] if str(r.get("po_number", "") or "").strip() else [])
        out[iid] = {**r, "_pos": (prev["_pos"] if prev else 0) + 1, "po_number": ", ".join(nums)}
    return out


def _nkey(s: str) -> str:
    return " ".join(str(s or "").split()).casefold()


def _rematch(by: dict, lines: list[IndentLine]) -> None:
    """PO names that are not exactly an indent item (e.g. a PO saved with the
    customer's own name) are matched to a still-unmatched indent item with the
    same words (core.po_reader), so old POs compare correctly too."""
    from core import po_reader
    names = {_nkey(x.customer_sku_name): x.customer_sku_name for x in lines}
    free = [n for k, n in names.items() if k not in by]
    for k in [k for k in list(by) if k not in names]:
        if not free:
            break
        name, v = by[k]
        hit, _ = po_reader.find_in_indent(name, free)
        if hit and _nkey(hit) not in by:
            del by[k]
            by[_nkey(hit)] = (hit, v)
            free.remove(hit)


def po_vs_indent(lines: list[IndentLine], info: dict) -> list[dict]:
    """Indent qty vs PO qty, per item (same Customer SKU Name, spaces/case ignored).
    An indent item that is not on the PO has po_qty None (never shown as 0);
    PO-only items come last with indent_qty None."""
    if info["qty"] is None:
        return []
    by = {_nkey(k): (k, v) for k, v in info["qty"].items()}
    _rematch(by, lines)
    out = []
    for x in lines:
        hit = by.pop(_nkey(x.customer_sku_name), None)
        ind = to_number(x.qty)
        po = None if hit is None else hit[1]
        out.append({"customer_sku_name": x.customer_sku_name, "lot": x.lot, "indent_qty": ind,
                    "po_qty": po, "diff": (po or 0.0) - ind,
                    "ok": (po is None and abs(ind) < 1e-9) or (po is not None and abs(po - ind) < 1e-9)})
    for name, v in by.values():
        out.append({"customer_sku_name": name, "lot": "", "indent_qty": None, "po_qty": v, "diff": v,
                    "ok": abs(v) < 1e-9})
    return out


__all__ = ["find_duplicate", "DuplicateError", "edit_deadline", "can_edit", "deadline_text", "delivery_bounds", "date_allowed", "created_at", "CutoffError", "read_lines", "current_rows", "summary", "versions", "snapshot", "validate",
           "submit_new", "submit_update", "freeze", "lock", "end_pos", "po_info", "po_vs_indent", "is_multi_po",
           "next_indent_id", "build_rows",
           "ConflictError", "FrozenError", "NothingChangedError", "fmt_num"]


def owner_delete_days() -> int:
    try:
        return max(0, int(config.get("owner_delete_days", 2)))
    except (TypeError, ValueError):
        return 2


def owner_can_delete(delivery_date: str) -> bool:
    """Owners may delete an indent until 2 days after its delivery date (T-2),
    even after the edit cutoff and even when a PO was uploaded."""
    try:
        d = date.fromisoformat(str(delivery_date)[:10])
    except ValueError:
        return False
    return d >= config.now_ist().date() - timedelta(days=owner_delete_days())


def cancel(indent_id: str, base_version: int, user: str, owner: bool = False) -> int:
    """'Delete' an indent: append a copy of the current version with status
    Cancelled. It disappears from production, the store/date becomes free,
    and every earlier version stays in the sheet. owner=True: allowed until
    2 days after the delivery date, also after the cutoff and after a PO."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    if owner:
        if cur is None:
            raise SheetError(f"Indent {indent_id} was not found in the sheet.")
        if cur.status == STATUS_CANCELLED:
            raise FrozenError(f"{indent_id} is already deleted.")
        if cur.version != int(base_version):
            raise ConflictError(f"{indent_id} was changed by {cur.submitted_by} meanwhile. Please try again.")
        if not owner_can_delete(cur.header.delivery_date):
            raise CutoffError(f"{indent_id} is older than {owner_delete_days()} days after its delivery "
                              "date and can no longer be deleted.")
    else:
        _check_editable(cur, indent_id, base_version)
        if not can_edit(cur.header.delivery_date, customer=cur.header.customer):
            raise CutoffError(f"{indent_id} can no longer be deleted: editing closed at "
                              f"{deadline_text(cur.header.delivery_date, cur.header.customer)}.")
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(indent_id, new_v, STATUS_CANCELLED, stamp, user, cur.header, cur.lines,
                      note=change_note("Deleted", user, creator_of(df, indent_id), stamp,
                                       "whole indent deleted (Cancelled)"
                                       + (" by the owner; it had a PO" if cur.status == STATUS_FROZEN else "")))
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


def move_date(indent_id: str, base_version: int, new_date: str, user: str) -> int:
    """Owner: change an indent's delivery date (e.g. a retro order that was placed
    for the wrong day), ignoring the cutoff. Same status; a new version and a
    Change_Log row are written. Refused if that store already has an indent that day."""
    backend = get_backend()
    df = prepare(backend.read(INDENT_LINES))
    cur = snapshot(df, indent_id)
    if cur is None or cur.status == STATUS_CANCELLED:
        raise SheetError(f"{indent_id} was not found or is deleted.")
    if cur.version != int(base_version):
        raise ConflictError(f"{indent_id} was changed meanwhile. Please try again.")
    old = cur.header.delivery_date
    if str(new_date) == str(old):
        raise NothingChangedError("That is already the delivery date.")
    header = IndentHeader(**{**cur.header.to_dict(), "delivery_date": str(new_date)})
    dup = find_duplicate(df, header, exclude_id=indent_id)
    if dup:
        raise DuplicateError(duplicate_message(dup, header), dup)
    new_v = cur.version + 1
    stamp = config.now_iso()
    rows = build_rows(indent_id, new_v, cur.status, stamp, user, header, cur.lines,
                      note=change_note("Date moved", user, creator_of(df, indent_id), stamp,
                                       f"delivery date {old} -> {new_date} (owner)"))
    if not _append_verified(backend, rows, indent_id, new_v, stamp, user):
        clear_cache()
        raise ConflictError(f"Someone else saved {indent_id} at the same moment. Please try again.")
    try:
        backend.append_dicts(CHANGE_LOG, changelog.to_rows(
            [{"change_type": "header_changed", "customer_sku_name": "", "field": "delivery_date",
              "old_value": old, "new_value": str(new_date)}],
            indent_id=indent_id, from_version=cur.version, to_version=new_v, changed_by=user, changed_at=stamp))
    except SheetError:
        pass
    clear_cache()
    return new_v


RESET_TABS = (INDENT_LINES, CHANGE_LOG, PO_FREEZE, DRAFTS)


def backup_and_clear(user: str) -> dict:
    """Start fresh: copy every indent tab to Backup_<time>_<tab>, then leave
    only the header row in Indent_Lines, Change_Log, PO_Freeze and Drafts.
    Returns {tab: rows cleared}. Numbering starts again at IN-001."""
    backend = get_backend()
    stamp = config.now_ist().strftime("%Y%m%d_%H%M")
    present = set(backend.list_tabs())
    done = {}
    for tab in RESET_TABS:
        if tab not in present:
            continue
        values = backend._get_values([tab]).get(tab, [])
        rows = max(0, len([r for r in values[1:] if any(str(c).strip() for c in r)]))
        done[tab] = rows
        if not rows:
            continue
        backend.replace_tab(f"Backup_{stamp}_{tab}", values)
        header = [str(h) for h in values[0]] if values and any(values[0]) else list(TABS[tab])
        backend.replace_tab(tab, [header])
        backend._headers[tab] = header
    clear_cache()
    return done
