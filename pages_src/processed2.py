"""Production Detail Process (27 Nov, trial; was 'Processed · option 2'): by grading executive, + its tracking.

Only tables still in process are listed (folded; tap to open). Inside a table, per item: MT Ready per customer
lot, then left-over / GT / dump once for the item, a sum check (97-102 %), Save draft and Submit. A submitted
item leaves the list (Done today; owners can reopen). Logic: core/processed2.py."""
from __future__ import annotations

import hashlib
import uuid

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core import prod_actual as pa
from core import processed as pr
from core import processed2 as p2
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common

PICK = "Choose…"
LABEL = {"mt_packs": "MT Ready (Cux lots) D1", "mt_loose_kg": "MT Ready (loose kg) D2",
         "left_box": "Vendor lots E1", "left_kg": "Loose kg E2", "left_pcs": "Loose pcs E3",
         "gt_box": "Box F1", "gt_kg": "Loose kg F2", "gt_pcs": "Loose pcs F3",
         "dump_kg": "Dump kg G1", "dump_pcs": "Dump pcs G2"}
PCS_FIELDS = {"left_pcs", "gt_pcs", "dump_pcs"}
SUM_COL = {"empty": ("#F1F5F9", "#64748B"), "low": ("#FAEEDA", "#633806"), "ok": ("#EAF3DE", "#27500A"),
           "over": ("#FCEBEB", "#791F1F")}

CSS = """<style>
.p2-hd {font-size:1.08rem; background:#F4F8FE; border:2px solid #85B7EB; border-radius:12px; padding:8px 12px; color:#0C447C;
  font-weight:800; display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; margin-bottom:10px;}
.p2-hd span {background:#fff; border:1px solid #B5D4F4; border-radius:999px; padding:2px 10px; font-size:0.88rem;}
[class*="st-key-p2t_"] {background:#fff; border:2px solid #E2E8F0; border-radius:14px; padding:12px 16px 14px 16px;
  margin-bottom:8px;}
[class*="st-key-p2t_"] [data-testid="stMarkdownContainer"] {margin-bottom:0;}
[class*="st-key-p2t_"] [data-testid="stMarkdownContainer"] p {margin-bottom:0;}
[class*="st-key-p2t_on_"] {border-color:#3B82F6;}
.p2-tn {font-weight:800; font-size:1.25rem; color:#000; line-height:1.35;}
.p2-tx {font-size:0.9rem; color:#475569; line-height:1.55; margin-top:2px;}
.p2-var {background:#F3E8FF; color:#6B21A8; border-radius:999px; padding:1px 8px; font-weight:700;}
.p2-st {border-radius:999px; padding:3px 10px; font-size:0.86rem; font-weight:800; display:inline-block;}
[class*="st-key-p2i_"] {background:#fff; border:1px solid #E2E8F0; border-radius:12px; padding:10px;
  margin:0 0 10px 0;}
[class*="st-key-p2mt_"] {background:#F4F8FE; border:2px solid #BFDBFE; border-radius:12px; padding:10px;}
[class*="st-key-p2tb_"] {background:#F8FAFC; border:2px solid #E2E8F0; border-radius:12px; padding:10px;}
.p2-chip {display:inline-block; border-radius:6px; padding:2px 10px; color:#fff; font-size:0.86rem;
  font-weight:800; margin-bottom:4px;}
.p2-no {background:#334155; color:#fff; border-radius:8px; height:38px; display:flex; align-items:center;
  justify-content:center; font-weight:800; margin-top:26px;}
.p2-l {font-size:0.8rem; font-weight:700; color:#475569; text-align:center; margin-bottom:4px; height:1.3em;}
.p2-k {height:40px; border-radius:10px; display:flex; align-items:center; justify-content:center;
  font-weight:800; background:#EFF6FF; color:#1E3A8A;}
.p2-sub {font-size:0.86rem; font-weight:800; margin:6px 0 0 0;}
[class*="st-key-p2i_"] [data-testid="stWidgetLabel"] {justify-content:center; width:100%%;}
[class*="st-key-p2i_"] [data-testid="stWidgetLabel"] p {font-size:0.8rem; font-weight:700; color:#475569;
  text-align:center;}
[class*="st-key-p2i_"] input {text-align:center; font-weight:800;}
[class*="st-key-p2i_"] [data-testid="stNumberInputContainer"],
[class*="st-key-p2i_"] [data-testid="stTextInputRootElement"] {border:2px solid #CBD5E1; border-radius:10px;
  background:#fff;}
[class*="st-key-p2i_"] [data-baseweb="select"] > div {border:2px solid #93C5FD; border-radius:10px;
  font-weight:800; background:#fff;}
[class*="st-key-p2i_"] button[data-testid="stNumberInputStepUp"],
[class*="st-key-p2i_"] button[data-testid="stNumberInputStepDown"] {display:none;}
[class*="st-key-p2add_"] button {border:2px dashed #85B7EB; background:#F4F8FE; color:#185FA5; font-weight:800;}
.p2-sum {border-radius:12px; padding:8px 12px; margin:8px 0; font-size:0.9rem; font-weight:800;}
.p2-sum > div {display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;}
.p2-bar {height:8px; border-radius:999px; background:#E2E8F0; overflow:hidden; margin:5px 0;}
.p2-bar div {height:100%%;}
.p2-view {border:1px solid #BFDBFE; border-radius:10px; overflow:hidden; margin:6px 0 4px 0; font-size:0.8rem;}
.p2-vh {background:#F4F8FE; color:#0C447C; font-weight:800; padding:5px 10px; display:flex;
  justify-content:space-between; flex-wrap:wrap; gap:6px;}
.p2-vh span:last-child {border-radius:999px; padding:1px 10px;}
.p2-view table {width:100%%; border-collapse:collapse;}
.p2-view th {background:#fff; color:#475569; font-size:0.72rem; padding:4px 6px; text-align:center;
  border-bottom:1px solid #E2E8F0;}
.p2-view td {padding:4px 6px; text-align:center; font-weight:700; color:#000; border-bottom:1px solid #F1F5F9;}
.p2-vt td {background:#EFF6FF; color:#1E3A8A; font-weight:800;}
.p2-vf {display:flex; gap:14px; flex-wrap:wrap; padding:5px 10px; font-weight:800;}
.p2-lock {height:40px; border-radius:10px; display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:0.84rem; background:#F1F5F9; color:#94A3B8; border:1px dashed #CBD5E1;
  cursor:not-allowed;}
.st-key-p2next button {background:#2563EB; border-color:#2563EB; color:#fff; font-weight:800;}
.st-key-p2day button {background:#1F6B4A; border-color:#1F6B4A; color:#fff; font-weight:800;}
.p2-note {border-radius:10px; padding:8px 10px; font-size:0.9rem; font-weight:700; margin-bottom:8px;}
[class*="st-key-p2sub_"] button:not(:disabled) {background:#16A34A; border-color:#15803D; color:#fff;
  font-weight:800;}
@media (max-width: 640px) { [class*="st-key-p2i_"] input {font-size:16px;} .p2-no {margin-top:0;} }
</style>""" % ()


