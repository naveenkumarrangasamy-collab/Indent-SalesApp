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
.pa-sec {font-size:0.82rem; font-weight:800; color:#2C5496; text-align:left; margin:12px 0 4px 2px;}
.pa-ex {background:#F4F8FE; color:#0C447C; border:1px solid #B5D4F4; border-radius:10px; padding:6px 12px;
  font-weight:800; margin:10px 0 4px 0; display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px;}
.pa-ex span {font-weight:700; font-size:0.8rem; color:#185FA5;}
.st-key-pa_card [class*="_go"] button {background:#1F6B4A; border-color:#1F6B4A; color:#fff; font-weight:800;}
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


def _pick(label: str, opts: list[str], key: str, blank: bool = True, fmt=None) -> str:
    vals = ([BLANK] if blank else []) + opts
    if st.session_state.get(key) not in vals:
        st.session_state.pop(key, None)
    v = st.selectbox(label, vals, key=key, placeholder="Choose…", index=None if not blank else 0,
                     format_func=fmt or str)
    return "" if v in (None, BLANK) else v


def _typed(label: str, opts: list[str], key: str, hint: str) -> str:
    """A dropdown the user can also type a new value into (same box, Enter adds it)."""
    cur = st.session_state.get(key)
    if cur and cur not in opts:
        opts = opts + [cur]
    v = st.selectbox(label, opts, key=key, index=None, placeholder=hint, accept_new_options=True)
    return str(v or "").strip()


def _add_name(city: str, key: str) -> None:
    """＋ Add name: save the typed name for this city and select it."""
    name = " ".join(str(st.session_state.get(f"{key}_new") or "").split())
    if not name:
        return
    u = st.session_state.get("user") or {}
    try:
        pa.add_executive(get_backend(), city, name, str(u.get("email", "")))
    except Exception as e:  # noqa: BLE001
        st.toast(f"Name not saved: {e}", icon="⚠️")
        return
    st.session_state[key] = name
    st.session_state[f"{key}_new"] = ""


def _pending() -> list[dict]:
    return st.session_state.setdefault("pa_rows", [])


def _preview_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Fruit": r["parent_sku"], "Origin": r["origin"], "Variety": r["variety"],
                          "Brand": r["brand"], "Spec": r["size"], "Box kg": r["box_kg"], "Pcs/box": r["pcs_per_box"] or "",
                          "Executive": r.get("executive", ""), "Table": r["table_no"],
                          "Number of boxes": r["boxes_moved"], "Stock": r["stock_type"],
                          "Kg on table": round(float(r["box_kg"]) * float(r["boxes_moved"]), 2)} for r in rows])


