"""Option 2 (26 Nov, trial): Processed table by table + its Production Tracking.

Only tables still in process are listed (folded; tap to open). Inside a table, per item: MT Ready per customer
lot, then left-over / GT / dump once for the item, a sum check (97-101 %), Save draft and Submit. A submitted
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
DEFAULT_PACKS = ["1PC", "2PC", "3PC", "4PC", "1Kg"]
LABEL = {"mt_packs": "MT Ready (Cux lots) D1", "mt_loose_kg": "MT Ready (loose kg) D2",
         "left_box": "Vendor lots E1", "left_kg": "Loose kg E2", "left_pcs": "Loose pcs E3",
         "gt_box": "Box F1", "gt_kg": "Loose kg F2", "gt_pcs": "Loose pcs F3",
         "dump_kg": "Dump kg G1", "dump_pcs": "Dump pcs G2"}
PCS_FIELDS = {"left_pcs", "gt_pcs", "dump_pcs"}
SUM_COL = {"empty": ("#F1F5F9", "#64748B"), "low": ("#FAEEDA", "#633806"), "ok": ("#EAF3DE", "#27500A"),
           "over": ("#FCEBEB", "#791F1F")}

CSS = """<style>
.p2-hd {background:#F4F8FE; border:2px solid #85B7EB; border-radius:12px; padding:8px 12px; color:#0C447C;
  font-weight:800; display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px; margin-bottom:10px;}