def _iid(day: str, city: str, key: str) -> str:
    return hashlib.md5(f"{day}|{city}|{key}".encode()).hexdigest()[:8]


def _new_line(src: dict | None = None) -> dict:
    src = src or {}
    return {"id": uuid.uuid4().hex[:8], "pack": src.get("pack", ""), "mt_packs": src.get("mt_packs"),
            "mt_loose_kg": src.get("mt_loose_kg")}


def _plain(e: dict) -> dict:
    """What gets compared / saved (no widget ids)."""
    return {"lines": [(ln["pack"], pr._f(ln.get("mt_packs")), pr._f(ln.get("mt_loose_kg")))
                      for ln in e["lines"] if ln["pack"]],
            "tbl": {f: pr._f(e["tbl"].get(f)) for f in p2.TABLE_FIELDS}, "comment": e["comment"].strip()}


def _store(day: str, city: str, its: dict, saved: dict) -> dict:
    """Session copy of every item (values survive while a table is folded)."""
    box = st.session_state.setdefault("p2_data", {}).setdefault(f"{day}|{city}", {})
    for key in its:
        if key in box:
            continue
        s = saved.get(f"{day}|{city}|{key}")
        e = {"lines": [_new_line(p2.clean_line(x)) for x in (s["lines"] if s else [])] or [_new_line()],
             "tbl": dict(s["tbl"]) if s else {f: None for f in p2.TABLE_FIELDS},
             "comment": s["comment"] if s else "", "status": s["status"] if s else "new"}
        e["saved"] = _plain(e) if s else None
        box[key] = e
    return box


def _sync(box: dict, day: str, city: str) -> None:
    ss = st.session_state
    for key, e in box.items():
        iid = _iid(day, city, key)
        for ln in e["lines"]:
            k = f"p2_{ln['id']}_pack"
            if k in ss:
                ln["pack"] = "" if ss[k] in (None, PICK) else ss[k]
            for f in p2.MT_FIELDS:
                if f"p2_{ln['id']}_{f}" in ss:
                    ln[f] = ss[f"p2_{ln['id']}_{f}"]
        for f in p2.TABLE_FIELDS:
            if f"p2_{iid}_{f}" in ss:
                e["tbl"][f] = ss[f"p2_{iid}_{f}"]
        if f"p2_{iid}_comment" in ss:
            e["comment"] = str(ss[f"p2_{iid}_comment"] or "")


