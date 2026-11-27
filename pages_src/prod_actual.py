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
.st-key-pa_card [class*="_add"] button {background:#2563EB; border-color:#2563EB; color:#fff;
  font-weight:800;}
</style>"""


def _pick(label: str, opts: list[str], key: str, blank: bool = True) -> str:
    vals = ([BLANK] if blank else []) + opts
    if st.session_state.get(key) not in vals:
        st.session_state.pop(key, None)
    v = st.selectbox(label, vals, key=key, placeholder="Choose…", index=None if not blank else 0)
    return "" if v in (None, BLANK) else v


def _typed(label: str, opts: list[str], key: str, hint: str) -> str:
    """A dropdown the user can also type a new value into (same box, Enter adds it)."""
    cur = st.session_state.get(key)
    if cur and cur not in opts:
        opts = opts + [cur]
    v = st.selectbox(label, opts, key=key, index=None, placeholder=hint, accept_new_options=True)
    return str(v or "").strip()


def _pending() -> list[dict]:
    return st.session_state.setdefault("pa_rows", [])


def _preview_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Fruit": r["parent_sku"], "Origin": r["origin"], "Variety": r["variety"],
                          "Brand": r["brand"], "Spec": r["size"], "Box kg": r["box_kg"], "Pcs/box": r["pcs_per_box"] or "",
                          "Executive": r.get("executive", ""), "Table": r["table_no"],
                          "Number of boxes": r["boxes_moved"], "Stock": r["stock_type"],
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
        exec_tab = pa.read_executives()
        _, parent_tab = mapping_sheet.load()
    except SheetError as e:
        common.sheet_error(e, "Could not load the masters.")
        return

    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="pa_day", format="DD/MM/YYYY")
    city = cities[0] if len(cities) == 1 else ""
    if len(cities) > 1:       # 27 Nov (user): the city is chosen, never assumed
        with top[1]:
            city = st.pills("City", cities, key="pa_city") or ""

    ready = bool(day and city)
    sku = m.sku[m.sku["City"] == city] if city else m.sku
    parents = sorted({str(p).strip() for p in sku["Parent SKU"] if str(p).strip()}, key=str.casefold)
    if ready and not parents:
        st.info("No fruits mapped for this city yet.")
        return
    if not ready:
        st.session_state.pop("pa_parent", None)
    parent = st.pills("Fruit picked from inventory", parents, key="pa_parent", disabled=not ready)
    if not ready:
        st.caption("Choose the " + " and the ".join(x for x, ok in (("date", day), ("city", city)) if not ok)
                   + " first.")
    elif parent:
        _entry_card(parent, city, day, parent_tab, saved, brand_tab, exec_tab)
    else:
        st.caption("Pick a fruit to add what goes onto the tables.")

    rows = _pending()
    if rows:
        st.markdown(f"#### Added · {len(rows)} to save")
        st.dataframe(common.numbered(_preview_df(rows)), hide_index=True, width="stretch")
        c = st.columns([1, 1, 3])
        if c[0].button("Save", type="primary", icon=":material/save:", width="stretch", key="pa_save"):
            _confirm(rows, user)
        drop = c[1].selectbox("Remove", ["—"] + [f"#{i + 1}" for i in range(len(rows))], key="pa_drop",
                              label_visibility="collapsed")
        if drop != "—":
            rows.pop(int(drop[1:]) - 1)
            st.session_state.pop("pa_drop", None)
            st.rerun()

    if ready:
        _saved_today(saved, city, day)


def _locked(col, label: str, val, unit: str, size: str) -> None:
    """Box kg / Pcs per box come from the master only (26 Nov, user): shown, never typed."""
    if val:
        body = f"{val:g}<small>{unit}</small> <span title='From the master'>🔒</span>"
        cls = "pa-ro"
    else:
        body, cls = ("Choose a spec first", "pa-ro") if not size else ("Not in master", "pa-ro miss")
    col.markdown(f"<div class='pa-l'>{label}</div><div class='{cls}'>{body}</div>", unsafe_allow_html=True)


def _entry_card(parent: str, city: str, day, parent_tab, saved, brand_tab=None, exec_tab=None) -> None:
    opts = pa.option_rows(parent, parent_tab, saved, brand_tab)
    k = f"pa_{pa.pkey(parent)}"
    only_box = pa.box_only(parent)
    with st.container(key="pa_card"):
        st.markdown(f"<div class='pa-hd'>{parent} · new lot on table<span>{city} · {day.strftime('%d/%m/%Y')}"
                    "</span></div>", unsafe_allow_html=True)
        st.markdown("<div class='pa-sec'>1 · Fruit picked from inventory</div>", unsafe_allow_html=True)
        r1 = st.columns(4)
        with r1[0]:
            origin = _pick("Origin", pa.choices(opts, "origin"), f"{k}_o")
        with r1[1]:
            variety = _pick("Variety", pa.choices(opts, "variety", origin=origin), f"{k}_v")
        with r1[2]:
            size = _pick("Spec", pa.choices(opts, "size", origin=origin, variety=variety), f"{k}_s", blank=False)
        with r1[3]:   # brands per SKU (fruit + origin + variety + size) from the Brand_Master tab
            b_opts = pa.brands(opts, origin, variety, size)
            brand = _typed("Brand", b_opts, f"{k}_b", "Choose or type")   # typed in the same box, Enter adds it

        _, pcs0 = pa.defaults(opts, origin=origin, variety=variety, size=size) if size else (None, None)
        weights = pa.box_weights(opts, origin=origin, variety=variety, size=size) if size else []
        pcs0 = 0 if only_box else int(pcs0 or 0)
        st.markdown("<div class='pa-sec'>2 · Choose the weight of the box</div>", unsafe_allow_html=True)
        r2 = st.columns(1 if only_box else 2)
        if len(weights) > 1:      # several box weights in the master: the user says which box was taken
            wk = f"{k}_w_{origin}_{variety}_{size}"
            w = r2[0].selectbox("Box kg", weights, index=None, placeholder="Choose the box weight", key=wk,
                                format_func=lambda x: f"{x:g} kg")
            box_kg = float(w or 0)
        else:
            box_kg = float(weights[0]) if weights else 0.0
            _locked(r2[0], "Box kg", box_kg, "kg", size)
        pcs = 0
        if not only_box:
            if pcs0:              # a piece count is known: it starts from the master and can be changed
                with r2[1]:
                    pcs = int(st.number_input("Pcs/box", min_value=0, step=1, value=pcs0, format="%d",
                                              key=f"{k}_p_{origin}_{variety}_{size}") or 0)
            else:
                r2[1].markdown("<div class='pa-l'>Pcs/box</div><div class='pa-ro'>"
                               + ("Kg only" if size else "Choose a spec first") + "</div>", unsafe_allow_html=True)

        st.markdown("<div class='pa-sec'>3 · Assign box to grading executive</div>", unsafe_allow_html=True)
        r3 = st.columns(4)
        names = pa.executives(exec_tab, city)
        names += [n for n in dict.fromkeys(r.get("executive", "") for r in _pending() if r.get("city") == city)
                  if n and n.casefold() not in {x.casefold() for x in names}]
        with r3[0]:    # names of this city only; a new name is typed here and kept for the city on Save
            person = _typed("Executive name", names, f"pa_ex_{pa.pkey(city)}", "Choose or type a name")
        table = r3[1].selectbox("Table number", TABLES, index=None, placeholder="Choose…", key=f"{k}_t")
        with r3[2].container(key=f"pa_box_{k}"):
            boxes = st.number_input("Number of boxes", min_value=0.0, step=1.0, value=None,
                                    key=f"{k}_n", placeholder="Enter number of box", format="%g")
        stock = r3[3].selectbox("Stock", pa.STOCK_CHOICES, index=0, key=f"{k}_st")

        if boxes and box_kg:
            st.markdown(f"<div class='pa-sub'>= {boxes * box_kg:g} kg on table "
                        f"{table or '?'}{f' · {pcs * boxes:g} pcs' if pcs else ''}</div>", unsafe_allow_html=True)
        entry = {"production_date": day.isoformat(), "city": city, "parent_sku": parent, "origin": origin,
                 "variety": variety, "brand": brand, "size": size, "box_kg": box_kg, "pcs_per_box": pcs or "",
                 "table_no": table or "", "boxes_moved": boxes or 0, "stock_type": stock, "executive": person}
        missing = [("Box kg (choose the weight)" if len(weights) > 1 else "Box kg (not in master)")
                   if m == "Box kg" and size else m for m in pa.entry_errors(entry)]
        if pcs0 and not pcs:
            missing.append("Pcs/box")
        f1, f2 = st.columns([3, 1], vertical_alignment="center")
        if missing:
            f1.markdown(f"<span class='pa-todo'>Still to fill: {', '.join(missing)}</span>", unsafe_allow_html=True)
        # never disabled: a number just typed is taken when the button is clicked (no Enter needed)
        if f2.button("Add", icon=":material/add:", key=f"{k}_add", width="stretch"):
            if missing:
                st.toast("Still to fill: " + ", ".join(missing), icon="⚠️")
            else:
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
