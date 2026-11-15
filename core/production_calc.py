"""Production and batching.

1. Production sheet: the total quantity to produce and grade for all
   customers, per City + Parent SKU + Variety + Spec + Repacking + Unit.
   Kept simple on purpose: no lot / lot size columns and no box conversion
   (the ground team plans the boxes from the repacking spec).
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


PRODUCTION_COLUMNS = ["City", "Parent SKU", "Variety", "Repacking", "Spec-Size", "Lot Size", "Qty", "Total"]
BOX_COL = "Boxes @ count {}"   # one column per count in Spec-Size (22C, 24C -> 2 columns)
NOT_IN_BASE = "not in New tab"
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
    mapped = ([masters.repacking(r.city, r.customer, r.customer_sku_name) for r in df.itertuples()]
              if masters is not None else [""] * len(df))
    df["Repacking"] = [m or _pack_label(size, lot) for m, size, lot in zip(mapped, df["Lot Size"], df["lot"])]
    df["Unit"] = df["lot"].map(lambda v: " ".join(str(v or "").split()))
    # what the qty means physically (for the box conversion)
    unit = [boxes.per_lot(lot, size) for lot, size in zip(df["lot"], df["Lot Size"])]
    df["_pcs"] = [q * n if u == "pcs" else 0.0 for (u, n), q in zip(unit, df["qty"])]
    df["_kg"] = [q * n if u == "kg" else 0.0 for (u, n), q in zip(unit, df["qty"])]
    df["_box"] = [q if u == "box" else 0.0 for (u, _), q in zip(unit, df["qty"])]
    df["_boxkg"] = ([masters.box_kg(r.city, r.customer, r.customer_sku_name) for r in df.itertuples()]
                    if masters is not None else None)
    return df


def _pack_label(size: str, lot: str) -> str:
    """Repacking spec from the SKU name when the mapping has none:
    '2 Pcs' + Pack -> '2 Pcs Pack', '' + Kg -> 'Kg', '17.5 Kg Box' + Box -> '17.5 Kg Box'."""
    size, lot = " ".join(str(size or "").split()), " ".join(str(lot or "").split())
    if not size:
        return lot
    if not lot or lot.casefold() in size.casefold().split():
        return size
    return f"{size} {lot}"


_SORT = lambda s: s.astype(str).str.casefold()  # noqa: E731


def _counts(spec_size: str) -> list[int]:
    """Fruit counts in a Spec-Size: '22C, 24C' -> [22, 24], '90, 110' -> [90, 110],
    '33 36' -> [33, 36]. Sizes that are not counts ('16mm', 'Blue', RSA '2,3') -> []."""
    import re
    s = str(spec_size or "")
    if re.search(r"mm|not in", s, re.IGNORECASE):
        return []
    out = [int(x) for x in re.findall(r"(?<![\d.])(\d{2,3})(?![\d.])", s)]
    return [c for c in out if c >= 10]


def _pcs_per_lot(size: str) -> float | None:
    """Pieces in one lot when the lot size is in pieces ('2 Pcs' -> 2), else None."""
    import re
    if not re.search(r"\bpcs?\b|piece", str(size or ""), re.IGNORECASE):
        return None          # '1 Pack', '200 gm', '1 Box': pieces unknown
    unit, n = boxes.per_lot("", size)
    return n if unit == "pcs" else None


def _kg_per_lot(size: str, lot: str) -> float | None:
    """Kg in one lot when the lot is a kg pack ('1 Kg' -> 1, plain Kg lot -> 1), else None."""
    s = str(size or "").casefold()
    if "box" in s or "tray" in s:
        return None
    if "kg" in s:
        return boxes.per_lot("", size)[1]
    if not s.strip() and str(lot or "").strip().casefold() == "kg":
        return 1.0
    return None


def _base_rows(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Indent rows with the production attributes from the 'New' tab
    (variety, Spec-Repacking, Spec-Size). A SKU name missing from the New tab
    gets Spec-Size 'not in New tab (name)' so it is never clubbed.
    Variety is kept only for the variety parents (Apple); other fruit has none."""
    from core import config
    df = lines.copy()
    df["qty"] = df["qty"].map(to_number)
    df = df[df["qty"] > 0].copy()
    if df.empty:
        return df
    clean = lambda v: " ".join(str(v or "").split())  # noqa: E731
    with_variety = {p.casefold() for p in config.variety_parents()}
    info = [masters.prod_info(r.city, r.customer, r.customer_sku_name) if masters is not None else None
            for r in df.itertuples()]
    df["City"] = df["city"].map(clean)
    df["Parent SKU"] = df["parent_sku"].map(clean)
    df["Variety"] = [(clean(i.get("Variety")) if i and clean(i.get("Variety")) else clean(v))
                     if p.casefold() in with_variety else ""
                     for i, v, p in zip(info, df["variety"].fillna(""), df["Parent SKU"])]
    df["Repacking"] = [clean(i.get("Repacking")) if i else "" for i in info]
    df["Spec-Size"] = [(clean(i.get("Spec-Size")) or "-") if i else f"{NOT_IN_BASE} ({clean(n)})"
                       for i, n in zip(info, df["customer_sku_name"])]
    df["Lot Size"] = [lot_size(n) or clean(lot) for n, lot in zip(df["customer_sku_name"], df["lot"])]
    df["_in_base"] = [i is not None for i in info]
    return df


