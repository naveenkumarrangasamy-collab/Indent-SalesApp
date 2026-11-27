"""Pre-Production Actual page (25 Nov, trial): put lots on grading tables.

Fruit (parent SKU) is the only header; everything else is picked from short dropdowns
(Brand can also be typed). Entries collect in a preview list and are saved together."""
from __future__ import annotations

import uuid

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
.pa-sec {font-size:0.98rem; font-weight:800; color:#2C5496; text-align:left; margin:12px 0 4px 2px;}
.st-key-pa_next {border:2px solid #639922; background:#EAF3DE; border-radius:12px; padding:10px 14px;}
.pa-next {color:#27500A; font-size:0.92rem;}
.st-key-pa_card [class*="st-key-pa_addrow_"] {position:relative;}
.st-key-pa_card [class*="st-key-pa_addrow_"] [class*="st-key-pa_tick_"] {position:absolute; right:5px; top:5px;
  width:34px; z-index:3;}
.st-key-pa_card [class*="st-key-pa_addrow_"]:has(input:placeholder-shown) [class*="st-key-pa_tick_"] {display:none;}
.st-key-pa_card [class*="st-key-pa_tick_"] button {background:#1F6B4A; border-color:#1F6B4A; color:#fff;
  font-weight:800; min-height:30px; height:30px; width:34px; padding:0; border-radius:8px;}
.st-key-pa_card [class*="st-key-pa_addrow_"] input {text-align:left; font-weight:600; padding-right:46px;}
.st-key-pa_card [class*="st-key-pa_addrow_"] [data-testid="InputInstructions"] {display:none;}
.pa-lh {font-size:0.85rem; font-weight:800; color:#475569; text-align:center;}
.pa-line {font-size:1rem; color:#0F172A; padding:4px 2px;}
.st-key-pa_added [data-baseweb="select"] > div, .st-key-pa_added [data-testid="stNumberInputContainer"] {
  border:2px solid #EF9F27 !important; border-radius:10px; background:#FFFBF2 !important;}
.st-key-pa_added [data-baseweb="select"] div, .st-key-pa_added input {text-align:center; justify-content:center;
  font-weight:800; font-size:1rem;}
.st-key-pa_added button[data-testid="stNumberInputStepUp"],
.st-key-pa_added button[data-testid="stNumberInputStepDown"] {display:none;}
.pa-ex {background:#F4F8FE; color:#0C447C; border:1px solid #B5D4F4; border-radius:10px; padding:6px 12px;
  font-weight:800; margin:10px 0 4px 0; display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px;}
.pa-ex span {font-weight:700; font-size:0.8rem; color:#185FA5;}
.st-key-pa_card [class*="_go"] button {background:#1F6B4A; border-color:#1F6B4A; color:#fff; font-weight:800;}
.st-key-pa_card [data-testid="stWidgetLabel"] {justify-content:center; width:100%;}
.st-key-pa_card [data-testid="stWidgetLabel"] p {font-size:0.88rem; font-weight:700; color:#475569; text-align:center;}
.st-key-pa_card [data-baseweb="select"] > div, .st-key-pa_card [data-testid="stNumberInputContainer"],
.st-key-pa_card [data-testid="stTextInputRootElement"] {border:2px solid #85B7EB; border-radius:12px; background:#fff;}
.st-key-pa_card [data-baseweb="select"] div, .st-key-pa_card input {text-align:center; justify-content:center;
  font-weight:700; font-size:1.05rem;}
.st-key-pa_card button[data-testid="stNumberInputStepUp"],
.st-key-pa_card button[data-testid="stNumberInputStepDown"] {display:none;}
.st-key-pa_card [class*="st-key-pa_box_"] [data-testid="stNumberInputContainer"] {border-color:#378ADD;}
.pa-l {font-size:0.88rem; font-weight:700; color:#475569; text-align:center; margin-bottom:4px;}
.pa-ro {height:42px; border-radius:12px; background:#E6F1FB; display:flex; align-items:center; justify-content:center;
  gap:6px; font-weight:800; color:#0C447C; cursor:not-allowed;}
.pa-ro small {font-size:0.72rem; color:#185FA5; font-weight:700;}
.pa-ro.miss {background:#FCEBEB; color:#791F1F;}
.pa-foot {display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-top:8px;}
.pa-todo {background:#FAEEDA; color:#633806; border-radius:999px; padding:4px 12px; font-size:0.9rem; font-weight:700;}
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


def _add_row(key: str, hint: str, on_tick, args: tuple) -> None:
    """A visible 'add' box with a tick next to it: type the name, press the tick, it is added and chosen."""
    # 27 Nov (user): the tick sits INSIDE the box and shows only once something is typed; Enter saves too
    with st.container(key=f"pa_addrow_{key}"):
        st.text_input(hint, key=f"{key}_new", placeholder=hint, label_visibility="collapsed",
                      on_change=on_tick, args=args)
        with st.container(key=f"pa_tick_{key}"):
            st.button("✓", key=f"{key}_tick", on_click=on_tick, args=args, help="Save this name")


def _add_brand(key: str) -> None:
    """＋ Add brand name: choose the typed brand (it joins the brand list of this SKU on Save)."""
    name = " ".join(str(st.session_state.get(f"{key}_new") or "").split())
    if name:
        st.session_state[key] = name
        st.session_state[f"{key}_new"] = ""


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


def _fk() -> str:
    """Key of the fruit row; it changes after every Add so the row comes back with nothing chosen."""
    return f"pa_parent_{st.session_state.get('pa_fruit_n', 0)}"


def _pending() -> list[dict]:
    return st.session_state.setdefault("pa_rows", [])


def _preview_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Fruit": r["parent_sku"], "Origin": r["origin"], "Variety": r["variety"],
                          "Brand name": r["brand"], "Spec": r["size"], "Box kg": r["box_kg"], "Pcs/box": r["pcs_per_box"] or "",
                          "Executive": r.get("executive", ""), "Table": r["table_no"],
                          "Number of boxes": r["boxes_moved"], "Stock": r["stock_type"],
                          "Kg on table": round(float(r["box_kg"]) * float(r["boxes_moved"]), 2)} for r in rows])


@st.dialog("Save these entries?", width="large")
def _confirm(rows: list[dict], user: User, nxt: str = "") -> None:
    st.dataframe(common.numbered(_preview_df(rows)).rename(columns={"#": "No"}), hide_index=True,
                 width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pa_ok"):
        try:
            n = pa.save(get_backend(), [{k: v for k, v in r.items() if k not in ("added_at", "rid")} for r in rows], user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pa_rows"] = []
        st.session_state.pop("pa_just", None)
        common.flash("success", f"{n} entr{'y' if n == 1 else 'ies'} saved.")
        if nxt and nxt in common.PAGES:        # Save / Proceed for production
            st.switch_page(common.PAGES[nxt])
        st.rerun()
    if c2.button("Back", width="stretch", key="pa_back"):
        st.rerun()


def _line_name(r: dict) -> str:
    bits = [r.get("parent_sku", ""), r.get("variety", ""), r.get("size", ""), r.get("executive", ""),
            f"table {r.get('table_no', '')}", f"{pa._num(r.get('boxes_moved')) or 0:g} boxes"]
    return " · ".join(str(b) for b in bits if str(b).strip())


def _added(rows: list[dict]) -> None:
    """27 Nov (user): the added lines, per executive, with the table number and the number of boxes
    editable right on the line (amber boxes) and a ✕ to take the line out. Nothing else to open."""
    last = _last_times(rows, "executive", "added_at")
    names = list(dict.fromkeys(str(r.get("executive") or "").strip() for r in rows))
    with st.container(key="pa_added"):
        for name in names:
            mine = [r for r in rows if str(r.get("executive") or "").strip() == name]
            boxes = sum(pa._num(r.get("boxes_moved")) or 0 for r in mine)
            at = _clock(last.get(name, ""))
            st.markdown(f"<div class='pa-ex'>{name}<span>{'Last given ' + at + ' · ' if at else ''}{len(mine)} SKU"
                        f"{'' if len(mine) == 1 else 's'} · {boxes:g} boxes</span></div>", unsafe_allow_html=True)
            h = st.columns([4.2, 1.3, 1.3, 0.6])
            h[0].markdown("<div class='pa-lh' style='text-align:left'>Fruit taken</div>", unsafe_allow_html=True)
            h[1].markdown("<div class='pa-lh'>Table number ✎</div>", unsafe_allow_html=True)
            h[2].markdown("<div class='pa-lh'>Number of boxes ✎</div>", unsafe_allow_html=True)
            for n, r in enumerate(mine, start=1):
                rid = r.setdefault("rid", uuid.uuid4().hex[:8])
                c = st.columns([4.2, 1.3, 1.3, 0.6], vertical_alignment="center")
                what = " · ".join(str(x) for x in (r.get("parent_sku"), r.get("origin"), r.get("variety"),
                                                   r.get("brand"), r.get("size"),
                                                   f"{pa._num(r.get('box_kg')) or 0:g} kg box") if x)
                c[0].markdown(f"<div class='pa-line'><b>{n}.</b> {what}</div>", unsafe_allow_html=True)
                t0 = str(r.get("table_no") or "")
                t = c[1].selectbox("Table number", TABLES, index=TABLES.index(t0) if t0 in TABLES else None,
                                   key=f"pa_rt_{rid}", label_visibility="collapsed")
                b = c[2].number_input("Number of boxes", min_value=0.0, step=1.0, format="%g",
                                      value=float(pa._num(r.get("boxes_moved")) or 0), key=f"pa_rb_{rid}",
                                      label_visibility="collapsed")
                if t and t != t0:
                    r["table_no"] = t
                if b and b != (pa._num(r.get("boxes_moved")) or 0):
                    r["boxes_moved"] = b
                if not b:                 # an item cannot be 0: delete it or edit it
                    z = st.columns([3, 1.2, 1.2], vertical_alignment="center")
                    z[0].error(f"Line {n}: boxes cannot be 0. Delete the item or edit it?")
                    if z[1].button("🗑 Delete the item", key=f"pa_rz_{rid}", width="stretch"):
                        rows.remove(r)
                        st.rerun()
                    if z[2].button("✎ Edit the item", key=f"pa_re_{rid}", width="stretch"):
                        st.session_state.pop(f"pa_rb_{rid}", None)      # back to the last number
                        st.rerun()
                if c[3].button("✕", key=f"pa_rx_{rid}", help="Remove this line", width="stretch"):
                    rows.remove(r)
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
        n, t = str(r.get(name_key) or "").strip() or "Name not recorded (older entry)", str(r.get(time_key) or "")
        if t and t > out.get(n, ""):
            out[n] = t
    return out


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
        st.session_state.pop(_fk(), None)
    just = st.session_state.get("pa_just")
    if just and ready and _pending() and not st.session_state.get(_fk()):
        # 27 Nov (user): after Add it must be obvious what comes next
        with st.container(key="pa_next"):
            b1, b2 = st.columns([3, 1.3], vertical_alignment="center")
            b1.markdown(f"<div class='pa-next'>✓ Added: {just}<br><b>Next: pick the next fruit below</b>, "
                        "or save and go to production.</div>", unsafe_allow_html=True)
            if b2.button("Save / Proceed for production", icon=":material/arrow_forward:", key="pa_go_top",
                         type="primary", width="stretch"):
                _confirm(_pending(), user, nxt)
    elif st.session_state.get(_fk()):
        st.session_state.pop("pa_just", None)
    parent = st.pills("Pick the next fruit from inventory" if just and _pending() else "Fruit picked from inventory",
                      parents, key=_fk(), disabled=not ready)
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
        _added(rows)
        if st.button("Save", type="primary", icon=":material/save:", key="pa_save"):
            _confirm(rows, user)

    if ready:
        _saved_today(saved, city, day, exec_tab, user)


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
            brand = _typed("Brand name", b_opts, f"{k}_b", "Choose")
            _add_row(f"{k}_b", "＋ Add brand name", _add_brand, (f"{k}_b",))

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
            _add_row(ek, "＋ Add name", _add_name, (city, ek))
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
                _pending().append({**entry, "added_at": config.now_iso(), "rid": uuid.uuid4().hex[:8]})
                for x in (f"{k}_n", f"{k}_t"):
                    st.session_state.pop(x, None)
                # a fresh fruit row for the next SKU (a new key, so no fruit stays highlighted)
                st.session_state["pa_fruit_n"] = st.session_state.get("pa_fruit_n", 0) + 1
                st.session_state["pa_top"] = True
                st.session_state["pa_just"] = _line_name(entry)
                st.rerun()
        # 27 Nov (user): save here itself and go on to production (a filled card is included)
        if f3.button("Save / Proceed for production", icon=":material/arrow_forward:", key=f"{k}_go",
                     width="stretch"):
            todo = _pending() + ([] if missing else [entry])
            if not todo:
                st.toast("Nothing to save yet. Still to fill: " + ", ".join(missing), icon="⚠️")
            else:
                if not missing:
                    _pending().append({**entry, "added_at": config.now_iso(), "rid": uuid.uuid4().hex[:8]})
                    for x in (f"{k}_n", f"{k}_t"):
                        st.session_state.pop(x, None)
                _confirm(_pending(), user, nxt)


def _saved_today(saved: pd.DataFrame, city: str, day, exec_tab=None, user=None) -> None:
    """27 Nov (user): ONE table, 'Total Production Items Taken', with the executive name after #.
    Executive name, table and boxes can be corrected right in the table (✎ columns), then Save changes."""
    if saved is None or saved.empty or "production_date" not in saved.columns or "entry_id" not in saved.columns:
        return
    d = saved[(saved["production_date"].astype(str).str[:10] == day.isoformat())
              & (saved["city"].astype(str) == city)]
    if d.empty:
        return
    recs = d.to_dict("records")
    ids = [str(r.get("entry_id") or "") for r in recs]

    def txt(v):
        return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()
    def g(v):
        n = pa._num(v)
        return f"{n:g}" if n else ""
    EX, TB, BX = "Executive name ✎", "Table ✎", "Boxes ✎"
    base = pd.DataFrame({
        "No": [str(i) for i in range(1, len(recs) + 1)],        # text = left aligned (user 27 Nov)
        EX: [txt(r.get("executive")) or None for r in recs],
        "Fruit": [txt(r.get("parent_sku")) for r in recs], "Origin": [txt(r.get("origin")) for r in recs],
        "Variety": [txt(r.get("variety")) for r in recs], "Brand name": [txt(r.get("brand")) for r in recs],
        "Spec": [txt(r.get("size")) for r in recs],
        "Box kg": [g(r.get("box_kg")) for r in recs], "Pcs/box": [g(r.get("pcs_per_box")) for r in recs],
        TB: [txt(r.get("table_no")) or None for r in recs],
        BX: [g(r.get("boxes_moved")) or "0" for r in recs],
        "Stock": [txt(r.get("stock_type")) for r in recs],
        "Given at": [_clock(r.get("saved_at")) for r in recs], "By": [txt(r.get("saved_by")).split("@")[0] for r in recs],
        "Kg on table": [f"{round((pa._num(r.get('box_kg')) or 0) * (pa._num(r.get('boxes_moved')) or 0), 2):g}"
                        for r in recs]})
    st.markdown(f"#### {day.strftime('%d/%b/%y')} - Total Production Items Taken · {len(recs)}")
    names = pa.executives(exec_tab, city)
    names += [n for n in dict.fromkeys(x for x in base[EX] if x) if n.casefold() not in {y.casefold() for y in names}]
    nonce = st.session_state.get("pa_saved_n", 0)
    # 27 Nov (user): the table stays as it was (white cells, its own size); only the HEADER is tinted
    # (theme.dataframeHeaderBackgroundColor in .streamlit/config.toml)
    out = st.data_editor(
        base, hide_index=True, width="stretch", num_rows="fixed", key=f"pa_saved_{day}_{city}_{nonce}",
        disabled=[c for c in base.columns if c not in (EX, TB, BX)],
        column_config={EX: st.column_config.SelectboxColumn(EX, options=names, required=False),
                       TB: st.column_config.SelectboxColumn(TB, options=TABLES, required=True),
                       BX: st.column_config.TextColumn(BX, validate=r"^\s*\d+(\.\d+)?\s*$", max_chars=8)})
    st.caption("To correct a saved line, change its **Executive name**, **Table** or **Boxes** in the table "
               "(the ✎ columns), then press Save changes. A new name is added with ＋ Add name in the card above.")
    changes, bad, zero, notes = {}, [], {}, []
    for k, eid in enumerate(ids):
        ch, what = {}, []
        if (out[EX].iloc[k] or "") != (base[EX].iloc[k] or ""):
            ch["executive"] = out[EX].iloc[k] or ""
            what.append(f"Executive {base[EX].iloc[k] or '—'} → {ch['executive'] or '—'}")
        if (out[TB].iloc[k] or "") != (base[TB].iloc[k] or ""):
            ch["table_no"] = out[TB].iloc[k] or ""
            what.append(f"Table {base[TB].iloc[k] or '—'} → {ch['table_no'] or '—'}")
        b = pa._num(out[BX].iloc[k]) or 0
        b0 = pa._num(base[BX].iloc[k]) or 0
        if b != b0:
            ch["boxes_moved"] = b
            what.append(f"Boxes {b0:g} → {b:g}")
        if not ch:
            continue
        name = f"No {k + 1} · " + " · ".join(x for x in (base["Fruit"].iloc[k], base["Variety"].iloc[k],
                                                          base["Spec"].iloc[k]) if x)
        if not eid or not out[TB].iloc[k]:
            bad.append(k + 1)
        elif not b:                      # an item cannot be 0: delete it or go back and edit it
            zero[eid] = name
        else:
            changes[eid] = ch
            notes.append(f"**{name}**: " + ", ".join(what))
    if changes or bad or zero:
        c = st.columns([1.2, 1, 3], vertical_alignment="center")
        if bad:
            c[2].warning(f"No {', '.join(map(str, bad))}: the table cannot be empty.")
        if c[0].button(f"Save changes · {len(changes) + len(zero)}", type="primary", icon=":material/save:",
                       key="pa_saved_ok", disabled=bool(bad) or not (changes or zero), width="stretch"):
            _sure(changes, notes, zero, getattr(user, "email", ""), nonce)
        if c[1].button("Undo", key="pa_saved_undo", width="stretch"):
            st.session_state["pa_saved_n"] = nonce + 1
            st.rerun()


@st.dialog("Are you sure?")
def _sure(changes: dict, notes: list[str], zero: dict, email: str, nonce: int) -> None:
    """27 Nov (user): every correction of a saved line is confirmed; a line set to 0 boxes is either
    deleted entirely or taken back to be edited — it never stays at 0."""
    if zero:
        st.error("Boxes cannot be 0. Delete the item, or go back and edit it.")
        for name in zero.values():
            st.markdown(f"- **{name}**: boxes changed to 0")
    if notes:
        st.markdown("These lines will be changed:" if not zero else "Also changed:")
        for n in notes:
            st.markdown(f"- {n}")

    def apply(delete: bool) -> None:
        try:
            backend = get_backend()
            n = pa.update_entries(backend, changes, email) if changes else 0
            d = pa.delete_entries(backend, list(zero)) if delete and zero else 0
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pa_saved_n"] = nonce + 1
        common.flash("success", " · ".join(x for x in (f"{n} line(s) changed" if n else "",
                                                        f"{d} item(s) deleted" if d else "") if x) or "Nothing changed.")
        st.rerun()
    c1, c2 = st.columns(2)
    if zero:
        if c1.button("🗑 Delete the item" + ("s" if len(zero) > 1 else ""), type="primary", width="stretch",
                     key="pa_sure_del"):
            apply(True)
        if c2.button("✎ Edit the item" + ("s" if len(zero) > 1 else ""), width="stretch", key="pa_sure_edit"):
            st.rerun()          # back to the table: the number is still there to correct
    else:
        if c1.button("Yes, change", type="primary", width="stretch", key="pa_sure_yes"):
            apply(False)
        if c2.button("Back", width="stretch", key="pa_sure_back"):
            st.rerun()
