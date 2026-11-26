"""Production tracking (25 Nov, trial): Pre-Production Actual + Processed in ONE table laid out like the
team's BLR_ProdTracking sheet (same headers, same order). One row per lot x customer lot; a lot on a
table that is not processed yet keeps one row with the second half blank.

Written by the app to the tab TRACKING_TAB (values, not formulas) after every save, and shown on
Production sheet -> Tracking. The team's own sheet is never touched."""
from __future__ import annotations

import pandas as pd

from core import prod_actual as pa
from core import processed as pr

TRACKING_TAB = "Production_Tracking"

HEADERS = [
    "Production Date", "Delivery Date", "Parent SKU Name", "Origin", "Variety", "Brand", "Size Spec",
    "Purchase Lot weight in Kgs (A)", "# of Pcs in Purchase lot", "Table #",
    "# Qty Moved to Grading table (Vendor Lots / Boxes) (B)", "Production prod Classification",
    "Cux Lot", "Cux Lot Unit", "Conversion factor if PC Lot (X)", "Conversion factor if Kg lot",
    "Cux Lot Weight in Kgs (C)", "MT Ready (Dispatch) (Cux Lots) (D1)", "MT Ready (Dispatch) (Loose Kg) (D2)",
    "Left over MT Ready (Vendor Lots) (E1)", "Left over MT Ready (Loose Kgs) (E2)",
    "Left over MT Ready (Loose PCs) (E3)", "GT Ready (Vendor Lots / Box) (F1)", "GT Ready (Loose Kg) (F2)",
    "GT Ready (Loose 1 PCs) (F3)", "Dump (in Kgs) (G1)", "Dump (in Pcs) (G2)",
    "NW of Product taken to tables in Kgs (H = A x B)", "MT Ready Leftover (in Kgs) (I = E1*A + E2 + E3*X)",
    "Actual NW used for Production Kgs (J = H - I)", "MT Ready in Kgs (K = D1*C + D2)",
    "GT Ready in Kgs (L = F1*A + F2 + F3*X)", "Dump in Kgs (M = G1 + G2*X)",
    "Lotting gain vs loss (+ loss, - gain)", "Category Efficiency % (K / J)", "Non MT Stock % (L / J)",
    "Dump % (M / J)", "Sum 0 Check", "Operations team Comments",
]
EFF_COL = HEADERS.index("Category Efficiency % (K / J)")

SHORT = {"Production Date": "Date", "Parent SKU Name": "Fruit", "Size Spec": "Size",
         "Purchase Lot weight in Kgs (A)": "Box kg (A)", "# of Pcs in Purchase lot": "Pcs/box",
         "Table #": "Table", "# Qty Moved to Grading table (Vendor Lots / Boxes) (B)": "Boxes (B)",
         "Production prod Classification": "Stock", "Cux Lot Weight in Kgs (C)": "Pack kg (C)",
         "Conversion factor if PC Lot (X)": "X"}


def _r(v, n=2):
    return "" if v in ("", None) else round(float(v), n)


def _pct(v):
    return "" if v in ("", None) else f"{round(float(v) * 100)}%"


def _num_or_blank(v):
    n = pr._f(v)
    return n if n else ""