def _seed(k: str, v, kind: str = "num") -> str:
    if k not in st.session_state:
        st.session_state[k] = ((v or PICK) if kind == "pack" else (str(v or "") if kind == "txt"
                               else (None if v in (None, "") else float(v))))
    return k


def _num(label: str, key: str, value, whole: bool = False) -> None:
    """whole=True (27 Nov, user): pieces and packs are whole numbers, never 2.5."""
    if whole:
        if key not in st.session_state or isinstance(st.session_state[key], float):
            v = st.session_state.get(key, value)
            st.session_state[key] = None if v in (None, "") else int(round(float(v)))
        st.number_input(label, min_value=0, step=1, key=key, format="%d", placeholder="0")
        return
    st.number_input(label, min_value=0.0, step=1.0, key=_seed(key, value), format="%g", placeholder="0")


NO_NAME = "Name not recorded"
ALL = "All"


def _name(it: dict) -> str:
    return " · ".join(x for x in [str(it.get("parent_sku", "")), str(it.get("variety", "")),
                                  str(it.get("size", ""))] if x)


def _ex(it: dict) -> str:
    return str(it.get("executive") or "").strip() or NO_NAME


def _clock(stamp) -> str:
    try:
        return pd.to_datetime(str(stamp)).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return ""


def _to_top() -> None:
    if not st.session_state.pop("p2_top", False):
        return
    import streamlit.components.v1 as components
    components.html("<script>const d = window.parent.document;"
                    "['stMain', 'stAppViewContainer'].forEach(t => {const e = d.querySelector"
                    "('[data-testid=\"' + t + '\"]'); if (e) e.scrollTo({top: 0, behavior: 'smooth'});});"
                    "window.parent.scrollTo(0, 0);</script>", height=0)


def render(user: User) -> None:
    """27 Nov (user): 'Production Detail Process', by grading executive. Save just saves, Submit just submits;
    one table at the end to check; only 'Confirm and submit the day' asks and shows the summary."""
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    _to_top()
    st.markdown("### Production Detail Process")
    try:
        m = masters.load_masters()
        lots = pa.read()
        lines = indents.current_rows(indents.read_lines())
        saved_df = p2.read()
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return
    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = common.day_input(top[0], "p2_day").isoformat()
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key="p2_city") or cities[0]
    raw = lots.copy() if lots is not None and not lots.empty else pd.DataFrame()
    if not raw.empty and "production_date" in raw.columns:
        raw = raw[(raw["production_date"].astype(str).str[:10] == day) & (raw["city"].astype(str) == city)]
    its = p2.items(raw)
    if not its:
        st.info("No lots given to executives for this date yet. Add them on **Pre-Production Actual** first.")
        return
    box = _store(day, city, its, p2.latest(saved_df, day, city))
    _body(its, box, lines, day, city, user, p2.day_state(saved_df, day, city))


