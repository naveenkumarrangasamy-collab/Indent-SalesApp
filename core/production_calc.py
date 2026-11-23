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
PENDING = "mapping not done"       # in the New tab, but Spec-Repacking / Spec-Size still empty
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
    return df


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
    pending = [bool(i) and not clean(i.get("Spec-Size")) and not clean(i.get("Repacking")) for i in info]
    df["Spec-Size"] = [f"{PENDING} ({clean(n)})" if p else
                       (clean(i.get("Spec-Size")) or "-") if i else f"{NOT_IN_BASE} ({clean(n)})"
                       for i, n, p in zip(info, df["customer_sku_name"], pending)]
    df["Lot Size"] = [lot_size(n) or clean(lot) for n, lot in zip(df["customer_sku_name"], df["lot"])]
    df["_in_base"] = [i is not None and not p for i, p in zip(info, pending)]
    return df


def production(lines: pd.DataFrame, masters: Masters | None) -> pd.DataFrame:
    """Production sheet (base: the 'New' tab), all customers together.
    One row per City + Parent SKU + Variety + Repacking + Spec-Size + Lot Size.
    'Total' clubs every customer for the same City + Parent SKU + Repacking +
    Spec-Size + Lot Size:
    - kg packs ('1 Kg', plain Kg) -> total kilos, e.g. '700 Kg' (no repacking units);
    - otherwise in repacking units: 10 + 20 packs of 2 pcs = '30 Punnet'.
    'Boxes @ count N' columns: for a piece lot (1 Pcs, 2 Pcs) and a Spec-Size with
    counts (22C, 24C), the boxes needed if packed at each count = pieces / count,
    rounded up (440 pcs: 22C -> 20, 24C -> 19). Blank when not computable."""
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
    g = g.sort_values(keys, key=_SORT)
    g["Spec-Size"] = g["Spec-Size"].map(lambda v: _count_label(str(v)))   # 90, 110 -> 90C, 110C
    return g[PRODUCTION_COLUMNS + extra].reset_index(drop=True)


MAKE_READY_COLUMNS = ["City", "Parent SKU", "Variety", "Repacking", "Pack", "Make ready", "Fruit needed",
                      "Spec Size"]
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
    from core import config
    df = df.rename(columns={"Lot Size": "Pack"})
    punnet = config.punnets_per_tray()
    is_p = df["Parent SKU"].astype(str).str.casefold().isin(punnet)
    df.loc[is_p, "Pack"] = "Punnet"            # blueberry: always punnets, whatever the gram size
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
    g["Spec Size"] = [" | ".join(c) for c in _by_size(df, keys, g)]
    return g.sort_values(keys, key=_SORT)[MAKE_READY_COLUMNS].reset_index(drop=True)


def _count_label(spec: str) -> str:
    """Mark counts with C so they are not read as pieces: '90, 110' -> '90C, 110C'."""
    import re
    if not _counts(spec):
        return spec
    return re.sub(r"(?<![\d.])(\d{2,3})(?![\d.])(?!\s*[Cc])", lambda m: m.group(1) + "C"
                  if int(m.group(1)) >= 10 else m.group(1), spec)


def _by_size(df: pd.DataFrame, keys: list[str], g: pd.DataFrame) -> list[list[str]]:
    """Per make-ready row, the parts of its 'Spec Size' cell (joined with ' | '),
    from the New tab Spec-Size. A count is fruit per box / tray:
    - piece packs: boxes at each count, rounded up: 900 pcs at '90C, 100C' ->
      '90C: 10 Box | 100C: 9 Box' (Avocado / Blueberry: 'Tray');
    - punnet parents (Blueberry, 12 punnets a tray): '16mm: 10 Tray' for 119 punnets;
    - kg packs: '18C: 70 kg'; otherwise just the spec ('180C, 198C' for gram packs).
    SKUs in one row with different specs each get their own part."""
    fold = lambda r: tuple(str(r[k]).casefold() for k in keys)  # noqa: E731
    parts: dict[tuple, dict[str, float]] = {}
    for r in df.to_dict("records"):
        spec = str(r.get("Spec-Size") or "").strip()
        if not spec or spec == "-" or spec.startswith(NOT_IN_BASE) or spec.startswith(PENDING):
            continue
        d = parts.setdefault(fold(r), {})
        d[spec] = d.get(spec, 0.0) + to_number(r["qty"])
    return [_spec_cells(r["Parent SKU"], r["Pack"], r["_lot"], parts.get(fold(r), {}))
            for r in g.to_dict("records")]


