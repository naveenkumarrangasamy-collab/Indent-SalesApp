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
        st.markdown(f"<div class='pr-info'><b>{fruit}</b> · table {table} · {_lot_label(lot)} × {a:g} kg = "
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