def production(lines: pd.DataFrame, masters: Masters | None,
               box_rules: list | None = None) -> pd.DataFrame:
    """Production sheet (base: the 'New' tab), all customers together.
    One row per City + Parent SKU + Variety + Repacking + Spec-Size + Lot Size.
    'Total' clubs every customer for the same City + Parent SKU + Repacking +
    Spec-Size + Lot Size:
    - kg packs ('1 Kg', plain Kg) -> total kilos, e.g. '700 Kg' (no repacking units);
    - otherwise in repacking units: 10 + 20 packs of 2 pcs = '30 Punnet'.
    'Boxes @ count N' columns: for a piece lot (1 Pcs, 2 Pcs) and a Spec-Size with
    counts (22C, 24C), the boxes needed if packed at each count = pieces / count,
    rounded up (440 pcs: 22C -> 20, 24C -> 19). Blank when not computable.
    `box_rules` is accepted for older callers and ignored."""
    import math
    df = _base_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return pd.DataFrame(columns=PRODUCTION_COLUMNS)
    keys = ["City", "Parent SKU", "Variety", "Repacking", "Spec-Size", "Lot Size"]
    g = (df.assign(**{k + "_k": df[k].astype(str).str.casefold() for k in keys})
           .groupby([k + "_k" for k in keys], sort=False)
           .agg(**{k: (k, "first") for k in keys}, Qty=("qty", "sum"), _lot=("lot", "first"))
           .reset_index(drop=True))
    club = ["City", "Parent SKU", "Repacking", "Spec-Size", "Lot Size"]
    tot = g.groupby([g[k].astype(str).str.casefold() for k in club], sort=False)["Qty"].transform("sum")
    totals, box_cols = [], {}
    for i, (t, r) in enumerate(zip(tot, g.to_dict("records"))):
        kg = _kg_per_lot(r["Lot Size"], r["_lot"])
        totals.append(f"{fmt_num(t * kg)} Kg" if kg else f"{fmt_num(t)} {r['Repacking']}".strip())
        pcs = _pcs_per_lot(r["Lot Size"])
        for j, c in enumerate(_counts(r["Spec-Size"]) if pcs else [], start=1):
            box_cols.setdefault(j, [""] * len(g))[i] = f"{c}C: {math.ceil(t * pcs / c - 1e-9)}"
    g["Qty"] = _whole(g["Qty"])
    g["Total"] = totals
    extra = []
    for j in sorted(box_cols):
        g[BOX_COL.format(j)] = box_cols[j]
        extra.append(BOX_COL.format(j))
    return g.sort_values(keys, key=_SORT)[PRODUCTION_COLUMNS + extra].reset_index(drop=True)


MAKE_READY_COLUMNS = ["City", "Parent SKU", "Variety", "Repacking", "Pack", "Make ready", "Fruit needed"]
_BULK = {"tray", "box", "crate", "carton", "bulk", "loose"}   # containers that hold loose fruit


def _is_container(pack: str) -> bool:
    """The pack itself is a container: '1 Box', '17.5 Kg Box', '1 Tray'."""
    return any(w in str(pack or "").casefold().split() for w in ("box", "tray", "crate", "carton"))


def make_ready(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Make-ready list for the ground team: all customers and all sizes together.
    One row per City + Parent SKU + Variety (Apple only) + Repacking + Pack.
    - Unit packs (Punnet, Pack): Make ready = number of packs; Fruit needed =
      pieces for piece packs (2 Pc x 316 = 632 pcs), kilos for kg packs, blank
      for gram packs (the packets are the answer).
    - Bulk repacking (Tray, Box) of a piece or kg pack: the fruit goes in loose,
      so Make ready = '7 pcs loose' / '700 kg loose' (not 7 trays).
    - The pack is itself a container ('1 Box'): Make ready = '10 Box'."""
    df = _base_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return pd.DataFrame(columns=MAKE_READY_COLUMNS)
    df = df.rename(columns={"Lot Size": "Pack"})
    keys = ["City", "Parent SKU", "Variety", "Repacking", "Pack"]
    g = (df.assign(**{k + "_k": df[k].astype(str).str.casefold() for k in keys})
           .groupby([k + "_k" for k in keys], sort=False)
           .agg(**{k: (k, "first") for k in keys}, _qty=("qty", "sum"), _lot=("lot", "first"))
           .reset_index(drop=True))
    make, need = [], []
    for r in g.to_dict("records"):
        q, pack, rep = r["_qty"], r["Pack"], r["Repacking"]
        pcs, kg = _pcs_per_lot(pack), _kg_per_lot(pack, r["_lot"])
        bulk = rep.casefold() in _BULK
        if _is_container(pack):
            make.append(f"{fmt_num(q)} {pack.split()[-1]}")
            need.append("")
        elif bulk and pcs:
            make.append(f"{fmt_num(q * pcs)} pcs loose")
            need.append(f"{fmt_num(q * pcs)} pcs")
        elif bulk and kg:
            make.append(f"{fmt_num(q * kg)} kg loose")
            need.append(f"{fmt_num(q * kg)} kg")
        else:
            make.append(f"{fmt_num(q)} {rep or 'packs'}".strip())
            need.append(f"{fmt_num(q * pcs)} pcs" if pcs else f"{fmt_num(q * kg)} kg" if kg else "")
    g["Make ready"], g["Fruit needed"] = make, need
    return g.sort_values(keys, key=_SORT)[MAKE_READY_COLUMNS].reset_index(drop=True)


def not_in_base(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Customer SKU names in these indents that are missing from the New tab."""
    df = _base_rows(lines, masters) if lines is not None and not lines.empty else None
    cols = ["City", "Customer", "Parent SKU", "Customer SKU Name"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    bad = df[~df["_in_base"]]
    return (bad[["City", "customer", "Parent SKU", "customer_sku_name"]].drop_duplicates()
            .rename(columns={"customer": "Customer", "customer_sku_name": "Customer SKU Name"})
            .reset_index(drop=True))


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
                     "Repacking": masters.repacking(city, cust, name)
                     or _pack_label(lot_size(name), masters.lot_for(city, cust, name)),
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