def _spec_cells(parent: str, pack: str, lot: str, specs: dict[str, float]) -> list[str]:
    """The 'Spec Size' parts for one row: {spec: qty} -> ['90C: 10 Box', ...]."""
    import math
    from core import config
    trays = {p.casefold() for p in config.tray_parents()}
    punnet = config.punnets_per_tray()
    parent = str(parent).casefold()
    unit = "Tray" if parent in trays else "Box"
    pcs, kg = _pcs_per_lot(pack), _kg_per_lot(pack, lot)
    if _is_container(pack):
        pcs = kg = None
    cells = []
    for spec, q in sorted(specs.items(), key=lambda kv: (_counts(kv[0]) or [999])[0]):
        counts = _counts(spec)
        if parent in punnet:
            cells.append(f"{_count_label(spec)}: {math.ceil(q / punnet[parent] - 1e-9)} Tray")
        elif pcs and counts:
            n = q * pcs
            cells += [f"{c}C: {math.ceil(n / c - 1e-9)} {unit}" for c in counts]
        elif kg:
            cells.append(f"{_count_label(spec)}: {fmt_num(q * kg)} kg")
        else:
            cells.append(_count_label(spec))
    return cells


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
    (city > customer > store). Temporary (16 Nov): when the New tab exists,
    Variety (Apple only), Spec (= New tab Spec-Size) and Lot Size come from it,
    the same as the production sheet, so the two match; SKU names missing from
    New show 'not in New tab (name)'. Without a New tab: Mapping Whole as before."""
    if lines is None or lines.empty:
        return pd.DataFrame(columns=BATCH_COLUMNS)
    if masters is not None and masters.has_prod_base:
        df = _base_rows(lines, masters)
        if df.empty:
            return pd.DataFrame(columns=BATCH_COLUMNS)
        df["Customer SKU Name"] = df["customer_sku_name"].map(lambda v: " ".join(str(v).split()))
        df["Lot"] = df["lot"]
        df["Spec"] = df["Spec-Size"]
    else:
        df = _spec_rows(lines, masters)
        if df.empty:
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


BY_CUSTOMER_COLUMNS = ["Parent SKU", "Customer SKU Name", "Variety", "Repacking", "Spec-Size"]
AT_SPEC = "At spec"


def customer_group(customer: str, store: str) -> str:
    """By-customer section: the customer's stores are clubbed (Swiggy WH1 + WH2 =
    'Swiggy'); cold-room stores form their own section ('Swiggy Cold Room')."""
    cust = " ".join(str(customer or "").split())
    if "coldroom" in "".join(str(store or "").casefold().split()):
        return f"{cust} Cold Room"
    return cust


def _store_label(customer: str, store: str) -> str:
    """Column name for a store: 'Swiggy WH1' -> 'WH1', 'Zepto - Nelamangala' -> 'Nelamangala'."""
    import re
    s = " ".join(str(store or "").split())
    c = " ".join(str(customer or "").split())
    short = re.sub(rf"^{re.escape(c)}\s*[-_:·]?\s*", "", s, flags=re.IGNORECASE).strip(" -_") if c else s
    return short or s or "Store"


def numbered(df: pd.DataFrame) -> pd.DataFrame:
    """21 Nov: an item number (#) as the first column: 1, 2, 3 ... ('Total' rows get none)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "#" in df.columns:
        return df
    out = df.reset_index(drop=True).copy()
    lead = out.iloc[:, : min(3, out.shape[1])].astype(str).apply(lambda r: r.str.strip().str.lower())
    total = lead.eq("total").any(axis=1)
    n, nums = 0, []
    for t in total:
        if t:
            nums.append("")
        else:
            n += 1
            nums.append(str(n))
    out.insert(0, "#", nums)
    return out


def make_ready_by_customer(lines: pd.DataFrame, masters: Masters | None) -> list[tuple[str, str, pd.DataFrame]]:
    """Production by customer: one section per customer (all its stores clubbed,
    cold rooms apart) and city. One row per exact Customer SKU Name (only case
    and spaces ignored), so different SKUs are never clubbed; each row shows its
    own New-tab Repacking + Spec-Size, a qty column per store, Total and 'At spec'
    (boxes / trays / kg at that line's spec). Ends with a Total row."""
    out = []
    df = _base_rows(lines, masters) if lines is not None and not lines.empty else None
    if df is None or df.empty:
        return out
    from core import config
    clean = lambda v: " ".join(str(v or "").split())  # noqa: E731
    punnet = config.punnets_per_tray()
    df["_group"] = [customer_group(c, s) for c, s in zip(df["customer"], df["store"])]
    df["_store"] = [_store_label(c, s) for c, s in zip(df["customer"], df["store"])]
    df["Customer SKU Name"] = df["customer_sku_name"].map(clean)
    df["_pack"] = ["Punnet" if str(p).casefold() in punnet else ls for p, ls in zip(df["Parent SKU"], df["Lot Size"])]
    for (grp, city), part in sorted(df.groupby(["_group", "City"]),
                                    key=lambda kv: (kv[0][0].casefold(), kv[0][1].casefold())):
        stores = sorted(part["_store"].unique(), key=str.casefold)
        keys = ["Parent SKU", "Customer SKU Name", "Variety"]
        part = part.assign(_k=[tuple(str(r[k]).casefold() for k in keys) for r in part.to_dict("records")])
        rows = []
        for _, g in part.groupby("_k", sort=False):
            r0 = g.iloc[0]
            spec = str(r0["Spec-Size"])
            if spec.startswith(NOT_IN_BASE):
                shown, rep, specs = NOT_IN_BASE, "", {}
            elif spec.startswith(PENDING):
                shown, rep, specs = "to fill", "to fill", {}
            else:
                shown = _count_label(spec) if spec != "-" else ""
                rep = r0["Repacking"]
                specs = {spec: float(g["qty"].sum())} if spec != "-" else {}
            row = {"Parent SKU": r0["Parent SKU"], "Customer SKU Name": r0["Customer SKU Name"],
                   "Variety": r0["Variety"], "Repacking": rep, "Spec-Size": shown}
            for s in stores:
                q = float(g.loc[g["_store"] == s, "qty"].sum())
                row[s] = fmt_num(q) if q else "–"
            row["Total"] = fmt_num(float(g["qty"].sum()))
            row[AT_SPEC] = " | ".join(_spec_cells(r0["Parent SKU"], r0["_pack"], r0["lot"], specs))
            rows.append(row)
        cols = BY_CUSTOMER_COLUMNS + stores + ["Total", AT_SPEC]
        t = pd.DataFrame(rows, columns=cols)
        t = t.sort_values(["Parent SKU", "Customer SKU Name"], key=_SORT).reset_index(drop=True)
        total = {c: "" for c in cols}
        total["Parent SKU"] = "Total"
        for s in stores:
            total[s] = fmt_num(float(part.loc[part["_store"] == s, "qty"].sum()))
        total["Total"] = fmt_num(float(part["qty"].sum()))
        t = pd.concat([t, pd.DataFrame([total])], ignore_index=True)
        if not any(str(v).strip() for v in t["Variety"]):
            t = t.drop(columns=["Variety"])
        ids = ", ".join(sorted(set(part["indent_id"].astype(str))))
        days = ", ".join(sorted(set(part["delivery_date"].astype(str))))
        head = grp + (" · " + " + ".join(stores) if len(stores) > 1 else "")
        out.append((head, f"{city} · Delivery {days} · {ids}", t))
    return out


def next_day_mask(lines: pd.DataFrame) -> pd.Series:
    """Rows of the D+1 customers (config.next_day_customers: Zepto in Bangalore)."""
    from core import config
    rules = {k.casefold(): [c.casefold() for c in v] for k, v in config.next_day_customers().items()}
    if lines is None or lines.empty or not rules:
        return pd.Series(False, index=getattr(lines, "index", None), dtype=bool)
    def hit(cust, city):
        words = rules.get(str(cust).strip().casefold())
        return words is not None and (not words or any(w in str(city).casefold() for w in words))
    return pd.Series([hit(c, t) for c, t in zip(lines["customer"], lines["city"])], index=lines.index, dtype=bool)


# ------------------------------------------------------------------ batching: indent vs PO (24 Nov)

SHEET_COLUMNS = ["Delivery date", "City", "Customer", "Delivery point", "Parent SKU", "Customer SKU Name", "Variety",
                 "Lot", "Lot Size", "Spec", "Indent qty", "PO qty", "PO − indent", "Updated at"]


def with_po(bat: pd.DataFrame, po_qty: dict, po_indents: set) -> pd.DataFrame:
    """Batching table -> 'Qty' becomes 'Indent qty', a 'PO qty' column next to it, no 'Indent' column.
    po_qty {(indent_id, sku key): qty}; po_indents = indents that have a PO with qty per item.
    PO qty is blank while none of the row's indents has a PO; an item missing from the PO counts 0."""
    out = bat.copy()
    vals = []
    for ids, name in zip(out.get("Indent", pd.Series(dtype=str)), out["Customer SKU Name"]):
        ids = [i.strip() for i in str(ids or "").split(",") if i.strip()]
        key = " ".join(str(name).split()).casefold()
        have = [i for i in ids if i in po_indents]
        vals.append(sum(float(po_qty.get((i, key), 0.0)) for i in have) if have else None)
    out = out.rename(columns={"Qty": "Indent qty"})
    pos = list(out.columns).index("Indent qty") + 1
    out.insert(pos, "PO qty", pd.array([None if v is None else int(v) if float(v).is_integer() else v
                                        for v in vals], dtype=object))
    return out.drop(columns=[c for c in ("Indent",) if c in out.columns])


def sheet_rows(view: pd.DataFrame, delivery_date: str, stamp: str) -> list[list]:
    """Rows for the Batching_Sheet tab: one per delivery point + SKU, with the date and PO − indent."""
    rows = []
    for r in view.to_dict("records"):
        ind, po = r.get("Indent qty"), r.get("PO qty")
        diff = "" if po is None or pd.isna(po) else float(po) - float(ind or 0)
        rows.append([delivery_date, r["City"], r["Customer"], r["Delivery point"], r["Parent SKU"],
                     r["Customer SKU Name"], r.get("Variety", ""), r["Lot"], r["Lot Size"], r["Spec"], ind,
                     "" if po is None or pd.isna(po) else po,
                     "" if diff == "" else (int(diff) if float(diff).is_integer() else diff), stamp])
    return rows


def merge_sheet(existing: list[list], new_rows: list[list], delivery_date: str, cities: set[str]) -> list[list]:
    """Batching_Sheet keeps every day: this date's rows for these cities are replaced, the rest kept.
    An old-format tab (title rows, no header) is started fresh."""
    keep = []
    if existing and [str(x).strip() for x in existing[0][:len(SHEET_COLUMNS)]] == SHEET_COLUMNS:
        cset = {c.casefold() for c in cities}
        for r in existing[1:]:
            if not any(str(x).strip() for x in r):
                continue
            r = list(r) + [""] * (len(SHEET_COLUMNS) - len(r))
            if str(r[0]).strip() == delivery_date and str(r[1]).strip().casefold() in cset:
                continue
            keep.append(r[:len(SHEET_COLUMNS)])
    rows = keep + new_rows
    rows.sort(key=lambda r: (str(r[0]), str(r[1]).casefold(), str(r[2]).casefold(), str(r[3]).casefold(),
                             str(r[4]).casefold(), str(r[5]).casefold()), reverse=False)
    rows.sort(key=lambda r: str(r[0]), reverse=True)          # newest date first
    return [SHEET_COLUMNS] + rows