@st.fragment
def _body(its: dict, box: dict, lines, day: str, city: str, user: User, closed: dict | None) -> None:
    _sync(box, day, city)
    locked = bool(closed) and not user.is_owner
    names = list(dict.fromkeys(_ex(it) for it in its.values()))
    names.sort(key=lambda n: (n == NO_NAME, n.casefold()))
    count = {n: sum(1 for it in its.values() if _ex(it) == n) for n in names}
    if closed:
        st.success(f"This day is confirmed · {closed['by']} · {_clock(closed['at'])}."
                   + (" Owners can still correct it." if user.is_owner else " Nothing can be changed."))
    opts = [ALL] + names
    go = st.session_state.pop("p2_ex_go", None)        # set by 'Save and next executive'
    if go in opts:
        st.session_state["p2_ex"] = go
    if st.session_state.get("p2_ex") not in opts:
        st.session_state["p2_ex"] = ALL
    pick = st.pills("Executive", opts, key="p2_ex",
                    format_func=lambda n: f"{n} · {len(its) if n == ALL else count[n]}") or ALL
    shown = names if pick == ALL else [pick]
    cur = st.session_state.get("p2_open")
    for name in shown:
        keys = [k for k, it in its.items() if _ex(it) == name]
        done = sum(1 for k in keys if box[k]["status"] == "submitted")
        boxes = sum(pr._f(its[k]["boxes_moved"]) for k in keys)
        at = _clock(max((its[k].get("last_at", "") for k in keys), default=""))
        st.markdown(f"<div class='p2-hd'>{name}<span>{'Last given ' + at + ' · ' if at else ''}{len(keys)} SKU"
                    f"{'' if len(keys) == 1 else 's'} · {boxes:g} boxes · {done} of {len(keys)} submitted</span>"
                    "</div>", unsafe_allow_html=True)
        for k in keys:
            it, e = its[k], box[k]
            is_open = cur == k
            started = bool(_plain(e)["lines"] or any(_plain(e)["tbl"].values()))
            if e["status"] == "submitted":
                stt, col = "Submitted", "background:#EAF3DE;color:#27500A"
            elif started:
                stt, col = "In process", "background:#FAEEDA;color:#633806"
            else:
                stt, col = "Not started", "background:#F1F5F9;color:#475569"
            with st.container(key=f"p2t_{'on' if is_open else 'off'}_{_iid(day, city, k)}"):
                c = st.columns([4, 1.4, 1], vertical_alignment="center")
                c[0].markdown(f"<div class='p2-tn'>Table {it['table_no']} · {_name(it)}</div><div class='p2-tx'>"
                              f"Taken: {_taken(it)}{_short(it, e)}</div>", unsafe_allow_html=True)
                c[1].markdown(f"<span class='p2-st' style='{col}'>{stt}</span>", unsafe_allow_html=True)
                word = "▲ Close" if is_open else ("✎ Edit" if e["status"] == "submitted" else "▼ Open")
                if c[2].button(word, key=f"p2_tog_{_iid(day, city, k)}", width="stretch", disabled=locked):
                    st.session_state["p2_open"] = None if is_open else k
                    st.rerun(scope="fragment")
            if is_open and not locked:
                _item(it, e, lines, day, city, user)
    if pick != ALL and not locked:
        nxt = names[(names.index(pick) + 1) % len(names)] if len(names) > 1 else ""
        c = st.columns([2, 1.6])
        with c[1].container(key="p2next"):
            if st.button(f"Save and next executive: {nxt} →" if nxt else "Save", key="p2_next", width="stretch"):
                _save_all([k for k, it in its.items() if _ex(it) == pick], its, box, day, city, user)
                if nxt:
                    st.session_state["p2_ex_go"] = nxt
                    st.session_state["p2_open"] = None
                    st.session_state["p2_top"] = True
                st.rerun()
    _entered(its, box, day)
    _day_end(its, box, day, city, user, closed)


def _taken(it: dict) -> str:
    unit = "trays" if pa.box_only(it.get("parent_sku", "")) else "boxes"
    pcs = f" · {it['taken_pcs']:,.0f} pcs" if it.get("taken_pcs") else ""
    return f"{pr._f(it['boxes_moved']):g} {unit} · {it['taken_kg']:,.1f} kg{pcs}"


def _short(it: dict, e: dict) -> str:
    """One line of what is SAVED for a folded item."""
    sv = e.get("saved")
    if not sv or not (sv["lines"] or any(sv["tbl"].values())):
        return ""
    lines = [{"pack": p, "mt_packs": n, "mt_loose_kg": kg} for p, n, kg in sv["lines"]]
    t = p2.total(it, lines, sv["tbl"])
    return (f"<br><b>Saved:</b> MT {t['mt_kg']:,.1f} · left over {t['left_kg']:,.1f} · GT {t['gt_kg']:,.1f} · "
            f"Dump {t['dump_kg']:,.1f} kg · sum {pr.pct(t['sum'])}")


def _locked(col, label: str, text: str) -> None:
    col.markdown(f"<div class='p2-l'>{label}</div><div class='p2-lock' title='{text}'>🔒 {text}</div>",
                 unsafe_allow_html=True)