def build(lots: pd.DataFrame, done: pd.DataFrame) -> list[list]:
    """Rows (without header), newest date first, then table, fruit."""
    if lots is None or lots.empty or "entry_id" not in lots.columns:
        return []
    proc = pr.latest(done) if done is not None and not done.empty else pd.DataFrame()
    by_lot: dict[str, list[dict]] = {}
    for r in proc.to_dict("records") if not proc.empty else []:
        by_lot.setdefault(str(r.get("lot_id")), []).append(r)
    rows = []
    all_lots = lots.drop_duplicates("entry_id", keep="last").to_dict("records")
    by_id = {str(r.get("entry_id")): r for r in all_lots}
    grp = {m: gid for gid in by_lot if "+" in gid for m in gid.split("+")}   # 26 Nov: clubbed lots
    for lot in all_lots:
        day = str(lot.get("production_date") or "")[:10]
        a, pcs, b = pr._f(lot.get("box_kg")), pr._f(lot.get("pcs_per_box")), pr._f(lot.get("boxes_moved"))
        eid = str(lot.get("entry_id"))
        gid = grp.get(eid)
        if gid:
            members = [by_id[m] for m in gid.split("+") if m in by_id]
            if eid != gid.split("+")[0]:
                lead = by_id.get(gid.split("+")[0], {})
                first = [day, day, lot.get("parent_sku", ""), lot.get("origin", ""), lot.get("variety", ""),
                         lot.get("brand", ""), lot.get("size", ""), _r(a, 3), pcs or "", lot.get("table_no", ""),
                         _r(b, 2), lot.get("stock_type", "")]
                rows.append(first + [""] * (len(HEADERS) - len(first) - 1)
                            + [f"clubbed with table {lead.get('table_no', '')}"])
                continue
            kg = sum(pr._f(m.get("box_kg")) * pr._f(m.get("boxes_moved")) for m in members)
            b = sum(pr._f(m.get("boxes_moved")) for m in members)
            a = kg / b if b else a
        x = a / pcs if a and pcs else ""
        first = [day, day, lot.get("parent_sku", ""), lot.get("origin", ""), lot.get("variety", ""),
                 lot.get("brand", ""), lot.get("size", ""), _r(a, 3), pcs or "", lot.get("table_no", ""), _r(b, 2),
                 lot.get("stock_type", "")]
        outs = by_lot.get(gid or eid, [])
        if not outs:
            rows.append(first + [""] * (len(HEADERS) - len(first)))
            continue
        for o in outs:
            pack = o.get("cux_lot", "")
            _, unit = pr.pack_kg(pack, x or None)
            c = pr.compute(a, pcs, b, pack, o)
            j = c["used_kg"]
            parts = [c["efficiency"], c["non_mt"], c["dump_pct"]]
            rows.append(first + [
                pack, unit, _r(x, 3) if x else "", 1, _r(c["pack_kg"], 3),
                _num_or_blank(o.get("mt_packs")), _num_or_blank(o.get("mt_loose_kg")),
                _num_or_blank(o.get("left_box")), _num_or_blank(o.get("left_kg")), _num_or_blank(o.get("left_pcs")),
                _num_or_blank(o.get("gt_box")), _num_or_blank(o.get("gt_kg")), _num_or_blank(o.get("gt_pcs")),
                _num_or_blank(o.get("dump_kg")), _num_or_blank(o.get("dump_pcs")),
                _r(c["taken_kg"]), _r(c["left_kg_total"]), _r(j), _r(c["mt_kg"]), _r(c["gt_kg_total"]),
                _r(c["dump_kg_total"]), _r(c["lotting"]),
                _pct(c["efficiency"]), _pct(c["non_mt"]), _pct(c["dump_pct"]),
                _pct(sum(p for p in parts if p is not None)) if j > 0 else "", str(o.get("comment") or "")])
    rows.sort(key=lambda r: (r[0], str(r[9]).zfill(3), str(r[2])), reverse=False)
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def frame(rows: list[list], day: str | None = None, city_rows: set | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=HEADERS)
    if day:
        df = df[df["Production Date"] == day]
    return df.reset_index(drop=True)


def eff_rgb(text) -> tuple[float, float, float] | None:
    try:
        n = float(str(text).rstrip("%")) / 100
    except ValueError:
        return None
    if n >= 0.9:
        return (0.85, 0.94, 0.85)
    if n >= 0.85:
        return (1.0, 0.93, 0.75)
    return (0.98, 0.84, 0.84)


def publish(backend=None) -> int:
    """Rewrite the tracking tab from the two saved tabs. Never raises; returns rows written (-1 on error)."""
    try:
        from core import indents
        b = backend or indents.get_backend()
        lots = pa.read(b)
        rows = build(lots, pr.read(b))
        b.replace_tab(TRACKING_TAB, [HEADERS] + rows)
        groups: dict = {}
        for i, r in enumerate(rows, start=2):
            rgb = eff_rgb(r[EFF_COL])
            if rgb:
                groups.setdefault(rgb, []).append(i)
        b.color_cells(TRACKING_TAB, len(HEADERS), EFF_COL, groups, len(rows) + 1)
        return len(rows)
    except Exception:  # noqa: BLE001 - the saves themselves already succeeded
        return -1
