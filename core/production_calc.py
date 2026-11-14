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
                  "Spec-Size", "Total Qty", "Stores", "Indents", "Store Names"]

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
    df["variety"] = df["variety"].fillna("").astype(str)
    df["Lot Size"] = df["customer_sku_name"].map(lot_size)
    if masters is not None:
        df["Spec-Size"] = [masters.spec_size(r.city, r.customer, r.customer_sku_name)
                           for r in df.itertuples()]
    else:
        df["Spec-Size"] = ""
    return df


def aggregate(lines: pd.DataFrame, masters: Masters, with_spec: bool = False) -> pd.DataFrame:
    """Production sheet: one row per City + Customer SKU name (+ variety, lot,
    lot size, Spec-Size), adding up every store that ordered it. Origin only
    when with_spec (show_spec)."""
    cols = OUTPUT_COLUMNS if with_spec else [c for c in OUTPUT_COLUMNS if c != "Origin"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    df = _prep(lines, masters)
    df["Origin"] = ([masters.spec(r.city, r.customer, r.customer_sku_name)[0] or NO_ORIGIN
                     for r in df.itertuples()] if with_spec else "")
    df["_sku"] = df["customer_sku_name"].map(lambda v: " ".join(str(v).split()))
    keys = ["city", "parent_sku", "_sku", "variety", "Origin", "lot", "Lot Size", "Spec-Size"]
    g = (df.groupby(keys, dropna=False)
           .agg(**{"Total Qty": ("qty", "sum"),
                   "Stores": ("store", "nunique"),
                   "Indents": ("indent_id", "nunique"),
                   "Store Names": ("store", lambda s: ", ".join(sorted(set(s), key=str.casefold)))})
           .reset_index()
           .rename(columns={"city": "City", "parent_sku": "Parent SKU", "_sku": "Customer SKU Name",
                            "variety": "Variety", "lot": "Lot"}))
    g["Total Qty"] = _whole(g["Total Qty"])
    g = g.sort_values(["City", "Parent SKU", "Customer SKU Name", "Variety", "Lot"],
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
