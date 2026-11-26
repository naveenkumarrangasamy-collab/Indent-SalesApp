"""Pre-Production Actual page (25 Nov, trial): put lots on grading tables.

Fruit (parent SKU) is the only header; everything else is picked from short dropdowns
(Brand can also be typed). Entries collect in a preview list and are saved together."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, mapping_sheet, masters
from core import prod_actual as pa
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common

NEW = "＋ New brand"
BLANK = "—"
TABLES = [str(i) for i in range(1, 11)]

CSS = """<style>
.st-key-pa_card {border:1px solid #DDE3EA; border-radius:10px; padding:14px 16px 6px 16px; background:#FBFCFD;}
.st-key-pa_card label p {font-size:0.82rem; color:#4A5562; font-weight:600;}
.pa-sub {font-size:0.8rem; color:#6B7684; margin:-6px 0 6px 0;}
</style>"""


def _pick(label: str, opts: list[str], key: str, blank: bool = True) -> str:
    vals = ([BLANK] if blank else []) + opts
    if st.session_state.get(key) not in vals:
        st.session_state.pop(key, None)
    v = st.selectbox(label, vals, key=key, placeholder="Choose…", index=None if not blank else 0)
    return "" if v in (None, BLANK) else v


def _pending() -> list[dict]:
    return st.session_state.setdefault("pa_rows", [])


def _preview_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Fruit": r["parent_sku"], "Origin": r["origin"], "Variety": r["variety"],
                          "Brand": r["brand"], "Size": r["size"], "Box kg": r["box_kg"], "Pcs/box": r["pcs_per_box"] or "",
                          "Table": r["table_no"], "Boxes": r["boxes_moved"], "Stock": r["stock_type"],
                          "Kg on table": round(float(r["box_kg"]) * float(r["boxes_moved"]), 2)} for r in rows])


@st.dialog("Save these entries?", width="large")
def _confirm(rows: list[dict], user: User) -> None:
    st.dataframe(common.numbered(_preview_df(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pa_ok"):
        try:
            n = pa.save(get_backend(), rows, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pa_rows"] = []
        common.flash("success", f"{n} entr{'y' if n == 1 else 'ies'} saved · see Production sheet → "
                                "Production Actual.")
        st.rerun()
    if c2.button("Back", width="stretch", key="pa_back"):
        st.rerun()


def render(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Pre-Production Actual")
    try:
        m = masters.load_masters()
        saved = pa.read()
        brand_tab = pa.read_brands()
        _, parent_tab = mapping_sheet.load()
    except SheetError as e:
        common.sheet_error(e, "Could not load the masters.")
        return

    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="pa_day", format="DD/MM/YYYY")
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key="pa_city") or cities[0]

    sku = m.sku[m.sku["City"] == city] if city else m.sku
    parents = sorted({str(p).strip() for p in sku["Parent SKU"] if str(p).strip()}, key=str.casefold)
    if not parents:
        st.info("No fruits mapped for this city yet.")
        return
    parent = st.pills("Fruit", parents, key="pa_parent")
    if parent:
        _entry_card(parent, city, day, parent_tab, saved, brand_tab)
    else:
        st.caption("Pick a fruit to add what goes onto the tables.")

    rows = _pending()
    if rows:
        st.markdown(f"#### Preview · {len(rows)} to save")
        st.dataframe(common.numbered(_preview_df(rows)), hide_index=True, width="stretch")
        c = st.columns([1, 1, 3])
        if c[0].button("Save all", type="primary", icon=":material/save:", width="stretch", key="pa_save"):
            _confirm(rows, user)
        drop = c[1].selectbox("Remove", ["—"] + [f"#{i + 1}" for i in range(len(rows))], key="pa_drop",
                              label_visibility="collapsed")
        if drop != "—":
            rows.pop(int(drop[1:]) - 1)
            st.session_state.pop("pa_drop", None)
            st.rerun()

    _saved_today(saved, city, day)


def _entry_card(parent: str, city: str, day, parent_tab, saved, brand_tab=None) -> None:
    opts = pa.option_rows(parent, parent_tab, saved, brand_tab)
    k = f"pa_{pa.pkey(parent)}"
    with st.container(key="pa_card"):
        st.markdown(f"**{parent}**")
        r1 = st.columns(4)
        with r1[0]:
            origin = _pick("Origin", pa.choices(opts, "origin"), f"{k}_o")
        with r1[1]:
            variety = _pick("Variety", pa.choices(opts, "variety", origin=origin), f"{k}_v")
        with r1[2]:
            size = _pick("Size", pa.choices(opts, "size", origin=origin, variety=variety), f"{k}_s", blank=False)
        with r1[3]:   # 26 Nov: brands per SKU (fruit + origin + variety + size) from the Brand_Master tab
            b_opts = pa.brands(opts, origin, variety, size)
            brand = _pick("Brand", b_opts + [NEW], f"{k}_b")
            if brand == NEW:
                brand = st.text_input("New brand", key=f"{k}_bn", placeholder="Type brand").strip()

        kg0, pcs0 = pa.defaults(opts, origin=origin, variety=variety, size=size) if size else (None, None)
        only_box = pa.box_only(parent)
        r2 = st.columns([1, 1, 1, 1.5]) if only_box else st.columns([1, 1, 1, 1, 1.5])
        box_kg = r2[0].number_input("Box kg", min_value=0.0, step=0.5, value=float(kg0 or 0),
                                    key=f"{k}_kg_{size}_{origin}_{variety}")
        if only_box:
            pcs, rest = 0, r2[1:]
        else:
            pcs = r2[1].number_input("Pcs/box", min_value=0, step=1, value=int(pcs0 or 0),
                                     key=f"{k}_pcs_{size}_{origin}_{variety}")
            rest = r2[2:]
        table = rest[0].selectbox("Table", TABLES, index=None, placeholder="Choose…", key=f"{k}_t")
        boxes = rest[1].number_input("Box/Tray" if only_box else "Boxes", min_value=0.0, step=1.0, value=0.0,
                                     key=f"{k}_n")
        stock = rest[2].selectbox("Stock", pa.STOCK_CHOICES, index=0, key=f"{k}_st")

        if boxes and box_kg:
            st.markdown(f"<div class='pa-sub'>= {boxes * box_kg:g} kg on table "
                        f"{table or '?'}{f' · {pcs * boxes:g} pcs' if pcs else ''}</div>", unsafe_allow_html=True)
        entry = {"production_date": day.isoformat(), "city": city, "parent_sku": parent, "origin": origin,
                 "variety": variety, "brand": brand, "size": size, "box_kg": box_kg, "pcs_per_box": pcs or "",
                 "table_no": table or "", "boxes_moved": boxes, "stock_type": stock}
        missing = pa.entry_errors(entry)
        if st.button("Add to preview", icon=":material/add:", key=f"{k}_add", disabled=bool(missing),
                     help=("Fill: " + ", ".join(missing)) if missing else None):
            _pending().append(entry)
            for x in (f"{k}_n", f"{k}_t"):
                st.session_state.pop(x, None)
            st.rerun()
        if missing:
            st.caption("Still to fill: " + ", ".join(missing))


def _saved_today(saved: pd.DataFrame, city: str, day) -> None:
    v = pa.view(saved, day.isoformat(), city)
    if v.empty:
        return
    st.markdown(f"#### Saved · {day.strftime('%d %b')} · {len(v)}")
    st.dataframe(common.numbered(v.drop(columns=["Date", "City"])), hide_index=True, width="stretch")
