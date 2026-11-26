"""Pre-Production Actual (25 Nov, trial): what goes onto the grading tables.

Inspired by the team's "BLR_Production Actual Master" sheet (tab BLR_ProdTracking, columns C-L).
One entry = one fruit lot on one table: Parent SKU, Origin, Variety, Brand, Size, box kg, pieces per
box, table, boxes moved and the stock it came from. Saved to the app's own tab PREPROD_ENTRIES
(the team's sheet is never written).

Dropdown lists = New Mapping sheet Parent tab + the values seen in the team's sheet (SEED) + every
value saved here before (so a new brand typed once shows next time)."""
from __future__ import annotations

import re
import uuid

import pandas as pd

from core import config
from core.models import to_number
from core.schema import PREPROD_ENTRIES

STOCK_TYPES = ["Unused Vendor Lot", "Returns", "MT Ready Leftover"]  # still valid in saved rows
STOCK_CHOICES = ["Unused Vendor Lot"]  # 26 Nov (user): only unused stock is offered for now
COLS = ["origin", "variety", "brand", "size", "box_kg", "pcs"]

# Values read from BLR_ProdTracking (24-25 Nov), names cleaned (mandrin -> Mandarin, enay -> Envy …).
SEED = [
    ("Kiwi", "", "Gold", "Zespri", "", 5.6, 59),
    ("Kiwi", "", "Green", "", "33mm", 10, 100),
    ("Blueberry", "", "", "Beta", "16mm", 1.5, 12),
    ("Grapes", "China", "Crimson Red", "", "22mm+", 6, None),
    ("Grapes", "China", "Red Globe", "", "22mm+", 6.5, None),
    ("Avocado", "", "", "Asli", "16C", 4, 16),
    ("Avocado", "", "", "Asli", "24C", 4, 24),
    ("Avocado", "", "", "Asli", "26C", 4, 26),
    ("Grapefruit", "", "", "", "50C", 16, 50),
    ("Apple", "NZ", "Gala", "Envy", "30C", 10, 30),
    ("Apple", "", "Gala", "", "90C", 17.5, 90),
    ("Apple", "", "Gala", "", "113C", 18, 113),
    ("Apple", "", "Granny Smith", "", "120C", 18, 120),
    ("Apple", "", "Queen", "", "120C", 18, 120),
    ("Mandarin", "Australia", "", "Gold Fresh", "80C", 9, 80),
    ("Mandarin", "Australia", "", "Gold Fresh", "88C", 9, 88),
    ("Orange", "", "", "Alliance", "80C", 15, 80),
]

_ALIASES = {"bb": "blueberry", "blueberries": "blueberry", "mandrin": "mandarin", "grape fruit": "grapefruit",
            "kiwi gold": "kiwi", "kiwi green": "kiwi", "kiwi sungold": "kiwi", "c.r grapes": "grapes"}


BOX_ONLY = {"blueberry"}   # counted only in boxes / trays: no pieces per box (user 25 Nov)


def box_only(parent) -> bool:
    return pkey(parent) in BOX_ONLY


def pkey(parent) -> str:
    s = re.sub(r"\s+", " ", str(parent or "").strip().lower())
    return _ALIASES.get(s, s)


def _t(v) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in {"nan", "none"} else re.sub(r"\s+", " ", s)


def clean_size(v) -> str:
    """'30 C' / '24c' -> '30C', '16 mm' -> '16mm', '22 mm+ dia' -> '22mm+'."""
    s = _t(v)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*c", s, flags=re.I)
    if m:
        return f"{m.group(1)}C"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*mm\s*(\+)?.*", s, flags=re.I)
    if m:
        return f"{m.group(1)}mm{m.group(2) or ''}"
    return s


def count_of(size: str) -> int | None:
    """Pieces per box from a count size ('30C' -> 30); None for mm / other sizes."""
    m = re.fullmatch(r"(\d+)C", clean_size(size))
    return int(m.group(1)) if m else None


def _num(v):
    """A positive number, else None (blank, text, NaN)."""
    try:
        n = float(to_number(v))
    except (TypeError, ValueError):
        return None
    return n if n == n and n > 0 else None