def _item(it: dict, e: dict, lines, day: str, city: str, user: User) -> None:
    iid = _iid(day, city, it["key"])
    t = p2.total(it, e["lines"], e["tbl"])
    piece = bool(t["x"])
    packs = pr.lot_choices(str(it.get("parent_sku", "")), piece,
                           list(pr.packs_for(lines, str(it.get("parent_sku", "")), day, city)))
    with st.container(key=f"p2i_{iid}"):
        extra = " · ".join(x for x in [str(it.get("origin") or ""), f"brand {it['brand']}" if it.get("brand") else "",
                                       f"{pr._f(it['box_kg']):g} kg box",
                                       f"{pr._f(it.get('pcs_per_box')):g} pcs" if piece else ""] if x)
        st.markdown(f"<div class='p2-tx'>{extra}</div>", unsafe_allow_html=True)
        with st.container(key=f"p2mt_{iid}"):
            st.markdown("<span class='p2-chip' style='background:#2563EB'>1 · MT Ready by customer lot</span>",
                        unsafe_allow_html=True)
            used = {ln["pack"] for ln in e["lines"] if ln["pack"]}
            for n, (ln, kg) in enumerate(zip(e["lines"], t["mt_per_line"]), 1):
                c = st.columns([0.4, 1.1, 1.4, 1.4, 1.1, 0.5])
                c[0].markdown(f"<div class='p2-no'>{n}</div>", unsafe_allow_html=True)
                opts = [PICK] + [p for p in packs if p == ln["pack"] or p not in used]
                if ln["pack"] and ln["pack"] not in opts:
                    opts.append(ln["pack"])
                k = _seed(f"p2_{ln['id']}_pack", ln["pack"], "pack")
                if st.session_state.get(k) not in opts:
                    st.session_state[k] = PICK
                c[1].selectbox("Customer lot", opts, key=k)
                # 27 Nov (user): a piece lot is typed ONLY in packs, a kg lot ONLY in kg (this line only;
                # left over, GT and dump keep every box)
                unit = p2.lot_unit(ln["pack"])
                if unit in ("PC", "Pack"):
                    with c[2]:
                        _num(LABEL["mt_packs"], f"p2_{ln['id']}_mt_packs", ln.get("mt_packs"), whole=True)
                    _locked(c[3], "MT Ready (kg)", "Not for pieces" if unit == "PC" else "Packs only")
                    _drop(ln, "mt_loose_kg")
                elif unit == "Kg":
                    _locked(c[2], "MT Ready (packs)", "Not for kg")
                    _drop(ln, "mt_packs")
                    with c[3]:
                        _num("MT Ready (kg)", f"p2_{ln['id']}_mt_loose_kg", ln.get("mt_loose_kg"))
                else:
                    _locked(c[2], "MT Ready (packs)", "Choose the lot")
                    _locked(c[3], "MT Ready (kg)", "Choose the lot")
                c[4].markdown(f"<div class='p2-l'>MT kg</div><div class='p2-k'>{kg:,.1f} kg</div>",
                              unsafe_allow_html=True)
                if len(e["lines"]) > 1:
                    c[5].markdown("<div class='p2-l'>&nbsp;</div>", unsafe_allow_html=True)
                    if c[5].button("✕", key=f"p2_{ln['id']}_rm", help="Remove this customer lot"):
                        e["lines"].remove(ln)
                        st.rerun(scope="fragment")
            ready = all(ln["pack"] for ln in e["lines"])
            with st.container(key=f"p2add_{iid}"):
                if st.button("＋ Add customer lot", key=f"p2_{iid}_add", width="stretch", disabled=not ready,
                             help=None if ready else "Pick the customer lot above first"):
                    e["lines"].append(_new_line())
                    st.rerun(scope="fragment")
        with st.container(key=f"p2tb_{iid}"):
            st.markdown("<span class='p2-chip' style='background:#475569'>2 · For the whole table (once)</span>",
                        unsafe_allow_html=True)
            for title, colr, fields in [("Left over MT Ready · back to stock", "#1E3A8A",
                                         ["left_box", "left_kg", "left_pcs"]),
                                        ("GT Stock", "#9F1239", ["gt_box", "gt_kg", "gt_pcs"]),
                                        ("Dump", "#5B21B6", ["dump_kg", "dump_pcs"])]:
                st.markdown(f"<div class='p2-sub' style='color:{colr}'>{title}</div>", unsafe_allow_html=True)
                cols = st.columns(3)
                for col, f in zip(cols, fields):
                    if f in PCS_FIELDS and not piece:
                        continue
                    with col:
                        _num(LABEL[f], f"p2_{iid}_{f}", e["tbl"].get(f), whole=f in PCS_FIELDS)
        st.text_input("Comments (optional)", key=_seed(f"p2_{iid}_comment", e["comment"], "txt"),
                      placeholder="Type a note")
        state = p2.state_of(t)
        bg, fg = SUM_COL[state]
        pct = 0 if t["sum"] is None else max(0.0, min(t["sum"], 1.0)) * 100
        st.markdown(f"<div class='p2-sum' style='background:{bg};color:{fg}'><div><span>Table {it['table_no']} sum "
                    f"check · (MT + GT + Dump) ÷ used</span><span>{t['out_kg']:,.1f} of {t['used_kg']:,.1f} kg · "
                    f"{pr.pct(t['sum']) if state != 'empty' else '–'}</span></div><div class='p2-bar'><div "
                    f"style='width:{pct:.0f}%;background:{fg}'></div></div><div style='font-weight:600'><span>"
                    f"Efficiency (all customer lots) {pr.pct(t['efficiency']) if state != 'empty' else '–'}</span>"
                    f"<span>MT {t['mt_kg']:,.1f} · GT {t['gt_kg']:,.1f} · Dump {t['dump_kg']:,.1f} · left over "
                    f"{t['left_kg']:,.1f} kg</span></div></div>", unsafe_allow_html=True)
        if state == "over":
            st.markdown(f"<div class='p2-note' style='background:#FCEBEB;color:#791F1F'>Can't save or submit · "
                        f"{pr.pct(t['sum'])} of the kg used. It can't be more than 102%. Check MT / GT / Dump."
                        "</div>", unsafe_allow_html=True)
        elif state == "low":
            st.markdown(f"<div class='p2-note' style='background:#FAEEDA;color:#633806'>{t['to_go']:,.1f} kg not "
                        "accounted yet (target 97–102%).</div>", unsafe_allow_html=True)
        # never disabled and no pop-up: Save just saves, Submit just submits (user 27 Nov)
        c = st.columns([1, 2])
        if c[0].button("Save", key=f"p2_{iid}_save", width="stretch"):
            _write(it, e, "draft", day, city, user, state)
        with c[1].container(key=f"p2sub_{iid}"):
            if st.button("✓ Submit", key=f"p2_{iid}_submit", width="stretch"):
                _write(it, e, "submitted", day, city, user, state)


