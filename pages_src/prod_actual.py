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
/* 26 Nov: same look as Processed: blue header, centred bold fields, locked box kg / pcs from the master */
.st-key-pa_card {border:2px solid rgba(59,130,246,.45); border-radius:16px; padding:14px 16px; background:#FFFFFF;}
.pa-hd {background:#F4F8FE; color:#0C447C; border:2px solid #85B7EB; border-radius:12px; padding:10px 14px;
  display:flex; justify-content:space-between; align-items:center; font-weight:800; flex-wrap:wrap; gap:6px;}
.pa-hd span {background:#fff; color:#0C447C; border:1px solid #B5D4F4; border-radius:999px; padding:2px 10px;
  font-size:0.78rem; font-weight:700;}
.pa-sec {font-size:0.78rem; font-weight:800; color:#2C5496; text-align:center; margin:12px 0 4px 0;}
.st-key-pa_card [data-testid="stWidgetLabel"] {justify-content:center; width:100%;}
.st-key-pa_card [data-testid="stWidgetLabel"] p {font-size:0.75rem; font-weight:700; color:#475569; text-align:center;}
.st-key-pa_card [data-baseweb="select"] > div, .st-key-pa_card [data-testid="stNumberInputContainer"],
.st-key-pa_card [data-testid="stTextInputRootElement"] {border:2px solid #85B7EB; border-radius:12px; background:#fff;}
.st-key-pa_card [data-baseweb="select"] div, .st-key-pa_card input {text-align:center; justify-content:center;
  font-weight:700;}
.st-key-pa_card button[data-testid="stNumberInputStepUp"],
.st-key-pa_card button[data-testid="stNumberInputStepDown"] {display:none;}
.st-key-pa_card [class*="st-key-pa_box_"] [data-testid="stNumberInputContainer"] {border-color:#378ADD;}
.pa-l {font-size:0.75rem; font-weight:700; color:#475569; text-align:center; margin-bottom:4px;}
.pa-ro {height:42px; border-radius:12px; background:#E6F1FB; display:flex; align-items:center; justify-content:center;
  gap:6px; font-weight:800; color:#0C447C; cursor:not-allowed;}
.pa-ro small {font-size:0.72rem; color:#185FA5; font-weight:700;}
.pa-ro.miss {background:#FCEBEB; color:#791F1F;}
.pa-foot {display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-top:8px;}
.pa-todo {background:#FAEEDA; color:#633806; border-radius:999px; padding:4px 12px; font-size:0.78rem; font-weight:700;}
.pa-sub {font-size:0.8rem; color:#185FA5; font-weight:700; text-align:center; margin:6px 0 0 0;}
.st-key-pa_card [class*="_add"] button:not(:disabled) {background:#2563EB; border-color:#2563EB; color:#fff;
  font-weight:800;}
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


def _locked(col, label: str, val, unit: str, size: str) -> None:
    """Box kg / Pcs per box come from the master only (26 Nov, user): shown, never typed."""
    if val:
        body = f"{val:g}<small>{unit}</small> <span title='From the master'>🔒</span>"
        cls = "pa-ro"
    else:
        body, cls = ("Choose a size first", "pa-ro") if not size else ("Not in master", "pa-ro miss")
    col.markdown(f"<div class='pa-l'>{label}</div><div class='{cls}'>{body}</div>", unsafe_allow_html=True)


def _entry_card(parent: str, city: str, day, parent_tab, saved, brand_tab=None) -> None:
    opts = pa.option_rows(parent, parent_tab, saved, brand_tab)
    k = f"pa_{pa.pkey(parent)}"
    only_box = pa.box_only(parent)
    with st.container(key="pa_card"):
        st.markdown(f"<div class='pa-hd'>{parent} · new lot on table<span>{city} · {day.strftime('%d/%m/%Y')}"
                    "</span></div>", unsafe_allow_html=True)
        st.markdown("<div class='pa-sec'>1 · What is the fruit</div>", unsafe_allow_html=True)
        r1 = st.columns(4)
        with r1[0]:
            origin = _pick("Origin", pa.choices(opts, "origin"), f"{k}_o")
        with r1[1]:
            variety = _pick("Variety", pa.choices(opts, "variety", origin=origin), f"{k}_v")
        with r1[2]:
            size = _pick("Size", pa.choices(opts, "size", origin=origin, variety=variety), f"{k}_s", blank=False)
        with r1[3]:   # brands per SKU (fruit + origin + variety + size) from the Brand_Master tab
            b_opts = pa.brands(opts, origin, variety, size)
            brand = _pick("Brand", b_opts + [NEW], f"{k}_b")
            if brand == NEW:
                brand = st.text_input("New brand", key=f"{k}_bn", placeholder="Type brand").strip()

        kg0, pcs0 = pa.defaults(opts, origin=origin, variety=variety, size=size) if size else (None, None)
        box_kg, pcs = float(kg0 or 0), (0 if only_box else int(pcs0 or 0))
        st.markdown("<div class='pa-sec'>2 · From the master (cannot be changed)</div>", unsafe_allow_html=True)
        r2 = st.columns(1 if only_box else 2)
        _locked(r2[0], "Box kg", box_kg, "kg", size)
        if not only_box:
            _locked(r2[1], "Pcs/box", pcs, "pcs", size)

        st.markdown("<div class='pa-sec'>3 · What goes on the table</div>", unsafe_allow_html=True)
        r3 = st.columns(3)
        table = r3[0].selectbox("Table", TABLES, index=None, placeholder="Choose…", key=f"{k}_t")
        with r3[1].container(key=f"pa_box_{k}"):
            boxes = st.number_input("Box/Tray" if only_box else "Boxes", min_value=0.0, step=1.0, value=None,
                                    key=f"{k}_n", placeholder="Type boxes", format="%g")
        stock = r3[2].selectbox("Stock", pa.STOCK_CHOICES, index=0, key=f"{k}_st")

        if boxes and box_kg:
            st.markdown(f"<div class='pa-sub'>= {boxes * box_kg:g} kg on table "
                        f"{table or '?'}{f' · {pcs * boxes:g} pcs' if pcs else ''}</div>", unsafe_allow_html=True)
        entry = {"production_date": day.isoformat(), "city": city, "parent_sku": parent, "origin": origin,
                 "variety": variety, "brand": brand, "size": size, "box_kg": box_kg, "pcs_per_box": pcs or "",
                 "table_no": table or "", "boxes_moved": boxes or 0, "stock_type": stock}
        missing = ["Box kg (not in master)" if m == "Box kg" and size else m for m in pa.entry_errors(entry)]
        f1, f2 = st.columns([3, 1], vertical_alignment="center")
        if missing:
            f1.markdown(f"<span class='pa-todo'>Still to fill: {', '.join(missing)}</span>", unsafe_allow_html=True)
        if f2.button("Add to preview", icon=":material/add:", key=f"{k}_add", disabled=bool(missing),
                     width="stretch"):
            _pending().append(entry)
            for x in (f"{k}_n", f"{k}_t"):
                st.session_state.pop(x, None)
            st.rerun()


def _saved_today(saved: pd.DataFrame, city: str, day) -> None:
    v = pa.view(saved, day.isoformat(), city)
    if v.empty:
        return
    st.markdown(f"#### Saved · {day.strftime('%d %b')} · {len(v)}")
    st.dataframe(common.numbered(v.drop(columns=["Date", "City"])), hide_index=True, width="stretch")
