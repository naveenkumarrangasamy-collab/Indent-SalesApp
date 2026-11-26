"""Processed page (25 Nov, trial): MT / GT / dump out of each lot on a table.

Built for phones: one thing at a time (Fruit -> Table -> Lot -> Cux lot), empty number boxes
(no zeros to delete), boxes that do not fit the fruit are hidden, live result under the inputs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core import prod_actual as pa
from core import processed as pr
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common

CSS = """<style>
.st-key-pr_card {border:1px solid #DDE3EA; border-radius:10px; padding:12px 14px 4px 14px; background:#FBFCFD;}
.st-key-pr_card label p {font-size:0.8rem; color:#4A5562; font-weight:600;}
.pr-info {font-size:0.82rem; color:#4A5562; background:#F1F4F7; border-radius:8px; padding:6px 10px; margin:2px 0 8px 0;}
.pr-grp {font-size:0.85rem; font-weight:700; margin:6px 0 -6px 0;}
.pr-res {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; margin:6px 0 10px 0;}
.pr-res div {border-radius:8px; padding:6px 4px; text-align:center; background:#F1F4F7; font-size:0.75rem; color:#4A5562;}
.pr-res b {display:block; font-size:1.05rem; color:#1F2933;}
.pr-kg {font-size:0.78rem; color:#4A5562; margin-top:-2px;}
.pr-var {display:inline-block; background:#EDE7FB; color:#4B2A9E; font-weight:700; border-radius:999px;
         padding:1px 10px; margin:0 2px; font-size:0.85rem;}
@media (max-width: 640px) { .pr-res {grid-template-columns:repeat(2,minmax(0,1fr));} }
</style>"""


def _num(label: str, key: str, step: float = 1.0):
    return st.number_input(label, min_value=0.0, step=step, value=None, key=key, placeholder="0", format="%g")


def _pending() -> list[dict]:
    return st.session_state.setdefault("pr_rows", [])


def _eff_colour(e) -> tuple[str, str]:
    if e is None:
        return "#F1F4F7", "#1F2933"
    if e >= 0.9:
        return "#E6F4EA", "#1E7B34"
    if e >= 0.85:
        return "#FFF4D6", "#8A5A00"
    return "#FDECEC", "#B42318"


@st.dialog("Save these?", width="large")
def _confirm(rows: list[dict], user: User) -> None:
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pr_ok"):
        try:
            n = pr.save(get_backend(), rows, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pr_rows"] = []
        common.flash("success", f"{n} saved · see Production sheet → Processed.")
        st.rerun()
    if c2.button("Back", width="stretch", key="pr_back"):
        st.rerun()


def render(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Processed")
    try:
        m = masters.load_masters()
        lots = pa.read()
        lines = indents.current_rows(indents.read_lines())
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return

    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="pr_day", format="DD/MM/YYYY").isoformat()
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key="pr_city") or cities[0]

    day_lots = pd.DataFrame(pa.view(lots, day, city))  # short names, for the check below
    raw = lots.copy() if lots is not None and not lots.empty else pd.DataFrame()
    if not raw.empty and "production_date" in raw.columns:
        raw = raw[(raw["production_date"].astype(str).str[:10] == day) & (raw["city"].astype(str) == city)]
    if day_lots.empty or raw.empty:
        st.info("No lots on tables for this date yet. Add them on **Pre-Production Actual** first.")
        _preview(user)
        return

    if not st.toggle("Phone view", key="pr_phone", help="One lot at a time (cards), easier on a phone"):
        _grid(raw, lines, day, city, user)
        return
    fruits = sorted({str(x) for x in raw["parent_sku"] if str(x).strip()}, key=str.casefold)
    fruit = st.pills("Fruit", fruits, key=f"pr_fruit_{day}")
    if fruit:
        f_lots = raw[raw["parent_sku"] == fruit]
        tables = sorted({str(t) for t in f_lots["table_no"]}, key=lambda t: (len(t), t))
        table = st.pills("Table", tables, key=f"pr_table_{day}_{fruit}",
                         default=tables[0] if len(tables) == 1 else None)
        if table:
            t_lots = f_lots[f_lots["table_no"].astype(str) == table].to_dict("records")
            _card(fruit, table, t_lots, lines, day, city)
    _preview(user)
    _saved(day, city)


def _lot_label(r: dict) -> str:
    bits = [r.get("size") or "", r.get("variety") or "", f"{pr._f(r.get('boxes_moved')):g} box"]
    return " · ".join(b for b in bits if b)


def _card(fruit: str, table: str, t_lots: list[dict], lines, day: str, city: str) -> None:
    with st.container(key="pr_card"):
        if len(t_lots) > 1:
            labels = [_lot_label(r) for r in t_lots]
            i = st.selectbox("Lot on table", range(len(t_lots)), format_func=lambda k: labels[k],
                             key=f"pr_lot_{day}_{fruit}_{table}")
        else:
            i = 0
        lot = t_lots[i]
        a, pcs, b = pr._f(lot.get("box_kg")), pr._f(lot.get("pcs_per_box")), pr._f(lot.get("boxes_moved"))
        x = a / pcs if a and pcs else 0
        from html import escape
        var = str(lot.get("variety") or "").strip()
        var_html = f"<span class='pr-var'>{escape(var)}</span> · " if var else ""
        st.markdown(f"<div class='pr-info'><b>{escape(fruit)}</b> {var_html}table {escape(table)} · "
                    f"{escape(str(lot.get('size') or ''))} · {b:g} box × {a:g} kg = "
                    f"<b>{a * b:g} kg</b>{f' · {x:.3f} kg/pc' if x else ''}</div>", unsafe_allow_html=True)

        needs = pr.packs_for(lines, fruit, day, city)
        options = list(needs) or ["1PC", "2PC", "3PC", "1Kg"]
        pack = st.pills("Cux lot", options, key=f"pr_pack_{lot.get('entry_id')}",
                        default=options[0] if len(options) == 1 else None)
        if not pack:
            st.caption("Pick the customer lot made from this lot.")
            return
        _, unit = pr.pack_kg(pack, x or None)
        if unit == "PC" and not x:
            st.warning("This lot has no Pcs/box, so piece packs can't be weighed. Fix it on Pre-Production Actual.")
        k = f"pr_{lot.get('entry_id')}_{pack}"
        piece = bool(x)                     # loose pieces only when we know kg per piece

        st.markdown("<div class='pr-grp' style='color:#1E7B34'>MT ready</div>", unsafe_allow_html=True)
        c = st.columns(2)
        with c[0]:
            d1 = _num(f"Packs ({pack})", f"{k}_d1")
        with c[1]:
            d2 = _num("Loose kg", f"{k}_d2", 0.1) if unit == "Kg" else None

        vals = {"mt_packs": d1, "mt_loose_kg": d2}
        for title, pre in (("MT leftover", "left"), ("GT Ready", "gt")):
            st.markdown(f"<div class='pr-grp'>{title}</div>", unsafe_allow_html=True)
            c = st.columns(2)
            with c[0]:
                vals[f"{pre}_box"] = _num("Box", f"{k}_{pre}_box")
            with c[1]:
                vals[f"{pre}_pcs" if piece else f"{pre}_kg"] = (_num("Pcs", f"{k}_{pre}_pcs") if piece
                                                                else _num("Kg", f"{k}_{pre}_kg", 0.1))
        st.markdown("<div class='pr-grp'>Dump</div>", unsafe_allow_html=True)
        c = st.columns(2)
        with c[0]:
            vals["dump_kg"] = _num("Kg", f"{k}_g1", 0.1)
        with c[1]:
            vals["dump_pcs"] = _num("Pcs", f"{k}_g2") if piece else None

        r = pr.compute(a, pcs, b, pack, vals)
        _result(r)
        if st.button("Add to preview", icon=":material/add:", type="primary", width="stretch", key=f"{k}_add",
                     disabled=not d1 and not any(vals.values())):
            _pending().append(pr.row(lot, pack, vals, day, city))
            for kk in list(st.session_state):
                if str(kk).startswith(k + "_"):
                    st.session_state.pop(kk, None)
            st.rerun()


def _result(r: dict) -> None:
    j = r["used_kg"]
    if j <= 0:
        st.error("Leftover is more than what was taken: check the boxes.")
        return
    loss = r["lotting"]
    bg, fg = _eff_colour(r["efficiency"])
    loss_txt = f"{'Loss' if loss >= 0 else 'Gain'}<b>{abs(loss):.2f} kg</b>"
    st.markdown(
        f"<div class='pr-res'><div>{loss_txt}</div>"
        f"<div style='background:{bg};color:{fg}'>Efficiency<b style='color:{fg}'>{pr.pct(r['efficiency'])}</b></div>"
        f"<div>GT Ready<b>{pr.pct(r['non_mt'])}</b></div><div>Dump<b>{pr.pct(r['dump_pct'])}</b></div></div>"
        f"<div class='pr-kg'>Taken {r['taken_kg']:.2f} · Leftover {r['left_kg_total']:.2f} · Used {j:.2f} · "
        f"MT {r['mt_kg']:.2f} · GT Ready {r['gt_kg_total']:.2f} · Dump {r['dump_kg_total']:.2f} kg</div>",
        unsafe_allow_html=True)


def _preview(user: User) -> None:
    rows = _pending()
    if not rows:
        return
    st.markdown(f"#### Preview · {len(rows)} to save")
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c = st.columns([1, 1])
    if c[0].button("Save all", type="primary", icon=":material/save:", width="stretch", key="pr_save"):
        _confirm(rows, user)
    drop = c[1].selectbox("Remove", ["—"] + [f"#{i + 1}" for i in range(len(rows))], key="pr_drop",
                          label_visibility="collapsed")
    if drop != "—":
        rows.pop(int(drop[1:]) - 1)
        st.session_state.pop("pr_drop", None)
        st.rerun()


def _saved(day: str, city: str) -> None:
    v = pr.latest(pr.read(), day, city)
    if v.empty:
        return
    st.markdown(f"#### Saved · {len(v)}")
    st.dataframe(common.numbered(pr.view(v)), hide_index=True, width="stretch")


# ------------------------------------------------------------------ line view (sheet-like), 25 Nov
# One line per lot of the day, exact BLR_ProdTracking headers, real dropdowns / boxes, scrolls sideways.

import uuid  # noqa: E402

PICK = "Choose…"
DEFAULT_PACKS = ["1PC", "2PC", "3PC", "1Kg"]
# (field, sheet header, width px, kind): lock = from Pre-Production Actual, pack, num, out, note, btn
COLS = [
    ("n", "#", 34, "lock"), ("parent_sku", "Parent SKU Name", 110, "lock"), ("variety", "Variety", 92, "lock"),
    ("size", "Size Spec", 80, "lock"), ("table_no", "Table #", 60, "lock"),
    ("box_kg", "Purchase Lot weight in Kgs (A)", 92, "lock"), ("pcs_per_box", "# of Pcs in Purchase lot", 86, "lock"),
    ("boxes_moved", "# Qty Moved to Grading table (Vendor Lots / Boxes) (B)", 120, "lock"),
    ("stock_type", "Production prod Classification", 130, "lock"),
    ("pack", "Cux Lot", 120, "pack"),
    ("mt_packs", "MT Ready (Dispatch) (Cux Lots) (D1)", 112, "num"),
    ("mt_loose_kg", "MT Ready (Disptach) (Loose Kg) (D2)", 112, "num"),
    ("left_box", "Left over MT Ready (Vendor Lots) (E1)", 112, "num"),
    ("left_kg", "Left over MT Ready (Loose Kgs) (E2)", 112, "num"),
    ("left_pcs", "Left over MT Ready (Loose PCs) (E3)", 112, "num"),
    ("gt_box", "GT Stock (Vendor Lots / Box) (F1)", 112, "num"),
    ("gt_kg", "GT Stock (Loose Kg) (F2)", 112, "num"),
    ("gt_pcs", "GT Stock (Loose 1 PCs) (F3)", 112, "num"),
    ("dump_kg", "Dump (in Kgs) (G1)", 100, "num"),
    ("dump_pcs", "Dump (in Pcs) (G2)", 100, "num"),
    ("eff", "Category Efficiency% (K / J)", 100, "out"), ("status", "Status", 96, "out"),
    ("comment", "Operations team Comments", 200, "note"), ("add", "", 70, "btn"),
]
NUMS = [c[0] for c in COLS if c[3] == "num"]
WIDTHS = [c[2] for c in COLS]

GRID_CSS = """<style>
.st-key-pg_grid {overflow-x:auto; padding-bottom:8px; -webkit-overflow-scrolling:touch; overscroll-behavior-x:contain;}
@media (max-width: 640px) {
  .st-key-pg_grid [data-testid="stHorizontalBlock"] {flex-direction:row !important;}
  .st-key-pg_grid [data-testid="stColumn"] {flex:1 1 0 !important; width:auto !important; min-width:0 !important;}
  .st-key-pg_grid input {font-size:16px;}
}
.st-key-pg_grid [data-testid="stHorizontalBlock"] {min-width:%dpx; flex-wrap:nowrap !important; gap:6px;}
.st-key-pg_grid [data-testid="stColumn"] {min-width:0 !important;}
.st-key-pg_grid [data-testid="stElementContainer"] {margin-bottom:0;}
.st-key-pg_grid button[data-testid="stNumberInputStepUp"],
.st-key-pg_grid button[data-testid="stNumberInputStepDown"] {display:none;}
.st-key-pg_grid input {font-size:0.85rem; text-align:center; font-weight:700;}
.st-key-pg_grid [data-baseweb="select"] div {justify-content:center; text-align:center; font-weight:700;}
.st-key-pg_grid [data-baseweb="select"] > div {min-height:36px; border-color:#9AA5B1; background:#FFFFFF;}
.st-key-pg_grid [data-testid="stNumberInputContainer"], .st-key-pg_grid [data-testid="stTextInputRootElement"]
  {border:1px solid #9AA5B1; border-radius:8px; background:#FFFFFF;}
.pg-h {font-size:0.76rem; font-weight:700; color:#0C447C; line-height:1.25; background:transparent;
       padding:10px 4px; min-height:58px; display:flex; align-items:center; justify-content:center; text-align:center;}
.st-key-pg_head {background:#E6F1FB; border-bottom:3px solid #185FA5; border-radius:10px 10px 0 0;
                 min-width:%dpx; margin-bottom:6px; padding:2px 0 4px 0; overflow:visible;}
.st-key-pg_head [data-testid="stColumn"], .st-key-pg_head [data-testid="stElementContainer"],
.st-key-pg_head [data-testid="stMarkdown"], .st-key-pg_head [data-testid="stMarkdownContainer"]
  {height:auto !important; overflow:visible !important;}
.st-key-pg_head [data-testid="stMarkdownContainer"] div.pg-h {height:auto; min-height:64px;}
.pg-lk {font-size:0.84rem; font-weight:700; background:#F1F4F7; color:#1F2933; border-radius:6px; padding:8px 6px;
        white-space:normal; line-height:1.2; min-height:36px; text-align:center; display:flex;
        align-items:center; justify-content:center;}
.pg-na {font-size:0.8rem; color:#9AA5B1; background:#F6F7F9; border-radius:8px; min-height:36px;
        display:flex; align-items:center; justify-content:center;}
.pg-var {background:#EDE7FB; color:#4B2A9E; font-weight:700; border-radius:999px; padding:1px 8px;}
.pg-ef {border-radius:8px; min-height:36px; display:flex; align-items:center; justify-content:center;
        font-weight:700; font-size:0.9rem;}
.pg-st {font-size:0.8rem; font-weight:700; min-height:36px; display:flex; align-items:center; justify-content:center;}
.pg-hint {font-size:0.8rem; color:#6B7684; padding:2px 4px 4px 4px;}
.pg-band {border-radius:8px; min-height:36px; margin-top:18px; display:flex; flex-direction:column;
          justify-content:center; align-items:center; text-align:center; padding:4px 10px; font-weight:700;
          font-size:0.9rem;}
.pg-band span {font-weight:500; font-size:0.75rem;}
.pg-lab {font-size:0.72rem; font-weight:700; color:#4A5562; line-height:1.2; min-height:2.4em; display:flex;
         align-items:flex-end; justify-content:center; text-align:center; margin-bottom:3px;}
.st-key-pg_grid [data-testid="stWidgetLabel"] p {font-size:0.72rem; font-weight:700; color:#4A5562; line-height:1.2;
  text-align:center;}
.st-key-pg_grid [data-testid="stWidgetLabel"] {min-height:2.4em; align-items:flex-end; justify-content:center; width:100%%;}
.st-key-pg_grid [class$="_pack"] [data-testid="stWidgetLabel"], .st-key-pg_grid [class*="_pack "] [data-testid="stWidgetLabel"] {display:none !important;}
[class*="st-key-pgb_mt_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_mt_"] .pg-lab {color:#0C447C;}
[class*="st-key-pgb_mt_"] [data-testid="stNumberInputContainer"] {border-color:#378ADD;}
[class*="st-key-pgb_gt_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_gt_"] .pg-lab {color:#791F1F;}
[class*="st-key-pgb_gt_"] [data-testid="stNumberInputContainer"] {border-color:#E24B4A;}
[class*="st-key-pgb_dump_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_dump_"] .pg-lab {color:#3C3489;}
[class*="st-key-pgb_dump_"] [data-testid="stNumberInputContainer"] {border-color:#7F77DD;}
[class*="st-key-pg_lot_"] {border:1px solid #D5DCE4; border-radius:12px; padding:8px; margin-bottom:8px;
                           min-width:%dpx; background:#FFFFFF;}
</style>""" % (1280, 1300, 1300)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""


def _lines(raw: pd.DataFrame, day: str, city: str, key: str) -> list[dict]:
    """Session lines: saved entries first, every lot of the day at least once."""
    lots = raw.drop_duplicates("entry_id", keep="last")
    lots = lots.assign(_t=lots["table_no"].astype(str).str.zfill(3)).sort_values(["_t", "parent_sku"])
    ids = list(lots["entry_id"].astype(str))
    have = st.session_state.get(key)
    if have is not None and {ln["lot_id"] for ln in have} >= set(ids):
        return have
    done = pr.latest(pr.read(), day, city)
    by_lot: dict[str, list[dict]] = {}
    for r in done.to_dict("records") if not done.empty else []:
        by_lot.setdefault(str(r.get("lot_id")), []).append(r)
    out = []
    for lid in ids:
        old = [ln for ln in have or [] if ln["lot_id"] == lid]
        if old:
            out += old
            continue
        saved = by_lot.get(lid) or [None]
        for o in saved:
            ln = {"id": uuid.uuid4().hex[:8], "lot_id": lid, "saved": None}
            if o is not None:
                ln["saved"] = {"pack": o.get("cux_lot", ""), "comment": str(o.get("comment") or ""),
                               **{f: (None if _blank(o.get(f)) else pr._f(o.get(f))) for f in NUMS}}
                st.session_state.setdefault(f"pg_{ln['id']}_pack", ln["saved"]["pack"] or PICK)
                st.session_state.setdefault(f"pg_{ln['id']}_comment", ln["saved"]["comment"])
                for f in NUMS:
                    st.session_state.setdefault(f"pg_{ln['id']}_{f}", ln["saved"][f])
            out.append(ln)
    st.session_state[key] = out
    return out


def _applies(field: str, unit: str, piece: bool) -> bool:
    """Which boxes a line needs for its pack (unit 'PC' / 'Kg')."""
    if not unit:
        return False
    if field in ("mt_packs", "left_box", "gt_box", "dump_kg"):
        return True
    if field in ("mt_loose_kg", "left_kg", "gt_kg"):
        return unit == "Kg" or not piece
    if field in ("left_pcs", "gt_pcs", "dump_pcs"):
        return unit == "PC" and piece
    return False


def _state(ln: dict, lot: dict) -> dict:
    """Current values of a line from its widgets + what it needs."""
    g = st.session_state.get
    pack = g(f"pg_{ln['id']}_pack") or PICK
    pack = "" if pack == PICK else pack
    a, pcs = pr._f(lot.get("box_kg")), pr._f(lot.get("pcs_per_box"))
    x = a / pcs if a and pcs else 0
    _, unit = pr.pack_kg(pack, x or None)
    piece = bool(x)
    need = [f for f in NUMS if _applies(f, unit, piece)]
    vals = {f: g(f"pg_{ln['id']}_{f}") for f in NUMS}
    vals = {f: (vals[f] if f in need else None) for f in NUMS}
    comment = str(g(f"pg_{ln['id']}_comment") or "").strip()
    touched = bool(pack) or any(v is not None for v in vals.values()) or bool(comment)
    missing = ([] if pack else ["Cux Lot"]) + [f for f in need if vals[f] is None]
    if pack and unit == "PC" and not piece:
        missing.append("# of Pcs in Purchase lot (fix on Pre-Production Actual)")
    cur = {"pack": pack, "comment": comment, **{f: vals[f] for f in NUMS}}
    saved = ln.get("saved")
    same = saved is not None and all((saved.get(k) or None) == (cur.get(k) or None) for k in cur)
    return {"pack": pack, "unit": unit, "need": need, "vals": vals, "comment": comment, "touched": touched,
            "missing": missing, "same": same}


def _eff_cell(s: dict, lot: dict) -> tuple[str, str, str]:
    if not s["pack"] or s["vals"].get("mt_packs") is None:
        return "–", "#F6F7F9", "#9AA5B1"
    c = pr.compute(lot.get("box_kg"), lot.get("pcs_per_box"), lot.get("boxes_moved"), s["pack"], s["vals"])
    if c["used_kg"] <= 0:
        return "check", "#FDECEC", "#B42318"
    bg, fg = _eff_colour(c["efficiency"])
    return pr.pct(c["efficiency"]), bg, fg


HEAD = ["n", "parent_sku", "variety", "size", "table_no", "box_kg", "pcs_per_box", "boxes_moved", "stock_type",
        "pack"]
ROW_W = [124] + [122] * 9
BANDS = [  # (kg key, name shown in the coloured box, fields, (fill, text)): MT blue, GT red, Dump violet
    ("MT", "MT Ready", ["mt_packs", "mt_loose_kg", "left_box", "left_kg", "left_pcs", "eff", "status"],
     ("#B5D4F4", "#042C53")),
    ("GT", "GT Stock", ["gt_box", "gt_kg", "gt_pcs"], ("#F7C1C1", "#501313")),
    ("Dump", "Dump", ["dump_kg", "dump_pcs", "comment", "add"], ("#CECBF6", "#26215C")),
]


def _band_kg(s: dict, lot: dict) -> dict:
    c = pr.compute(lot.get("box_kg"), lot.get("pcs_per_box"), lot.get("boxes_moved"), s["pack"], s["vals"])
    return {"MT": f"{c['mt_kg']:.1f} kg", "GT": f"{c['gt_kg_total']:.1f} kg", "Dump": f"{c['dump_kg_total']:.1f} kg"}


def _band_cell(f: str, ln: dict, s: dict, lot: dict, title: dict, i: int, rows: list) -> None:
    k = f"pg_{ln['id']}_{f}"
    lab = title.get(f, "")
    if f in NUMS:
        if f in s["need"]:
            st.number_input(lab, min_value=0.0, step=1.0, value=None, key=k, format="%g", placeholder="")
        else:
            st.markdown(f"<div class='pg-lab'>{lab}</div><div class='pg-na'>–</div>", unsafe_allow_html=True)
    elif f == "eff":
        txt, bg, fg = _eff_cell(s, lot)
        st.markdown(f"<div class='pg-lab'>{lab}</div><div class='pg-ef' style='background:{bg};color:{fg}'>{txt}"
                    "</div>", unsafe_allow_html=True)
    elif f == "status":
        stt, colr = (("Saved", "#1E7B34") if s["same"] else ("Not saved", "#8A5A00") if s["touched"]
                     else ("Not entered", "#9AA5B1"))
        st.markdown(f"<div class='pg-lab'>Status</div><div class='pg-st' style='color:{colr}'>{stt}</div>",
                    unsafe_allow_html=True)
    elif f == "comment":
        st.text_input(lab, key=k, placeholder="Type a note")
    elif f == "add":
        st.markdown("<div class='pg-lab'>&nbsp;</div>", unsafe_allow_html=True)
        if st.button("＋ pack", key=f"pg_{ln['id']}_add", help="Another pack from this lot", width="stretch"):
            rows.insert(i + 1, {"id": uuid.uuid4().hex[:8], "lot_id": ln["lot_id"], "saved": None})
            st.rerun(scope="fragment")


def _grid(raw: pd.DataFrame, lines, day: str, city: str, user: User) -> None:
    st.markdown(GRID_CSS, unsafe_allow_html=True)
    key = f"pg_lines_{day}_{city}"
    lots = {str(r["entry_id"]): r for r in raw.to_dict("records")}
    rows = _lines(raw, day, city, key)
    packs = []
    for fruit in {str(lots[ln["lot_id"]].get("parent_sku")) for ln in rows if ln["lot_id"] in lots}:
        packs += [p for p in pr.packs_for(lines, fruit, day, city) if p not in packs]
    packs += [p for p in DEFAULT_PACKS if p not in packs]
    _grid_body(rows, lots, packs, day, city, user, key)


@st.fragment
def _grid_body(rows, lots, packs, day, city, user, key) -> None:
    bad = st.session_state.get("pg_bad", set())
    if bad:
        st.markdown("<style>" + "".join(
            f".st-key-{k} [data-baseweb], .st-key-{k} [data-testid=\"stNumberInputContainer\"]"
            f"{{border:2px solid #D92D20 !important; background:#FFF5F5 !important;}}" for k in bad) + "</style>",
            unsafe_allow_html=True)
    states = {ln["id"]: _state(ln, lots[ln["lot_id"]]) for ln in rows if ln["lot_id"] in lots}
    done = sum(1 for s in states.values() if s["same"])
    st.caption(f"{len(rows)} line(s) · {done} saved · grey comes from Pre-Production Actual · fill the white "
               "boxes · scroll sideways for more columns →")
    title = {c[0]: c[1] for c in COLS}
    with st.container(key="pg_grid"):
        with st.container(key="pg_head"):
            head = st.columns(ROW_W)
            for col, f in zip(head, HEAD):
                col.markdown(f"<div class='pg-h'>{title[f]}</div>", unsafe_allow_html=True)
        for i, ln in enumerate(rows):
            lot = lots.get(ln["lot_id"])
            if lot is None:
                continue
            s = states[ln["id"]]
            with st.container(key=f"pg_lot_{ln['id']}"):
                cells = st.columns(ROW_W)
                for col, f in zip(cells, HEAD):
                    with col:
                        if f == "pack":
                            k = f"pg_{ln['id']}_pack"
                            if st.session_state.get(k) not in [PICK] + packs:
                                st.session_state[k] = PICK
                            st.selectbox("Cux Lot", [PICK] + packs, key=k, label_visibility="collapsed")
                            continue
                        v = i + 1 if f == "n" else lot.get(f, "")
                        if f in ("box_kg", "pcs_per_box", "boxes_moved"):
                            v = f"{pr._f(v):g}" if pr._f(v) else ""
                        if f == "variety" and v:
                            v = f"<span class='pg-var'>{v}</span>"
                        st.markdown(f"<div class='pg-lk'>{v or '&nbsp;'}</div>", unsafe_allow_html=True)
                if not s["pack"]:
                    st.markdown("<div class='pg-hint'>Pick the Cux Lot to open MT, GT and Dump.</div>",
                                unsafe_allow_html=True)
                    continue
                kg = _band_kg(s, lot)
                for band, name, fields, colr in BANDS:
                    with st.container(key=f"pgb_{band.lower()}_{ln['id']}"):
                        cells = st.columns(ROW_W)
                        bg, fg = colr
                        cells[0].markdown(f"<div class='pg-band' style='background:{bg};color:{fg}'>{name}"
                                          f"<span>{kg.get(band, '')}</span></div>", unsafe_allow_html=True)
                        for col, f in zip(cells[1:], fields):
                            with col:
                                _band_cell(f, ln, s, lot, title, i, rows)

    todo = [(ln, states[ln["id"]]) for ln in rows if ln["id"] in states
            and states[ln["id"]]["touched"] and not states[ln["id"]]["same"]]
    if st.button(f"Save {len(todo)} line(s)" if todo else "Save", type="primary", icon=":material/save:",
                 key="pg_save", disabled=not todo):
        miss, keys = [], set()
        for ln, s in todo:
            n = rows.index(ln) + 1
            if s["missing"]:
                names = [dict((c[0], c[1]) for c in COLS).get(m, m) for m in s["missing"]]
                miss.append(f"**Line {n}** ({lots[ln['lot_id']].get('parent_sku')}): " + ", ".join(names))
                keys |= {f"pg_{ln['id']}_{'pack' if m == 'Cux Lot' else m}" for m in s["missing"]}
        if miss:
            st.session_state["pg_bad"] = keys
            st.session_state["pg_miss"] = miss
            st.rerun(scope="fragment")
        st.session_state.pop("pg_bad", None)
        st.session_state.pop("pg_miss", None)
        out = [pr.row(lots[ln["lot_id"]], s["pack"], s["vals"], day, city, s["comment"]) for ln, s in todo]
        _grid_confirm(out, todo, user)
    for m in st.session_state.get("pg_miss", []):
        st.error("Fill before saving · " + m, icon=":material/error:")


@st.dialog("Save these lines?", width="large")
def _grid_confirm(rows: list[dict], todo: list, user: User) -> None:
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pg_ok"):
        try:
            n = pr.save(get_backend(), rows, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        for ln, s in todo:
            ln["saved"] = {"pack": s["pack"], "comment": s["comment"], **s["vals"]}
        common.flash("success", f"{n} line(s) saved · see Production Tracking.")
        st.rerun()
    if c2.button("Back", width="stretch", key="pg_back"):
        st.rerun()
