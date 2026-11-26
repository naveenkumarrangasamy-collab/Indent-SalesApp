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
/* 26 Nov: grading-sheet look (user's design): blue header, lot row, Cux Lot bar, MT / GT / Dump cards */
.st-key-pg_grid input {text-align:center; font-weight:700;}
.st-key-pg_grid button[data-testid="stNumberInputStepUp"],
.st-key-pg_grid button[data-testid="stNumberInputStepDown"] {display:none;}
.st-key-pg_grid [data-testid="stNumberInputContainer"], .st-key-pg_grid [data-testid="stTextInputRootElement"]
  {border:2px solid #CBD5E1; border-radius:12px; background:#FFFFFF; min-height:42px;}
.st-key-pg_grid [data-testid="stWidgetLabel"] p {font-size:0.72rem; font-weight:700; line-height:1.2;}
.st-key-pg_grid [data-testid="stElementContainer"] {margin-bottom:0;}
[class*="st-key-pgw_"], .st-key-pg_headw {overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch;
  padding-bottom:4px;}
[class*="st-key-pgr_"] [data-testid="stMarkdownContainer"], [class*="st-key-pgr_"] [data-testid="stElementContainer"]
  {min-height:46px; overflow:visible;}
[class*="st-key-pgr_"] [data-testid="stMarkdown"] {margin-bottom:0 !important;}
[class*="st-key-pgr_"], .st-key-pg_head {min-width:%dpx;}
[class*="st-key-pgr_"] [data-testid="stHorizontalBlock"], .st-key-pg_head [data-testid="stHorizontalBlock"]
  {flex-wrap:nowrap !important; flex-direction:row !important; gap:8px;}
[class*="st-key-pgr_"] [data-testid="stColumn"], .st-key-pg_head [data-testid="stColumn"]
  {min-width:0 !important; width:auto !important;}
.st-key-pg_head {background:linear-gradient(135deg,#3B6CB7 0%%,#2C5496 100%%); border-radius:16px;
  padding:14px 12px; border-bottom:4px solid rgba(30,58,138,.4); margin-bottom:10px;}
.pg-h {font-size:0.76rem; font-weight:800; color:#FFFFFF; line-height:1.3; text-align:center;
  display:flex; align-items:center; justify-content:center; min-height:34px;}
[class*="st-key-pg_lot_"] {background:#FFFFFF; border:2px solid #E2E8F0; border-radius:16px; padding:12px;
  margin-bottom:14px;}
[class*="st-key-pg_lot_on_"] {border-color:rgba(59,130,246,.6);}
.pg-no {height:44px; border-radius:12px; background:#475569; color:#fff; font-weight:800; display:flex;
  align-items:center; justify-content:center;}
.pg-lk {height:44px; border-radius:12px; background:#F1F5F9; border:1px solid #E2E8F0; color:#0F172A;
  font-weight:800; font-size:0.88rem; display:flex; align-items:center; justify-content:center; text-align:center;
  line-height:1.15; padding:0 6px;}
.pg-var {background:#EDE9FE; color:#5B21B6; border:1px solid #DDD6FE; font-weight:800; border-radius:999px;
  padding:3px 12px; font-size:0.8rem;}
[class*="st-key-pgc_"] {background:#F4F8FE; border:2px solid #BFDBFE; border-radius:12px; padding:8px 14px;
  margin-top:10px;}
[class*="st-key-pgc_on_"] {border-color:#3B82F6;}
[class*="st-key-pgc_"] [data-testid="stHorizontalBlock"] {align-items:center;}
[class*="st-key-pgc_"] [data-baseweb="select"] > div {border:2px solid #3B82F6; border-radius:12px;
  font-weight:800; color:#2C5496; background:#FFFFFF;}
[class*="st-key-pgc_on_"] [data-baseweb="select"] > div {background:#3B82F6; color:#FFFFFF;}
[class*="st-key-pgc_on_"] [data-baseweb="select"] svg {fill:#FFFFFF;}
.pg-cuxl {font-size:0.75rem; font-weight:800; letter-spacing:.06em; color:#2C5496;}
.pg-tag {display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 12px;
  font-size:0.78rem; font-weight:800;}
.pg-tag.on {background:#16A34A; color:#fff;}
.pg-tag.off {background:#FEF3C7; color:#78350F; border:1px solid #FCD34D;}
.pg-hint {font-size:0.8rem; color:#475569; font-weight:600; margin-left:8px;}
.pg-pills {display:flex; gap:8px; justify-content:flex-end; flex-wrap:wrap;}
.pg-pill {background:#fff; border:1px solid #BFDBFE; border-radius:999px; padding:5px 12px; font-size:0.78rem;
  font-weight:700; color:#2C5496;}
.pg-pill b {color:#0F172A;}
.pg-strip {display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;
  background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; padding:8px 12px; margin:12px 0 10px 0;
  font-size:0.8rem; font-weight:700; color:#475569;}
.pg-badge {border-radius:8px; padding:2px 10px; font-weight:800; border:1px solid #CBD5E1; background:#fff;
  color:#0F172A; margin-left:6px;}
.pg-chip {display:inline-flex; align-items:center; gap:8px; border-radius:8px; padding:4px 12px; color:#fff;
  font-weight:800; font-size:0.8rem; margin-bottom:6px;}
.pg-chip span {background:rgba(255,255,255,.95); border-radius:6px; padding:1px 8px;}
/* same label height for real boxes and 'not needed' boxes, so every box lines up */
[class*="st-key-pgb_"] [data-testid="stWidgetLabel"] {height:2.7em; min-height:2.7em; display:flex;
  align-items:flex-end; margin-bottom:4px;}
.pg-na-l {font-size:0.72rem; font-weight:700; line-height:1.2; height:2.7em; display:flex; align-items:flex-end;
  margin-bottom:4px;}
.pg-na {height:46px; box-sizing:border-box; border-radius:12px; background:#E2E8F0; border:2px solid #CBD5E1;
  color:#64748B; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.78rem;
  cursor:not-allowed;}
[class*="st-key-pgb_"] {border-radius:12px; padding:10px 12px; margin-bottom:10px;}
[class*="st-key-pgb_mt_"] {background:#F4F8FE; border:2px solid rgba(96,165,250,.45);}
[class*="st-key-pgb_gt_"] {background:#FDF4F5; border:2px solid rgba(251,113,133,.45);}
[class*="st-key-pgb_dump_"] {background:#F5F5FE; border:2px solid rgba(129,140,248,.45);}
[class*="st-key-pgb_mt_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_mt_"] .pg-na-l {color:#1E3A8A;}
[class*="st-key-pgb_gt_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_gt_"] .pg-na-l {color:#9F1239;}
[class*="st-key-pgb_dump_"] [data-testid="stWidgetLabel"] p, [class*="st-key-pgb_dump_"] .pg-na-l {color:#3730A3;}
[class*="st-key-pgb_mt_"] [data-testid="stNumberInputContainer"] {border-color:rgba(96,165,250,.7);}
[class*="st-key-pgb_gt_"] [data-testid="stNumberInputContainer"] {border-color:rgba(251,113,133,.7);}
[class*="st-key-pgb_dump_"] [data-testid="stNumberInputContainer"],
[class*="st-key-pgb_dump_"] [data-testid="stTextInputRootElement"] {border-color:rgba(129,140,248,.7);}
[class*="st-key-pgb_dump_"] button {border:1px solid #A5B4FC; color:#4338CA; font-weight:800;}
.st-key-pg_save button {background:linear-gradient(135deg,#16A34A 0%%,#15803D 100%%); border-color:#15803D;
  color:#fff; font-weight:800;}
.st-key-pg_save button:disabled {background:#E2E8F0; border-color:#E2E8F0; color:#94A3B8;}
@media (max-width: 640px) { .st-key-pg_grid input {font-size:16px;} }
</style>""" % (840, )


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


HEAD = [("n", "No"), ("parent_sku", "Parent SKU Name"), ("variety", "Variety"), ("size", "Size Spec"),
        ("table_no", "Table #"), ("boxes_moved", "# Qty Moved to Grading table (Vendor Lots / Boxes) (B)"),
        ("stock_type", "Production prod Classification")]
ROW_W = [0.6, 1.5, 1.3, 1.1, 0.9, 1.8, 1.7]
BANDS = [  # (key, name on the chip, input fields, chip colour)
    ("mt", "MT Ready", ["mt_packs", "mt_loose_kg", "left_box", "left_kg", "left_pcs"], "#2563EB"),
    ("gt", "GT Stock", ["gt_box", "gt_kg", "gt_pcs"], "#BE123C"),
    ("dump", "Dump", ["dump_kg", "dump_pcs", "comment"], "#4F46E5"),
]
_KG = {"mt": "mt_kg", "gt": "gt_kg_total", "dump": "dump_kg_total"}


def _band_cell(f: str, ln: dict, s: dict, title: dict) -> None:
    k = f"pg_{ln['id']}_{f}"
    lab = title.get(f, "")
    if f == "comment":
        st.text_input(lab, key=k, placeholder="Type a note")
    elif f in s["need"]:
        st.number_input(lab, min_value=0.0, step=1.0, value=None, key=k, format="%g", placeholder="0")
    else:
        st.markdown(f"<div class='pg-na-l'>{lab}</div><div class='pg-na' title='Not needed for this Cux Lot'>"
                    "Not needed</div>", unsafe_allow_html=True)


def _lot_block(i: int, ln: dict, lot: dict, s: dict, packs: list, title: dict, rows: list) -> None:
    on = bool(s["pack"])
    with st.container(key=f"pg_lot_{'on' if on else 'off'}_{ln['id']}"):
        with st.container(key=f"pgw_{ln['id']}"):
            with st.container(key=f"pgr_{ln['id']}"):
                cells = st.columns(ROW_W)
                for col, (f, _h) in zip(cells, HEAD):
                    if f == "n":
                        col.markdown(f"<div class='pg-no'>{i + 1}</div>", unsafe_allow_html=True)
                        continue
                    v = lot.get(f, "")
                    if f == "boxes_moved":
                        v = f"{pr._f(v):g}" if pr._f(v) else ""
                    if f == "variety" and v:
                        v = f"<span class='pg-var'>{v}</span>"
                    col.markdown(f"<div class='pg-lk'>{v or '&nbsp;'}</div>", unsafe_allow_html=True)
        a, b, pcs = pr._f(lot.get("box_kg")), pr._f(lot.get("boxes_moved")), pr._f(lot.get("pcs_per_box"))
        with st.container(key=f"pgc_{'on' if on else 'off'}_{ln['id']}"):
            c = st.columns([0.55, 1.0, 2.4, 2.6], vertical_alignment="center")
            c[0].markdown("<span class='pg-cuxl'>CUX LOT:</span>", unsafe_allow_html=True)
            k = f"pg_{ln['id']}_pack"
            if st.session_state.get(k) not in [PICK] + packs:
                st.session_state[k] = PICK
            c[1].selectbox("Cux Lot", [PICK] + packs, key=k, label_visibility="collapsed")
            if on:
                c[2].markdown(f"<span class='pg-tag on'>● Active lot · {lot.get('parent_sku', '')}"
                              f"{' (' + str(lot.get('variety')) + ')' if lot.get('variety') else ''}</span>",
                              unsafe_allow_html=True)
            else:
                c[2].markdown("<span class='pg-tag off'>Action required</span><span class='pg-hint'>Pick the Cux "
                              "Lot to open MT, GT and Dump.</span>", unsafe_allow_html=True)
            pills = [f"Lot weight: <b>{a:g} kg</b>" if a else "", f"Pcs in lot: <b>{pcs:g}</b>" if pcs else "",
                     f"Boxes moved: <b>{b:g}</b>" if b else ""]
            c[3].markdown("<div class='pg-pills'>" + "".join(f"<span class='pg-pill'>{p}</span>" for p in pills if p)
                          + "</div>", unsafe_allow_html=True)
        if not on:
            return
        comp = pr.compute(lot.get("box_kg"), lot.get("pcs_per_box"), lot.get("boxes_moved"), s["pack"], s["vals"])
        txt, bg, fg = _eff_cell(s, lot)
        stt, sbg, sfg = (("Saved", "#DCFCE7", "#166534") if s["same"] else ("Not saved", "#FEF3C7", "#78350F")
                         if s["touched"] else ("Not entered", "#F1F5F9", "#64748B"))
        st.markdown(f"<div class='pg-strip'><span>Category Efficiency% (K / J):<span class='pg-badge' "
                    f"style='background:{bg};color:{fg}'>{txt}</span></span><span>Status:<span class='pg-badge' "
                    f"style='background:{sbg};color:{sfg};border-color:{sbg}'>{stt}</span></span></div>",
                    unsafe_allow_html=True)
        for band, name, fields, colr in BANDS:
            with st.container(key=f"pgb_{band}_{ln['id']}"):
                chip = (f"<div class='pg-chip' style='background:{colr}'>{name}"
                        f"<span style='color:{colr}'>{comp[_KG[band]]:.1f} kg</span></div>")
                if band == "dump":
                    h = st.columns([4, 1], vertical_alignment="center")
                    h[0].markdown(chip, unsafe_allow_html=True)
                    if h[1].button("＋ pack", key=f"pg_{ln['id']}_add", help="Another Cux lot from this lot",
                                   width="stretch"):
                        rows.insert(rows.index(ln) + 1, {"id": uuid.uuid4().hex[:8], "lot_id": ln["lot_id"],
                                                         "saved": None})
                        st.rerun(scope="fragment")
                else:
                    st.markdown(chip, unsafe_allow_html=True)
                cols = st.columns(len(fields))
                for col, f in zip(cols, fields):
                    with col:
                        _band_cell(f, ln, s, title)


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
    active = sum(1 for s in states.values() if s["pack"])
    st.caption(f"{active} of {len(rows)} line(s) active · {done} saved · grey comes from Pre-Production Actual · "
               "pick the Cux Lot, then fill MT, GT and Dump")
    title = {c[0]: c[1] for c in COLS}
    with st.container(key="pg_grid"):
        with st.container(key="pg_headw"):
            with st.container(key="pg_head"):
                for col, (_f, h) in zip(st.columns(ROW_W), HEAD):
                    col.markdown(f"<div class='pg-h'>{h}</div>", unsafe_allow_html=True)
        for i, ln in enumerate(rows):
            lot = lots.get(ln["lot_id"])
            if lot is not None:
                _lot_block(i, ln, lot, states[ln["id"]], packs, title, rows)

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
