"""Production sheet aggregation (spec 5.8).

Input: current-version Indent_Lines rows (already filtered by date, city and
scope) and the SKU map. Output: one row per
Parent SKU > Variety > Spec (active origin, size) > Lot, with total qty and
the customer SKU names that feed the group.
"""
from __future__ import annotations

import pandas as pd

from core.lots import lot_size
from core.masters import Masters
from core.models import fmt_num, to_number

OUTPUT_COLUMNS = ["City", "Parent SKU", "Customer SKU Name", "Variety", "Origin", "Lot", "Lot Size",
                  "Spec-Size", "Total Qty", "Customers", "Indents"]

CITY_SKU_COLUMNS = ["City", "Customer", "Parent SKU", "Customer SKU Name", "Variety", "Lot",
                    "Lot Size", "Spec-Size", "Qty", "Indents", "Stores"]

NO_ORIGIN = "(origin not set)"


def _whole(col: pd.Series) -> pd.Series:
    """Quantities as whole numbers (30, not 30.0) when they all are."""
    vals = col.map(lambda v: float(fmt_num(v)))
    return vals.astype(int) if (vals % 1 == 0).all() else vals


def _prep(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    df = lines.copy()
    df["qty"] = df["qty"].map(to_number)
    df = df[df["qty"] > 0].copy()   # items set to 0 (no indent) produce nothing
    df["variety"] = df["variety"].fillna("").astype(str)
    df["Lot Size"] = df["customer_sku_name"].map(lot_size)
    if masters is not None:
        df["Spec-Size"] = [masters.spec_size(r.city, r.customer, r.customer_sku_name)
                           for r in df.itertuples()]
    else:
        df["Spec-Size"] = ""
    return df


def _join(values) -> str:
    seen = []
    for v in values:
        v = str(v or "").strip()
        if v and v not in seen:
            seen.append(v)
    return " / ".join(seen)


def aggregate(lines: pd.DataFrame, masters: Masters, with_spec: bool = False) -> pd.DataFrame:
    """Production sheet: ONE row per City + Parent SKU + Customer SKU name +
    Variety + Spec-Size + Lot size (+ Lot), adding up every customer and store
    of that city. Names differing only in case/spacing count as the same.
    Origin only when with_spec (show_spec)."""
    cols = OUTPUT_COLUMNS if with_spec else [c for c in OUTPUT_COLUMNS if c != "Origin"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    df = _prep(lines, masters)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["Origin"] = ([masters.spec(r.city, r.customer, r.customer_sku_name)[0] or NO_ORIGIN
                     for r in df.itertuples()] if with_spec else "")
    df["_name"] = df["customer_sku_name"].map(lambda v: " ".join(str(v).split()))
    df["_key"] = df["_name"].str.casefold()
    df["_city"] = df["city"].map(lambda v: " ".join(str(v).split()))
    df["_ckey"] = df["_city"].str.casefold()
    df["_pkey"] = df["parent_sku"].map(lambda v: " ".join(str(v).split()).casefold())
    keys = ["_ckey", "_pkey", "_key", "variety", "Spec-Size", "Lot Size", "lot"]
    g = (df.groupby(keys, dropna=False, sort=False)
           .agg(**{"City": ("_city", "first"),
                   "Parent SKU": ("parent_sku", "first"),
                   "Customer SKU Name": ("_name", lambda s: s.mode().iloc[0]),
                   "Origin": ("Origin", _join),
                   "Total Qty": ("qty", "sum"),
                   "Customers": ("customer", lambda s: ", ".join(sorted(set(s), key=str.casefold))),
                   "Indents": ("indent_id", "nunique")})
           .reset_index()
           .rename(columns={"variety": "Variety", "lot": "Lot"}))
    g["Total Qty"] = _whole(g["Total Qty"])
    g = g.sort_values(["City", "Parent SKU", "Customer SKU Name", "Variety", "Spec-Size", "Lot Size"],
                      key=lambda s: s.astype(str).str.casefold())
    return g[cols].reset_index(drop=True)


def filter_lines(current: pd.DataFrame, *, delivery_date: str | None, city: str | None,
                 allowed_ids: set[str] | None) -> pd.DataFrame:
    """Filter current-version rows by delivery date, city and (for sales
    users) the indents they created. `allowed_ids=None` means no limit."""
    df = current
    if df.empty:
        return df
    if delivery_date:
        df = df[df["delivery_date"] == delivery_date]
    if city:
        df = df[df["city"].str.casefold() == city.casefold()]
    if allowed_ids is not None:
        df = df[df["indent_id"].isin(allowed_ids)]
    return df


def city_sku_report(lines: pd.DataFrame, masters: Masters | None = None) -> pd.DataFrame:
    """City > Customer > Parent SKU > Customer SKU name (+ variety, lot,
    lot size) with total qty, from current-version indent rows."""
    if lines is None or lines.empty:
        return pd.DataFrame(columns=CITY_SKU_COLUMNS)
    df = _prep(lines, masters)
    if df.empty:
        return pd.DataFrame(columns=CITY_SKU_COLUMNS)
    g = (df.groupby(["city", "customer", "parent_sku", "customer_sku_name", "variety", "lot",
                     "Lot Size", "Spec-Size"], dropna=False)
           .agg(Qty=("qty", "sum"), Indents=("indent_id", "nunique"), Stores=("store", "nunique"))
           .reset_index()
           .rename(columns={"city": "City", "customer": "Customer", "parent_sku": "Parent SKU",
                            "customer_sku_name": "Customer SKU Name", "variety": "Variety",
                            "lot": "Lot"}))
    g["Qty"] = _whole(g["Qty"])
    g = g.sort_values(["City", "Customer", "Parent SKU", "Customer SKU Name"],
                      key=lambda s: s.astype(str).str.casefold())
    return g[CITY_SKU_COLUMNS].reset_index(drop=True)


def delivery_dates(current: pd.DataFrame) -> list[str]:
    """Distinct delivery dates (YYYY-MM-DD) that have indents, ascending."""
    if current is None or current.empty:
        return []
    return sorted(d for d in current["delivery_date"].astype(str).unique() if d)


def default_date(dates: list[str], today: str) -> str | None:
    """The first delivery date from today on that has indents, else the latest."""
    upcoming = [d for d in dates if d >= today]
    return upcoming[0] if upcoming else (dates[-1] if dates else None)