@st.dialog("Save these entries?", width="large")
def _confirm(rows: list[dict], user: User, nxt: str = "") -> None:
    st.dataframe(common.numbered(_preview_df(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pa_ok"):
        try:
            n = pa.save(get_backend(), [{k: v for k, v in r.items() if k != "added_at"} for r in rows], user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pa_rows"] = []
        common.flash("success", f"{n} entr{'y' if n == 1 else 'ies'} saved.")
        if nxt and nxt in common.PAGES:        # Save / Proceed for production
            st.switch_page(common.PAGES[nxt])
        st.rerun()
    if c2.button("Back", width="stretch", key="pa_back"):
        st.rerun()


def _clock(stamp) -> str:
    try:
        return pd.to_datetime(str(stamp)).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return ""


def _last_times(rows, name_key: str, time_key: str) -> dict[str, str]:
    """Executive name -> the latest time a lot was given to them."""
    out: dict[str, str] = {}
    for r in rows:
        n, t = str(r.get(name_key) or "").strip() or "No name", str(r.get(time_key) or "")
        if t and t > out.get(n, ""):
            out[n] = t
    return out


def _by_executive(df: pd.DataFrame, box_col: str, last: dict[str, str] | None = None) -> None:
    """One small table per executive name (27 Nov: executive level, not table level), headed by the name
    and the time the last lot was given to them (table numbers are in the rows)."""
    if "Executive" not in df.columns:
        st.dataframe(common.numbered(df), hide_index=True, width="stretch")
        return
    d = df.copy()
    d["Executive"] = [str(x).strip() or "No name" for x in d["Executive"].fillna("")]
    for name, part in d.groupby("Executive", sort=True):
        boxes = sum(pa._num(x) or 0 for x in part[box_col])
        at = _clock((last or {}).get(name, ""))
        st.markdown(f"<div class='pa-ex'>{name}<span>{'Last given ' + at + ' · ' if at else ''}{len(part)} SKU"
                    f"{'' if len(part) == 1 else 's'} · {boxes:g} boxes</span></div>", unsafe_allow_html=True)
        st.dataframe(common.numbered(part.drop(columns=["Executive"]).reset_index(drop=True)), hide_index=True,
                     width="stretch")


def _to_top() -> None:
    """After Add the page goes back up to the fruits."""
    if not st.session_state.pop("pa_top", False):
        return
    import streamlit.components.v1 as components
    components.html("<script>const d = window.parent.document;"
                    "['stMain', 'stAppViewContainer'].forEach(t => {const e = d.querySelector"
                    "('[data-testid=\"' + t + '\"]'); if (e) e.scrollTo({top: 0, behavior: 'smooth'});});"
                    "window.parent.scrollTo(0, 0);</script>", height=0)


def render(user: User, nxt: str = "") -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    _to_top()
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
        _entry_card(parent, city, day, parent_tab, saved, brand_tab, exec_tab, user, nxt)
    else:
        st.caption("Pick a fruit to add what goes onto the tables.")

    rows = _pending()
    if rows:
        st.markdown(f"#### Added · {len(rows)} to save")
        _by_executive(_preview_df(rows), "Number of boxes", _last_times(rows, "executive", "added_at"))
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


def _entry_card(parent: str, city: str, day, parent_tab, saved, brand_tab=None, exec_tab=None, user=None,
                nxt: str = "") -> None:
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
            sw = pa.size_weights(opts, origin=origin, variety=variety)
            flat = [w[0] for w in sw.values() if len(w) == 1]
            usual = max(set(flat), key=flat.count) if flat else None

            def _spec(s, sw=sw, usual=usual):      # "60C · 10 kg": a spec that only comes in the other box
                w = sw.get(s) or []
                return f"{s} · {w[0]:g} kg" if len(w) == 1 and usual is not None and w[0] != usual else s
            size = _pick("Spec", list(sw), f"{k}_s", blank=False, fmt=_spec)
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
        pcs = pcs0                # 27 Nov (user): the count is never typed; only the box weight is chosen
        if not only_box:
            if pcs0 or not size:
                _locked(r2[1], "Pcs/box", pcs0, "pcs", size)
            else:
                r2[1].markdown("<div class='pa-l'>Pcs/box</div><div class='pa-ro'>Kg only</div>",
                               unsafe_allow_html=True)

        st.markdown("<div class='pa-sec'>3 · Assign box to grading executive</div>", unsafe_allow_html=True)
        r3 = st.columns(4)
        names = pa.executives(exec_tab, city)
        names += [n for n in dict.fromkeys(r.get("executive", "") for r in _pending() if r.get("city") == city)
                  if n and n.casefold() not in {x.casefold() for x in names}]
        ek = f"pa_ex_{pa.pkey(city)}"
        with r3[0]:    # names of this city only; ＋ Add name onboards a new one for the city at once
            person = _typed("Executive name", names, ek, "Choose a name")
            with st.popover("＋ Add name", width="stretch"):
                st.text_input("New executive name", key=f"{ek}_new", placeholder="Type the name")
                st.button("Add", key=f"{ek}_addbtn", type="primary", width="stretch",
                          on_click=_add_name, args=(city, ek))
                st.caption(f"Kept for {city} only.")
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
        f1, f2, f3 = st.columns([2, 1, 1.4], vertical_alignment="center")
        if missing:
            f1.markdown(f"<span class='pa-todo'>Still to fill: {', '.join(missing)}</span>", unsafe_allow_html=True)
        # never disabled: a number just typed is taken when the button is clicked (no Enter needed)
        if f2.button("Add", icon=":material/add:", key=f"{k}_add", width="stretch"):
            if missing:
                st.toast("Still to fill: " + ", ".join(missing), icon="⚠️")
            else:
                _pending().append({**entry, "added_at": config.now_iso()})
                for x in (f"{k}_n", f"{k}_t", "pa_parent"):    # back to the fruits for the next SKU
                    st.session_state.pop(x, None)
                st.session_state["pa_top"] = True
                st.rerun()
        # 27 Nov (user): save here itself and go on to production (a filled card is included)
        if f3.button("Save / Proceed for production", icon=":material/arrow_forward:", key=f"{k}_go",
                     width="stretch"):
            todo = _pending() + ([] if missing else [entry])
            if not todo:
                st.toast("Nothing to save yet. Still to fill: " + ", ".join(missing), icon="⚠️")
            else:
                if not missing:
                    _pending().append({**entry, "added_at": config.now_iso()})
                    for x in (f"{k}_n", f"{k}_t"):
                        st.session_state.pop(x, None)
                _confirm(_pending(), user, nxt)


def _saved_today(saved: pd.DataFrame, city: str, day) -> None:
    v = pa.view(saved, day.isoformat(), city)
    if v.empty:
        return
    st.markdown(f"#### Saved · {day.strftime('%d %b')} · {len(v)}")
    d = saved[(saved["production_date"].astype(str).str[:10] == day.isoformat())
              & (saved["city"].astype(str) == city)] if "saved_at" in saved.columns else saved.iloc[0:0]
    _by_executive(v.drop(columns=["Date", "City"]), "Boxes",
                  _last_times(d.to_dict("records"), "executive", "saved_at"))