def _drop(ln: dict, field: str) -> None:
    """Empty the MT box that is locked for this lot type (and its widget value)."""
    ln[field] = None
    st.session_state.pop(f"p2_{ln['id']}_{field}", None)


def _write(it: dict, e: dict, status: str, day: str, city: str, user: User, state: str) -> None:
    if state == "over":
        st.toast("Not saved: more than 102% of the kg used.", icon="⚠️")
        return
    if state == "empty":
        st.toast("Nothing entered yet.", icon="⚠️")
        return
    rows = p2.snapshot(it, e["lines"], e["tbl"], e["comment"], status, day, city, user.email)
    try:
        p2.save(get_backend(), rows)
    except SheetError as err:
        st.error(f"Not saved. {err}")
        return
    e["status"] = status
    e["saved"] = _plain(e)
    if status == "submitted":
        st.session_state["p2_open"] = None
    common.flash("success", f"Table {it['table_no']} · {_name(it)} {'submitted' if status == 'submitted' else 'saved'}.")
    st.rerun()


def _save_all(keys: list[str], its: dict, box: dict, day: str, city: str, user: User,
              submit: bool = False) -> int:
    """Save every changed item of these keys in one write (their status is kept unless `submit`)."""
    rows, done = [], []
    for k in keys:
        it, e = its[k], box[k]
        state = p2.state_of(p2.total(it, e["lines"], e["tbl"]))
        if state in ("over", "empty"):
            continue
        status = "submitted" if submit or e["status"] == "submitted" else "draft"
        if e["saved"] == _plain(e) and e["status"] == status:
            continue
        rows += p2.snapshot(it, e["lines"], e["tbl"], e["comment"], status, day, city, user.email)
        done.append((e, status))
    if rows:
        try:
            p2.save(get_backend(), rows)
        except SheetError as err:
            st.error(f"Not saved. {err}")
            return 0
        for e, status in done:
            e["status"] = status
            e["saved"] = _plain(e)
        common.flash("success", f"{len(done)} item(s) saved.")
    return len(done)


def _entered_df(its: dict, box: dict) -> pd.DataFrame:
    rows = []
    for n, (k, it) in enumerate(its.items(), 1):
        e = box[k]
        sv = e.get("saved")
        base = {"No": str(n), "Executive": _ex(it), "Table": it["table_no"], "Fruit": it.get("parent_sku", ""),
                "Variety": it.get("variety", ""), "Spec size": it.get("size", ""),
                "Boxes": f"{pr._f(it['boxes_moved']):g}"}
        if sv and (sv["lines"] or any(sv["tbl"].values())):
            ls = [{"pack": p, "mt_packs": a, "mt_loose_kg": b} for p, a, b in sv["lines"]]
            t = p2.total(it, ls, sv["tbl"])
            rows.append({**base, "Customer lots": ", ".join(x["pack"] for x in ls), "MT kg": f"{t['mt_kg']:,.1f}",
                         "Left over kg": f"{t['left_kg']:,.1f}", "GT kg": f"{t['gt_kg']:,.1f}",
                         "Dump kg": f"{t['dump_kg']:,.1f}", "Sum": pr.pct(t["sum"]),
                         "Efficiency": pr.pct(t["efficiency"]),
                         "Status": "Submitted" if e["status"] == "submitted" else "Saved"})
        else:
            rows.append({**base, "Customer lots": "", "MT kg": "", "Left over kg": "", "GT kg": "", "Dump kg": "",
                         "Sum": "", "Efficiency": "", "Status": "Not started"})
    return pd.DataFrame(rows)


def _entered(its: dict, box: dict, day: str) -> None:
    """The one table at the end of the page to check what was saved (everyone)."""
    df = _entered_df(its, box)
    st.markdown(f"#### {day[8:]}/{pd.to_datetime(day).strftime('%b')}/{day[2:4]} - Production Detail Entered · "
                f"{len(df)}")
    tint = {"Submitted": "#EAF3DE", "Saved": "#FAEEDA"}
    st.dataframe(df.style.map(lambda v: f"background-color:{tint[v]}" if v in tint else "", subset=["Status"]),
                 hide_index=True, width="stretch")


