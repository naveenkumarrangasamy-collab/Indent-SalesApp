"""Production sheet aggregation (spec 5.8).

Input: current-version Indent_Lines rows (already filtered by date, city and
scope) and the SKU map. Output: one row per
Parent SKU > Variety > Spec (active origin, size) > Lot, with total qty and
the customer SKU names that feed the group.
"""
from __future__ import annotations

import pandas as pd

from core.masters import Masters
from core.models import fmt_num, to_number

OUTPUT_COLUMNS = ["Parent SKU", "Variety", "Origin", "Size", "Lot", "Total Qty",
                  "Lines", "Indents", "Customer SKU Names"]

NO_ORIGIN = "(origin not set)"


def aggregate(lines: pd.DataFrame, masters: Masters) -> pd.DataFrame:
    if lines is None or lines.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    df = lines.copy()
    specs = [masters.spec(r.city, r.customer, r.customer_sku_name) for r in df.itertuples()]
    df["Origin"] = [s[0] or NO_ORIGIN for s in specs]
    df["Size"] = [s[1] for s in specs]
    df["qty"] = df["qty"].map(to_number)
    df["variety"] = df["variety"].fillna("").astype(str)
    g = (df.groupby(["parent_sku", "variety", "Origin", "Size", "lot"], dropna=False)
           .agg(**{"Total Qty": ("qty", "sum"),
                   "Lines": ("customer_sku_name", "size"),
                   "Indents": ("indent_id", "nunique"),
                   "Customer SKU Names": ("customer_sku_name",
                                          lambda s: ", ".join(sorted(set(s), key=str.casefold)))})
           .reset_index()
           .rename(columns={"parent_sku": "Parent SKU", "variety": "Variety", "lot": "Lot"}))
    g["Total Qty"] = g["Total Qty"].map(lambda v: float(fmt_num(v)))
    g = g.sort_values(["Parent SKU", "Variety", "Origin", "Size", "Lot"],
                      key=lambda s: s.astype(str).str.casefold())
    return g[OUTPUT_COLUMNS].reset_index(drop=True)


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