def option_rows(parent: str, parent_tab: pd.DataFrame | None, saved: pd.DataFrame | None) -> pd.DataFrame:
    """Every known combination for this parent (origin, variety, brand, size, box_kg, pcs)."""
    k, rows = pkey(parent), []
    for p, o, v, b, s, kg, pcs in SEED:
        if pkey(p) == k:
            rows.append({"origin": o, "variety": v, "brand": b, "size": s, "box_kg": kg, "pcs": pcs})
    if parent_tab is not None and not parent_tab.empty:
        for r in parent_tab[parent_tab["parent"].map(pkey) == k].to_dict("records"):
            for s in [x.strip() for x in str(r.get("spec") or "").split(",") if x.strip()] or [""]:
                size = clean_size(s if not re.fullmatch(r"\d+", s) else f"{s}C")
                rows.append({"origin": _t(r.get("country")), "variety": _t(r.get("grade")), "brand": "",
                             "size": size, "box_kg": _num(r.get("box_kg")), "pcs": count_of(size)})
    if saved is not None and not saved.empty:
        for r in saved[saved["parent_sku"].map(pkey) == k].to_dict("records"):
            rows.append({"origin": _t(r.get("origin")), "variety": _t(r.get("variety")),
                         "brand": _t(r.get("brand")), "size": clean_size(r.get("size")),
                         "box_kg": _num(r.get("box_kg")), "pcs": _num(r.get("pcs_per_box"))})
    df = pd.DataFrame(rows, columns=COLS)
    for c in ("origin", "variety", "brand", "size"):
        df[c] = df[c].map(_t)
    return df


def _match(df: pd.DataFrame, **picked) -> pd.DataFrame:
    """Rows that fit every pick. Per column: exact rows first; rows that leave that column blank
    (e.g. a size known without a country) only when no row names the pick. Never falls back to all."""
    out = df
    for col, val in picked.items():
        if not val:
            continue
        exact = out[out[col].str.casefold() == str(val).casefold()]
        out = exact if not exact.empty else out[out[col] == ""]
    return out


def choices(df: pd.DataFrame, col: str, **picked) -> list[str]:
    """Values for one dropdown, only from rows that fit what is already picked (26 Nov: strict)."""
    seen, out = set(), []
    for v in _match(df, **picked)[col]:
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


def defaults(df: pd.DataFrame, **picked) -> tuple[float | None, int | None]:
    """Box kg and pieces per box for the picked origin / variety / brand / size."""
    sub = _match(df, **picked)
    kg = next((float(x) for x in sub["box_kg"] if _num(x)), None)
    pcs = count_of(picked.get("size", "")) or next((int(float(x)) for x in sub["pcs"] if _num(x)), None)
    return kg, pcs


def brands(df: pd.DataFrame, origin: str = "", variety: str = "") -> list[str]:
    return choices(df, "brand", origin=origin, variety=variety)


def entry_errors(e: dict) -> list[str]:
    errs = []
    if not e.get("parent_sku"):
        errs.append("Fruit")
    if not e.get("size"):
        errs.append("Size")
    if not _num(e.get("box_kg")):
        errs.append("Box kg")
    if not e.get("table_no"):
        errs.append("Table")
    if not _num(e.get("boxes_moved")):
        errs.append("Boxes")
    if e.get("stock_type") not in STOCK_TYPES:
        errs.append("Stock")
    return errs


def save(backend, entries: list[dict], user: str) -> int:
    stamp = config.now_iso()
    rows = [{"entry_id": uuid.uuid4().hex[:10], "saved_at": stamp, "saved_by": user, **e} for e in entries]
    if rows:
        backend.append_dicts(PREPROD_ENTRIES, rows)
        from core import tracking_sheet
        tracking_sheet.publish(backend)
        from core import indents
        try:
            indents.clear_cache()
        except Exception:  # noqa: BLE001
            pass
    return len(rows)


VIEW = {"production_date": "Date", "city": "City", "parent_sku": "Fruit", "origin": "Origin", "variety": "Variety",
        "brand": "Brand", "size": "Size", "box_kg": "Box kg", "pcs_per_box": "Pcs/box", "table_no": "Table",
        "boxes_moved": "Boxes", "stock_type": "Stock", "saved_by": "By"}


def view(saved: pd.DataFrame, day: str | None = None, city: str | None = None) -> pd.DataFrame:
    """Saved entries for a date (ISO) / city, with short column names and Kg on table."""
    cols = list(VIEW.values()) + ["Kg on table"]
    if saved is None or saved.empty or "production_date" not in saved.columns:
        return pd.DataFrame(columns=cols)
    d = saved.copy()
    d["production_date"] = d["production_date"].astype(str).str[:10]
    if day:
        d = d[d["production_date"] == day]
    if city:
        d = d[d["city"].astype(str) == city]
    for c in VIEW:
        if c not in d.columns:
            d[c] = ""
    out = d[list(VIEW)].rename(columns=VIEW)
    out["Kg on table"] = [round((_num(a) or 0) * (_num(b) or 0), 2) for a, b in zip(out["Box kg"], out["Boxes"])]
    return out.reset_index(drop=True)


def read(backend=None) -> pd.DataFrame:
    from core import store_settings
    df = store_settings._read(backend, PREPROD_ENTRIES)
    return df if not df.empty else pd.DataFrame(columns=["parent_sku"])
