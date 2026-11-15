"""Production and batching.

1. Production sheet: the total quantity to produce and grade for all
   customers, per City + Parent SKU + Variety + Lot + Lot size + Spec.
2. Batching sheet: the same quantities split per delivery point
   (city > customer > store), to allocate the ready stock and dispatch.
"""
from __future__ import annotations

import pandas as pd

from core import boxes
from core.lots import lot_size
from core.masters import Masters
from core.models import fmt_num, to_number




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


PRODUCTION_COLUMNS = ["City", "Parent SKU", "Customer SKU Name", "Variety", "Lot", "Lot Size", "Spec", "Total Qty"]
BOX_OUT = ["Units", "Box", "Boxes"]
BATCH_COLUMNS = ["City", "Customer", "Delivery point", "Parent SKU", "Customer SKU Name", "Variety", "Lot", "Lot Size",
                 "Spec", "Qty", "Indent"]
NOT_MAPPED = "spec not mapped"


def _spec_rows(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Indent rows with the production attributes: variety (as entered, else
    from the mapping), lot size and the agreed spec (Spec-Size + grade from
    Mapping Whole). A SKU without a spec gets 'spec not mapped (name)' so it is
    never clubbed with a different product by mistake."""
    df = _prep(lines, masters)
    if df.empty:
        return df
    if masters is not None:
        df["Variety"] = [v or masters.mapped_variety(r.city, r.customer, r.customer_sku_name)
                         for v, r in zip(df["variety"], df.itertuples())]
        df["Spec"] = [masters.spec_label(r.city, r.customer, r.customer_sku_name)
                      or f"{NOT_MAPPED} ({' '.join(str(r.customer_sku_name).split())})"
                      for r in df.itertuples()]
    else:
        df["Variety"] = df["variety"]
        df["Spec"] = df["customer_sku_name"].map(lambda n: f"{NOT_MAPPED} ({n})")
    df["City"] = df["city"].map(lambda v: " ".join(str(v).split()))
    df["Parent SKU"] = df["parent_sku"].map(lambda v: " ".join(str(v).split()))
    df["Customer SKU Name"] = df["customer_sku_name"].map(lambda v: " ".join(str(v).split()))
    df["Lot"] = df["lot"]
    # what the qty means physically (for the box conversion)
    unit = [boxes.per_lot(lot, size) for lot, size in zip(df["lot"], df["Lot Size"])]
    df["_pcs"] = [q * n if u == "pcs" else 0.0 for (u, n), q in zip(unit, df["qty"])]
    df["_kg"] = [q * n if u == "kg" else 0.0 for (u, n), q in zip(unit, df["qty"])]
    df["_box"] = [q if u == "box" else 0.0 for (u, _), q in zip(unit, df["qty"])]
    df["_boxkg"] = ([masters.box_kg(r.city, r.customer, r.customer_sku_name) for r in df.itertuples()]
                    if masters is not None else None)
    return df


_SORT = lambda s: s.astype(str).str.casefold()  # noqa: E731


def production(lines: pd.DataFrame, masters: Masters | None,
               box_rules: list | None = None) -> pd.DataFrame:
    """Production sheet: the total to produce and grade, for ALL customers.
    One row per City + Parent SKU + Customer SKU name + Variety + Lot + Lot
    size + Spec. No customer names (those are on the batching sheet).
    With box_rules (a list, may be empty) the qty is also converted into
    boxes: Units (pcs / kg), Box, Boxes."""
    cols = PRODUCTION_COLUMNS + (BOX_OUT if box_rules is not None else [])
    df = _spec_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    keys = ["City", "Parent SKU", "Customer SKU Name", "Variety", "Lot", "Lot Size", "Spec"]
    g = (df.assign(**{k + "_k": df[k].astype(str).str.casefold() for k in keys})
           .groupby([k + "_k" for k in keys], sort=False)
           .agg(**{k: (k, "first") for k in keys}, **{"Total Qty": ("qty", "sum")},
                _pcs=("_pcs", "sum"), _kg=("_kg", "sum"), _box=("_box", "sum"),
                _boxkg=("_boxkg", lambda s: next((float(v) for v in s if v and v == v), 0.0)))
           .reset_index(drop=True))
    g["Total Qty"] = _whole(g["Total Qty"])
    if box_rules is not None:
        conv = [boxes.convert(r["Parent SKU"], r["Spec"], r["_pcs"], r["_kg"], r["_box"], r["_boxkg"] or None,
                              box_rules)
                for r in g.to_dict("records")]
        g["Units"], g["Box"], g["Boxes"] = zip(*conv) if conv else ([], [], [])
    return g.sort_values(keys, key=_SORT)[cols].reset_index(drop=True)


def batching(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Batching sheet: how the produced stock is split per delivery point
    (city > customer > store), with the same variety / lot / lot size / spec
    as the production sheet so the totals add up."""
    df = _spec_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return pd.DataFrame(columns=BATCH_COLUMNS)
    df["Customer"], df["Delivery point"] = df["customer"], df["store"]
    keys = ["City", "Customer", "Delivery point", "Parent SKU", "Customer SKU Name", "Variety", "Lot",
            "Lot Size", "Spec"]
    g = (df.groupby(keys, sort=False, dropna=False)
           .agg(Qty=("qty", "sum"), Indent=("indent_id", lambda s: ", ".join(sorted(set(s)))))
           .reset_index())
    g["Qty"] = _whole(g["Qty"])
    return g.sort_values(keys, key=_SORT)[BATCH_COLUMNS].reset_index(drop=True)


def unmapped(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Customer SKU names in these indents that have no spec yet."""
    df = _spec_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return pd.DataFrame(columns=["City", "Customer", "Parent SKU", "Customer SKU Name"])
    bad = df[df["Spec"].str.startswith(NOT_MAPPED)]
    return (bad[["City", "customer", "Parent SKU", "customer_sku_name"]].drop_duplicates()
            .rename(columns={"customer": "Customer", "customer_sku_name": "Customer SKU Name"})
            .reset_index(drop=True))


def spec_mapping_list(masters: Masters) -> pd.DataFrame:
    """Every customer SKU name of the mapping with what production uses for
    it, and what is still missing (the backend list to complete)."""
    sku = masters.sku
    if sku is None or sku.empty:
        return pd.DataFrame()
    base = sku[["City", "Customer", "Parent SKU", "Customer SKU Name"]].drop_duplicates()
    rows = []
    for r in base.itertuples(index=False):
        city, cust, parent, name = r
        origin, _ = masters.spec(city, cust, name)
        size, grade = masters.spec_size(city, cust, name), masters.spec_grade(city, cust, name)
        variety = masters.mapped_variety(city, cust, name)
        missing = [w for w, v in (("Spec-Size", size), ("Grade", grade)) if not v]
        rows.append({"City": city, "Customer": cust, "Parent SKU": parent, "Customer SKU Name": name,
                     "Variety": variety, "Lot": masters.lot_for(city, cust, name), "Lot Size": lot_size(name),
                     "Active origin": origin, "Spec-Size": size, "Grade": grade,
                     "Spec used in production": " - ".join(x for x in (size, grade) if x) or NOT_MAPPED,
                     "To fill in": ", ".join(missing) or "complete"})
    out = pd.DataFrame(rows)
    return out.sort_values(["City", "Parent SKU", "Customer", "Customer SKU Name"], key=_SORT).reset_index(drop=True)


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


def delivery_dates(current: pd.DataFrame) -> list[str]:
    """Distinct delivery dates (YYYY-MM-DD) that have indents, ascending."""
    if current is None or current.empty:
        return []
    return sorted(d for d in current["delivery_date"].astype(str).unique() if d)


def default_date(dates: list[str], today: str) -> str | None:
    """The first delivery date from today on that has indents, else the latest."""
    upcoming = [d for d in dates if d >= today]
    return upcoming[0] if upcoming else (dates[-1] if dates else None)