def _day_end(its: dict, box: dict, day: str, city: str, user: User, closed: dict | None) -> None:
    df = _entered_df(its, box)
    sub, not_started = int((df["Status"] == "Submitted").sum()), int((df["Status"] == "Not started").sum())
    if closed:
        if user.is_owner and st.button("Reopen the day", key="p2_reopen"):
            try:
                p2.save(get_backend(), p2.close_rows(day, city, user.email, "open"))
            except SheetError as err:
                st.error(f"Not saved. {err}")
                return
            st.rerun()
        return
    c = st.columns([2, 1.6])
    c[0].caption(f"{sub} of {len(df)} submitted · {not_started} not started.")
    with c[1].container(key="p2day"):
        if st.button("🔒 Confirm and submit the day", key="p2_day_btn", width="stretch"):
            _day_confirm(its, box, day, city, user)


@st.dialog("Confirm and submit the day?", width="large")
def _day_confirm(its: dict, box: dict, day: str, city: str, user: User) -> None:
    """The only pop-up on this page: the day's summary, then one confirm."""
    df = _entered_df(its, box)
    n_sub, n_saved = int((df["Status"] == "Submitted").sum()), int((df["Status"] == "Saved").sum())
    n_none = int((df["Status"] == "Not started").sum())
    c = st.columns(3)
    c[0].metric("Submitted", f"{n_sub} of {len(df)}")
    c[1].metric("Saved, not submitted", n_saved)
    c[2].metric("Not started", n_none)
    st.dataframe(df, hide_index=True, width="stretch")
    if n_saved:
        st.info(f"{n_saved} saved item(s) will be submitted with the day.")
    if n_none:
        st.warning(f"{n_none} item(s) are not started. They stay empty when the day is confirmed.")
    b = st.columns(2)
    if b[0].button("Yes, confirm the day", type="primary", width="stretch", key="p2_day_ok"):
        _save_all(list(its), its, box, day, city, user, submit=True)
        try:
            p2.save(get_backend(), p2.close_rows(day, city, user.email))
        except SheetError as err:
            st.error(f"Not saved. {err}")
            return
        common.flash("success", "The day is confirmed.")
        st.rerun()
    if b[1].button("Back", width="stretch", key="p2_day_back"):
        st.rerun()


BAND = {"green": "#EAF3DE", "amber": "#FAEEDA", "yellow": "#FFF6C2", "red": "#FCEBEB"}


def render_tracking(user: User) -> None:
    """27 Nov (user): 'Production Summary' with two views: the Production tracker (as before) and Category
    efficiency (fruit + variety + country + brand, counts clubbed). One date, or a date range."""
    common.show_flash()
    st.markdown("### Production Summary")
    try:
        m = masters.load_masters()
        lots = pa.read()
        saved = p2.read()
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return
    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 0.9, 1, 3])
    d1 = common.day_input(top[0], "t2_day")
    ranged = top[1].toggle("Date range", key="t2_range", help="Add a second date to see a week, a month ...")
    d2 = top[2].date_input("To", value=d1, min_value=d1, key="t2_to", format="DD/MM/YYYY") if ranged else d1
    if d2 < d1:
        d2 = d1
    days = {d.date().isoformat() for d in pd.date_range(d1, d2)}
    label = d1.isoformat() if d1 == d2 else f"{d1.isoformat()}_to_{d2.isoformat()}"
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[3]:
            city = st.pills("City", cities, default=cities[0], key="t2_city") or cities[0]
    t_track, t_cat = st.tabs(["Production tracker", "Category efficiency"])
    with t_track:
        _tracker(lots, saved, days, city, label)
    with t_cat:
        _category(lots, saved, days, city, label)