.p2-hd span {background:#fff; border:1px solid #B5D4F4; border-radius:999px; padding:2px 10px; font-size:0.8rem;}
[class*="st-key-p2t_"] {background:#fff; border:2px solid #E2E8F0; border-radius:14px; padding:8px 12px;
  margin-bottom:8px;}
[class*="st-key-p2t_on_"] {border-color:#3B82F6;}
.p2-tn {font-weight:800; font-size:1.15rem; color:#000;}
.p2-tx {font-size:0.8rem; color:#475569;}
.p2-var {background:#F3E8FF; color:#6B21A8; border-radius:999px; padding:1px 8px; font-weight:700;}
.p2-st {border-radius:999px; padding:3px 10px; font-size:0.78rem; font-weight:800; display:inline-block;}
[class*="st-key-p2i_"] {background:#fff; border:1px solid #E2E8F0; border-radius:12px; padding:10px;
  margin:0 0 10px 0;}
[class*="st-key-p2mt_"] {background:#F4F8FE; border:2px solid #BFDBFE; border-radius:12px; padding:10px;}
[class*="st-key-p2tb_"] {background:#F8FAFC; border:2px solid #E2E8F0; border-radius:12px; padding:10px;}
.p2-chip {display:inline-block; border-radius:6px; padding:2px 10px; color:#fff; font-size:0.78rem;
  font-weight:800; margin-bottom:4px;}
.p2-no {background:#334155; color:#fff; border-radius:8px; height:38px; display:flex; align-items:center;
  justify-content:center; font-weight:800; margin-top:26px;}
.p2-l {font-size:0.72rem; font-weight:700; color:#475569; text-align:center; margin-bottom:4px; height:1.3em;}
.p2-k {height:40px; border-radius:10px; display:flex; align-items:center; justify-content:center;
  font-weight:800; background:#EFF6FF; color:#1E3A8A;}
.p2-sub {font-size:0.76rem; font-weight:800; margin:6px 0 0 0;}
[class*="st-key-p2i_"] [data-testid="stWidgetLabel"] {justify-content:center; width:100%%;}
[class*="st-key-p2i_"] [data-testid="stWidgetLabel"] p {font-size:0.72rem; font-weight:700; color:#475569;
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
.p2-sum {border-radius:12px; padding:8px 12px; margin:8px 0; font-size:0.82rem; font-weight:800;}
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
.p2-note {border-radius:10px; padding:8px 10px; font-size:0.82rem; font-weight:700; margin-bottom:8px;}
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
        e = {"lines": [_new_line(x) for x in (s["lines"] if s else [])] or [_new_line()],
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


def _num(label: str, key: str, value) -> None:
    st.number_input(label, min_value=0.0, step=1.0, key=_seed(key, value), format="%g", placeholder="0")


def _desc(it: dict) -> str:
    v = f" · <span class='p2-var'>{it['variety']}</span>" if it.get("variety") else ""
    unit = "trays" if pa.box_only(it.get("parent_sku", "")) else "boxes"
    pcs = f" · <b>{it['taken_pcs']:,.0f} pcs</b>" if it.get("taken_pcs") else ""
    return (f"{it.get('parent_sku', '')}{v} · {it.get('size', '')} · {pr._f(it['boxes_moved']):g} {unit} · "
            f"{it['taken_kg']:,.1f} kg{pcs}")


def _view(it: dict, e: dict, many: bool = False) -> str:
    """Read-only table of what is SAVED for an item (not what is being typed)."""
    sv = e.get("saved")
    if not sv or not (sv["lines"] or any(sv["tbl"].values())):
        return ""
    lines = [{"pack": p, "mt_packs": n, "mt_loose_kg": kg} for p, n, kg in sv["lines"]]
    t = p2.total(it, lines, sv["tbl"])
    piece = bool(t["x"])
    body, pcs_all = "", 0.0
    for ln, kg in zip(lines, t["mt_per_line"]):
        pcs = p2.line_pcs(ln["pack"], ln["mt_packs"])
        pcs_all += pcs
        body += (f"<tr><td><b>{ln['pack']}</b></td><td>{ln['mt_packs']:g}</td><td>{ln['mt_loose_kg']:g}</td>"
                 f"<td>{kg:,.1f}</td>" + (f"<td>{pcs:,.0f}</td>" if piece else "") + "</tr>")
    body += (f"<tr class='p2-vt'><td>Total MT</td><td></td><td></td><td>{t['mt_kg']:,.1f}</td>"
             + (f"<td>{pcs_all:,.0f}</td>" if piece else "") + "</tr>")
    bg, fg = SUM_COL[p2.state_of(t)]
    word = "Submitted" if e["status"] == "submitted" else "Saved draft"
    taken = f"{pr._f(it['boxes_moved']):g} boxes · {it['taken_kg']:,.1f} kg" + (
        f" · {it['taken_pcs']:,.0f} pcs" if it.get("taken_pcs") else "")
    return (f"<div class='p2-view'><div class='p2-vh'><span>{word}"
            + (f" · {_name(it)}" if many else "") + f" · taken {taken}</span>"
            f"<span style='background:{bg};color:{fg}'>Sum {pr.pct(t['sum'])} · Eff {pr.pct(t['efficiency'])}"
            "</span></div><table><tr><th>Customer lot</th><th>Packs</th><th>Loose kg</th><th>MT kg</th>"
            + ("<th>Pcs</th>" if piece else "") + f"</tr>{body}</table><div class='p2-vf'>"
            f"<span style='color:#1E3A8A'>Left over {t['left_kg']:,.1f} kg</span>"
            f"<span style='color:#9F1239'>GT {t['gt_kg']:,.1f} kg</span>"
            f"<span style='color:#5B21B6'>Dump {t['dump_kg']:,.1f} kg</span>"
            f"<span>Used {t['used_kg']:,.1f} kg</span>"
            + (f"<span>{e['comment']}</span>" if e.get("comment") else "") + "</div></div>")


def _name(it: dict) -> str:
    return " · ".join(x for x in [str(it.get("parent_sku", "")), str(it.get("variety", "")),
                                  str(it.get("size", ""))] if x)


def render(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Processed · option 2")
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
    day = top[0].date_input("Date", value=config.now_ist().date(), key="p2_day", format="DD/MM/YYYY").isoformat()
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key="p2_city") or cities[0]
    raw = lots.copy() if lots is not None and not lots.empty else pd.DataFrame()
    if not raw.empty and "production_date" in raw.columns:
        raw = raw[(raw["production_date"].astype(str).str[:10] == day) & (raw["city"].astype(str) == city)]
    its = p2.items(raw)
    if not its:
        st.info("No lots on tables for this date yet. Add them on **Pre-Production Actual** first.")
        return
    box = _store(day, city, its, p2.latest(saved_df, day, city))
    _body(its, box, lines, day, city, user)


@st.fragment
def _body(its: dict, box: dict, lines, day: str, city: str, user: User) -> None:
    _sync(box, day, city)
    open_keys = [k for k in its if box[k]["status"] != "submitted"]
    done_keys = [k for k in its if box[k]["status"] == "submitted"]
    tables = list(dict.fromkeys(its[k]["table_no"] for k in open_keys))
    st.markdown(f"<div class='p2-hd'>Processed · {city} · {day[8:]}/{day[5:7]}/{day[:4]}<span>Open tables "
                f"{len(tables)} · Done items {len(done_keys)}</span></div>", unsafe_allow_html=True)
    if not tables:
        st.success("Every table of this date is submitted.")
    cur = st.session_state.get("p2_open")
    for t in tables:
        keys = [k for k in open_keys if its[k]["table_no"] == t]
        all_t = [k for k in its if its[k]["table_no"] == t]
        started = any(_plain(box[k])["lines"] or any(_plain(box[k])["tbl"].values()) for k in keys)
        n_done = len(all_t) - len(keys)
        if n_done:
            stt, col = f"{n_done} of {len(all_t)} items done", "background:#FAEEDA;color:#633806"
        elif started:
            stt, col = "In process", "background:#FAEEDA;color:#633806"
        else:
            stt, col = "Not started", "background:#F1F5F9;color:#475569"
        is_open = cur == t
        with st.container(key=f"p2t_{'on' if is_open else 'off'}_{t}"):
            c = st.columns([4, 1.4, 1], vertical_alignment="center")
            c[0].markdown(f"<div class='p2-tn'>Table {t}</div><div class='p2-tx'>"
                          + " &nbsp;|&nbsp; ".join(_desc(its[k]) for k in keys) + "</div>", unsafe_allow_html=True)
            c[1].markdown(f"<span class='p2-st' style='{col}'>{stt}</span>", unsafe_allow_html=True)
            if c[2].button("▲ Close" if is_open else "▼ Open", key=f"p2_tog_{t}", width="stretch"):
                st.session_state["p2_open"] = None if is_open else t
                st.rerun(scope="fragment")
            if not is_open:
                html = "".join(_view(its[k], box[k], many=len(keys) > 1) for k in keys)
                if html:
                    st.markdown(html, unsafe_allow_html=True)
        if is_open:
            for k in keys:
                _item(its[k], box[k], lines, day, city, user, many=len(all_t) > 1)
    if done_keys:
        with st.expander(f"Done today · {len(done_keys)} item(s)", expanded=True):
            for k in done_keys:
                it, e = its[k], box[k]
                t = p2.total(it, e["lines"], e["tbl"])
                c = st.columns([4, 1], vertical_alignment="center")
                c[0].markdown(f"<span class='p2-st' style='background:#EAF3DE;color:#27500A'>Table "
                              f"{it['table_no']} ✓ {_name(it)} · sum {pr.pct(t['sum'])} · eff "
                              f"{pr.pct(t['efficiency'])}</span> <span class='p2-tx'>MT {t['mt_kg']:,.1f} · GT "
                              f"{t['gt_kg']:,.1f} · Dump {t['dump_kg']:,.1f} kg</span>", unsafe_allow_html=True)
                st.markdown(_view(it, e, many=True), unsafe_allow_html=True)
                if user.is_owner and c[1].button("✎ Edit", key=f"p2_re_{_iid(day, city, k)}", width="stretch",
                                                   help="Open this table again to change or add customer lots"):
                    st.session_state["p2_open"] = it["table_no"]
                    _write(it, e, "draft", day, city, user, "opened again for editing")


def _item(it: dict, e: dict, lines, day: str, city: str, user: User, many: bool) -> None:
    iid = _iid(day, city, it["key"])
    t = p2.total(it, e["lines"], e["tbl"])
    piece = bool(t["x"])
    packs = [p for p in pr.packs_for(lines, str(it.get("parent_sku", "")), day, city)]
    packs += [p for p in DEFAULT_PACKS if p not in packs]
    if not piece:
        packs = [p for p in packs if pr.pack_kg(p, None)[0]]
    with st.container(key=f"p2i_{iid}"):
        pcs = f" · <b>{it['taken_pcs']:,.0f}</b> pcs" if it["taken_pcs"] else ""
        extra = " · ".join(x for x in [str(it.get("origin") or ""), f"brand {it['brand']}" if it.get("brand") else "",
                                       f"{pr._f(it['box_kg']):g} kg box",
                                       f"{pr._f(it.get('pcs_per_box')):g} pcs" if piece else ""] if x)
        st.markdown((f"<div class='p2-tn' style='font-size:1rem'>{_name(it)}</div>" if many else "")
                    + f"<div class='p2-tx'>Taken: <b>{pr._f(it['boxes_moved']):g}</b> boxes · "
                    f"<b>{it['taken_kg']:,.1f}</b> kg{pcs} · {extra}</div>", unsafe_allow_html=True)
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
                with c[2]:
                    _num(LABEL["mt_packs"], f"p2_{ln['id']}_mt_packs", ln.get("mt_packs"))
                with c[3]:
                    _num(LABEL["mt_loose_kg"], f"p2_{ln['id']}_mt_loose_kg", ln.get("mt_loose_kg"))
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
                        _num(LABEL[f], f"p2_{iid}_{f}", e["tbl"].get(f))
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
                        f"{pr.pct(t['sum'])} of the kg used. It can't be more than 101%. Check MT / GT / Dump."
                        "</div>", unsafe_allow_html=True)
        elif state == "low":
            st.markdown(f"<div class='p2-note' style='background:#FAEEDA;color:#633806'>{t['to_go']:,.1f} kg not "
                        "accounted yet (target 97–101%).</div>", unsafe_allow_html=True)
        dirty = e["saved"] != _plain(e)
        c = st.columns([1, 2])
        if c[0].button("Save draft", key=f"p2_{iid}_save", width="stretch",
                       disabled=state in ("over", "empty") or not dirty):
            _write(it, e, "draft", day, city, user, "saved")
        with c[1].container(key=f"p2sub_{iid}"):
            if st.button(f"✓ Submit Table {it['table_no']}" + (f" · {_name(it)}" if many else ""),
                         key=f"p2_{iid}_submit", width="stretch", disabled=state in ("over", "empty")):
                _confirm(it, e, t, state, day, city, user)


def _write(it: dict, e: dict, status: str, day: str, city: str, user: User, word: str) -> None:
    rows = p2.snapshot(it, e["lines"], e["tbl"], e["comment"], status, day, city, user.email)
    try:
        p2.save(get_backend(), rows)
    except SheetError as err:
        st.error(f"Not saved. {err}")
        return
    e["status"] = status
    e["saved"] = _plain(e)
    if status == "submitted" and st.session_state.get("p2_open") == it["table_no"]:
        st.session_state["p2_open"] = None
    common.flash("success", f"Table {it['table_no']} · {_name(it)} {word}.")
    st.rerun()


@st.dialog("Submit this table?")
def _confirm(it: dict, e: dict, t: dict, state: str, day: str, city: str, user: User) -> None:
    per = " · ".join(f"{ln['pack']} {kg:,.1f}" for ln, kg in zip(e["lines"], t["mt_per_line"]) if ln["pack"])
    st.markdown(f"**Table {it['table_no']} · {_name(it)}** · {pr._f(it['boxes_moved']):g} boxes  \n"
                f"MT {t['mt_kg']:,.1f} kg ({per or 'none'}) · GT {t['gt_kg']:,.1f} · Dump {t['dump_kg']:,.1f} · "
                f"left over {t['left_kg']:,.1f} kg  \nSum {pr.pct(t['sum'])} · Efficiency {pr.pct(t['efficiency'])}")
    if state == "low":
        st.warning(f"Only {pr.pct(t['sum'])} is accounted · {t['to_go']:,.1f} kg missing. Submit anyway?")
    c = st.columns(2)
    if c[0].button("Yes, submit" if state == "low" else "Submit", type="primary", width="stretch", key="p2_ok"):
        _write(it, e, "submitted", day, city, user, "submitted")
    if c[1].button("Back", width="stretch", key="p2_back"):
        st.rerun()


def render_tracking(user: User) -> None:
    common.show_flash()
    st.markdown("### Production Tracking · option 2")
    try:
        m = masters.load_masters()
        lots = pa.read()
        saved = p2.read()
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return
    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="t2_day", format="DD/MM/YYYY").isoformat()
    all_days = top[1].toggle("All dates", key="t2_all")
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[2]:
            city = st.pills("City", cities, default=cities[0], key="t2_city") or cities[0]
    df = pd.DataFrame(p2.track_rows(lots, saved), columns=p2.TRACK_HEAD)
    if not df.empty:
        df = df[df["City"] == city]
        if not all_days:
            df = df[df["Production Date"] == day]
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
        if n is None:
            return ""
        return "background-color:" + ("#EAF3DE" if n >= 0.9 else "#FAEEDA" if n >= 0.85 else "#FCEBEB")

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
                         file_name=f"Production_Tracking_2_{'all' if all_days else day}.csv", mime="text/csv",
                         icon=":material/download:", width="stretch")
    if b[1].button("Update sheet tab", icon=":material/sync:", width="stretch", key="t2_pub"):
        n = p2.publish(get_backend())
        st.success(f"{n} row(s) written.") if n >= 0 else st.error("Could not write the tab.")