def _category(lots, saved, days: set[str], city: str, label: str) -> None:
    rows, tot = p2.category_rows(lots, saved, days, city)
    if not rows:
        st.info("Nothing was given to executives for this date yet. Start on **Pre-Production Actual**.")
        return

    def pc(v):
        return "–" if v is None else f"{round(v * 100)}%"
    c = st.columns(5)
    c[0].metric("Kg used (J)", f"{tot['j']:,.0f}")
    c[1].metric("Category efficiency (K / J)", pc(tot["efficiency"]))
    c[2].metric("GT created (L / J)", pc(tot["gt"]))
    c[3].metric("Dump (M / J)", pc(tot["dump"]))
    c[4].metric("Lotting loss (+ loss / − gain)", f"{tot['lot']:+,.1f} kg" if tot["j"] else "–",
                None if tot["lotting"] is None else f"{tot['lotting'] * 100:+.1f}% of kg used", delta_color="off")
    if tot["saved"] or tot["none"]:
        st.caption(" · ".join(x for x in (
            f"**{tot['saved']}** item(s) are saved but not submitted yet; they are counted in these percentages"
            if tot["saved"] else "",
            f"**{tot['none']}** item(s) are not started; they are not counted" if tot["none"] else "") if x) + ".")
    pcts = ["Category Efficiency % (K / J)", "GT Created % (L / J)", "Dump % (M / J)"]
    signed = {p2.LOT_KG: "{:+,.2f}", p2.LOT_PCT: "{:+.1%}"}
    df = pd.DataFrame(rows, columns=p2.CAT_HEAD).astype(object)   # object: an empty % stays None, not NaN
    df = df.where(df.notna(), None)
    band = [p2.eff_band(v) for v in df[pcts[0]]]
    show = df.copy()
    for col in ("Boxes", "Kg taken", "Kg used (J)", "MT kg (K)", "GT kg (L)", "Dump kg (M)"):
        show[col] = [f"{float(v):,.1f}".rstrip("0").rstrip(".") if v else "" for v in df[col]]
    for col in pcts:
        show[col] = ["" if v is None else f"{round(float(v) * 100)}%" for v in df[col]]
    for col, fmt in signed.items():
        show[col] = ["" if v is None else fmt.format(float(v) + 0.0) for v in df[col]]
    show.insert(0, "No", [str(i) for i in range(1, len(show) + 1)])

    def paint(col):
        return [f"background-color:{BAND[b]}" if b else "" for b in band]
    st.dataframe(show.style.apply(paint, subset=[pcts[0]]), hide_index=True, width="stretch")
    st.caption("One row per fruit + variety + country + brand; every count, table and day in the range is added "
               "together. Green 90% and above · amber 80–90% · yellow 70–80% · red below 70%.")
    st.download_button("CSV", data=show.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"Category_Efficiency_{label}.csv", mime="text/csv",
                       icon=":material/download:", key="t2_cat_csv")


def _tracker(lots, saved, days: set[str], city: str, label: str) -> None:
    df = pd.DataFrame(p2.track_rows(lots, saved), columns=p2.TRACK_HEAD)
    if not df.empty:
        df = df[(df["City"] == city) & df["Production Date"].isin(days)]
    if df.empty:
        st.info("Nothing on the tables for this date yet. Start on **Pre-Production Actual**.")
        return
    tot = df[df["Cux Lot"].isin(["Table total", ""])]
    used = tot["Actual NW used for Production Kgs (J = H - I)"].map(pr._f).sum()
    mt = tot["MT Ready in Kgs (K)"].map(pr._f).sum()
    c = st.columns(5)
    c[0].metric("Items on tables", len(tot))
    c[1].metric("Submitted", int((tot["Status"] == "Submitted").sum()))
    c[2].metric("In process", int((tot["Status"] == "In process").sum()))
    c[3].metric("Not started", int((tot["Status"] == "Not started").sum()))
    c[4].metric("Efficiency", f"{round(mt / used * 100)}%" if used else "–")

    def _eff(v):
        n = pr._f(str(v).replace("%", "")) / 100 if str(v).endswith("%") else None
        b = p2.eff_band(n)
        return f"background-color:{BAND[b]}" if b else ""

    def _sum(v):
        n = pr._f(str(v).replace("%", "")) / 100 if str(v).endswith("%") else None
        return "" if n is None else "background-color:" + pr.sum_colour(n)[0]

    def _st(v):
        return "background-color:" + {"Submitted": "#EAF3DE", "In process": "#FAEEDA"}.get(v, "#F1F5F9")
    shown = df.map(lambda v: f"{v:g}" if isinstance(v, float) else v)
    st.dataframe(shown.style.map(_eff, subset=["Category Efficiency% (K / J)"])
                 .map(_sum, subset=["Sum check (K+L+M) / J"]).map(_st, subset=["Status"]),
                 hide_index=True, width="stretch")
    st.caption("One row per customer lot (its MT) + one **Table total** row (left-over, GT, dump). Also in the "
               "**Production_Tracking_2** tab of the Google Sheet (rewritten after every save).")
    b = st.columns([1, 1, 4])
    b[0].download_button("CSV", data=df.to_csv(index=False).encode("utf-8-sig"),
                         file_name=f"Production_Tracking_2_{label}.csv", mime="text/csv",
                         icon=":material/download:", width="stretch", key="t2_csv")
    if b[1].button("Update sheet tab", icon=":material/sync:", width="stretch", key="t2_pub"):
        n = p2.publish(get_backend())
        st.success(f"{n} row(s) written.") if n >= 0 else st.error("Could not write the tab.")
