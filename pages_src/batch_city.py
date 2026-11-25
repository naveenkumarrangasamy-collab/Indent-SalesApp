"""City-level Batching plan + Actual dispatch (25 Nov; owners only, trial). Logic: core/batch_city.py.
Replaces the per-customer Batching plan / Dispatch pages in the menu (their code stays in
preprod_actual.py / dispatch.py)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import batch_city as bc
from core import config, dispatch, preprod
from core import preprod_city as pc
from core.auth import User
from core.models import fmt_num
from core.schema import CITY_GRADING, DISPATCH_LINES, DISPATCH_LOCKS
from core.sheets import SheetError, get_backend
from pages_src import common
from pages_src import preprod_city as pcp

CSS = """<style>
[class*="st-key-bcnum"] [data-testid="stNumberInputContainer"]{border:1px solid #EF9F27 !important;background:#FFFCF5 !important;border-radius:8px}
[class*="st-key-bcnum"] [data-testid="stNumberInputContainer"] *{background-color:transparent !important}
[class*="st-key-bcnum"] [data-testid="stNumberInputStepUp"],[class*="st-key-bcnum"] [data-testid="stNumberInputStepDown"]{display:none}
[class*="st-key-bcnum"] input{text-align:right}
.bc-h{font-size:.75rem;color:#6B6F7B;font-weight:600}
.bc-ro{font-size:.85rem;color:#6B6F7B;padding-top:.45rem}
.bc-v{font-size:.88rem;padding-top:.45rem}
.bc-chip{font-size:.75rem;padding:.1rem .6rem;border-radius:10px;white-space:nowrap}
.bc-ok{background:#EAF3DE;color:#27500A}.bc-warn{background:#FAEEDA;color:#633806}.bc-bad{background:#FCEBEB;color:#791F1F}
.bc-neu{background:#EEF0F4;color:#444}
.bc-pool{font-size:.8rem;background:#E6F1FB;color:#0C447C;border-radius:6px;padding:.15rem .55rem;display:inline-block;margin:0 .3rem .3rem 0}
.bc-pool.neg{background:#FCEBEB;color:#791F1F}
.bc-tot{font-size:.85rem;font-weight:600;padding-top:.3rem}
.bc-note{font-size:.8rem;color:#6B6F7B}
</style>"""
GCHIP = {"Graded": "bc-ok", "Part graded": "bc-warn", "Not graded": "bc-bad", "Over": "bc-bad"}


def _chip(kind: str, text: str) -> str:
    return f"<span class='bc-chip bc-{kind}'>{text}</span>"


def _n(v) -> str:
    return "–" if v is None else fmt_num(round(v, 2))


def _ctx(user: User, prefix: str, title: str, text: str):
    common.show_flash()
    st.markdown(f"### {title}")
    st.caption("Owners only (trial). " + text)
    if not user.is_owner:
        st.error("This page is for owners only for now.")
        return None
    st.markdown(CSS, unsafe_allow_html=True)
    ctx = pcp._load(user, prefix)
    if ctx is None:
        return None
    day, lines, m, data, parent_df = ctx
    city = pcp._pick_city(lines, f"{prefix}_city_{day}")
    city_lines = lines[lines["city"] == city]
    rows = pcp.city_rows(city_lines, day, m)
    try:
        bdata = bc.read_all()
    except SheetError as e:
        common.sheet_error(e)
        return None
    return day, city, city_lines, rows, data, parent_df, bdata


def _opts(parent_df):
    cache: dict = {}

    def f(r):
        if r["key"] not in cache:
            o = pc.options(parent_df, r["parent"], r["variety"])
            cache[r["key"]] = o or [{"label": f"{r['parent']} · any", "country": "", "grade": "", "count": "",
                                     "box_kg": None}]
        return cache[r["key"]]
    return f


def _unit(u: str) -> str:
    return pcp._unit(u)


# ------------------------------------------------------------------ Batching plan

def render_plan(user: User) -> None:
    ctx = _ctx(user, "bcp", "Batching plan",
               "Every customer of the city clubbed, like Pre-production actual. For each lot taken out, type what "
               "grading gave: **MT** (for the customers), **GT** and **Dump**. Change it any time; the last save "
               "counts.")
    if ctx is None:
        return
    day, city, _lines, rows, data, parent_df, bdata = ctx
    took = pc.taken(data[preprod.PREPROD_ACTUAL], day, city)
    if not took:
        st.info(f"Nothing taken out yet for {city} on this date. Save a take-out on Pre-production actual first.")
        return
    _plan_body(user, day, city, rows, took, parent_df, bdata)


@st.fragment
def _plan_body(user, day, city, rows, took, parent_df, bdata) -> None:
    saved = bc.grading(bdata[CITY_GRADING], day, city)
    opts_for = _opts(parent_df)
    tot = bc.fruit_totals(rows, took, opts_for, saved)
    used = bc.mt_used(bdata[DISPATCH_LINES], day, city)
    c = st.columns(5)
    c[0].metric("Boxes / trays taken", fmt_num(sum(v["boxes"] for v in tot.values())))
    c[1].metric("Rows graded", f"{sum(1 for r in rows if took.get(r['key']) and bc.grade_status(bc.grade_rows(r, took[r['key']], opts_for(r), saved)) == 'Graded')} of {sum(1 for r in rows if took.get(r['key']))}")
    c[2].metric("MT", fmt_num(round(sum(v["mt"] for v in tot.values()), 1)))
    c[3].metric("GT", fmt_num(round(sum(v["gt"] for v in tot.values()), 1)))
    c[4].metric("Dump", fmt_num(round(sum(v["dump"] for v in tot.values()), 1)))
    nonce = st.session_state.get("bcp_nonce", 0)
    last_parent = None
    widths = [2.6, 0.8, 1.1, 1.1, 1.1, 1.1, 1]
    for i, r in enumerate(rows):
        mine = took.get(r["key"])
        if not mine:
            continue
        if r["parent"] != last_parent:
            st.markdown(f"#### {r['parent']}")
            last_parent = r["parent"]
        unit = _unit(r["unit"])
        word = pc.box_word(r["parent"])
        lines = bc.grade_rows(r, mine, opts_for(r), saved)
        with st.container(border=True):
            head = st.empty()
            for col, h in zip(st.columns(widths), ["Taken (pre-production)", f"{word}s", f"Fruit ({unit})",
                                                   "MT", "GT", "Dump", "Left"]):
                col.markdown(f"<div class='bc-h'>{h}</div>", unsafe_allow_html=True)
            typed = []
            for j, x in enumerate(lines):
                cc = st.columns(widths, vertical_alignment="center")
                cc[0].markdown(f"<div class='bc-v'>{x['option']}</div>", unsafe_allow_html=True)
                cc[1].markdown(f"<div class='bc-ro'>{fmt_num(x['boxes'])}</div>", unsafe_allow_html=True)
                cc[2].markdown(f"<div class='bc-ro'>{_n(x['fruit'])}</div>", unsafe_allow_html=True)
                vals = []
                for k, (col, f) in enumerate(zip(cc[3:6], ("mt", "gt", "dump"))):
                    with col.container(key=f"bcnum_{i}_{j}_{k}_{nonce}"):
                        v = st.number_input(f"{f} {x['option']}", min_value=0.0, step=1.0,
                                            value=None if x[f] is None else float(x[f]),
                                            key=f"bcp_{nonce}_{day}_{city}_{i}_{j}_{f}", placeholder="0",
                                            label_visibility="collapsed")
                    vals.append(v)
                lf = bc.left(x["fruit"], *vals)
                colour = "#A32D2D" if lf is not None and lf < -1e-9 else "#6B6F7B"
                cc[6].markdown(f"<div class='bc-ro' style='color:{colour}'>{_n(lf)}</div>", unsafe_allow_html=True)
                typed.append({**x, "mt": vals[0], "gt": vals[1], "dump": vals[2], "left": lf,
                              "graded": any(v is not None for v in vals)})
            stt = bc.grade_status(typed)
            mt = sum(x["mt"] or 0 for x in typed)
            fruit = sum(x["fruit"] or 0 for x in typed) if all(x["fruit"] is not None for x in typed) else None
            gap = round(mt - r["need"], 1)
            head.markdown(
                f"<div class='pc-top' style='display:flex;justify-content:space-between'><div><b>{r['parent']}"
                f"{' · ' + r['variety'] if r['variety'] else ''}</b> <span class='bc-note'>· need "
                f"{fmt_num(round(r['need'], 1))} {unit} · fruit in {word.lower()}s {_n(fruit)}</span></div>"
                f"{_chip(GCHIP.get(stt, 'bc-neu').replace('bc-', ''), stt)}</div>", unsafe_allow_html=True)
            sent = used.get(r["key"], 0.0)
            st.markdown(f"<div class='bc-note'>MT {fmt_num(round(mt, 1))} vs need {fmt_num(round(r['need'], 1))} → "
                        f"{'+' if gap >= 0 else ''}{fmt_num(gap)} · dispatched {fmt_num(round(sent, 1))} · "
                        f"MT left {fmt_num(round(mt - sent, 1))}</div>", unsafe_allow_html=True)
            changed = [x for x, y in zip(typed, lines) if (x["mt"], x["gt"], x["dump"]) != (y["mt"], y["gt"], y["dump"])]
            if st.button("Save grading", key=f"bcp_save_{nonce}_{i}", type="primary" if changed else "secondary",
                         disabled=not changed or stt == "Over", icon=":material/save:",
                         help="More typed than the boxes hold" if stt == "Over" else None):
                try:
                    bc.save_grading(get_backend(), day, city, r, typed, user.email)
                except SheetError as e:
                    st.error(f"Not saved. {e}")
                    return
                st.session_state["bcp_nonce"] = nonce + 1
                common.flash("success", f"Grading saved for {r['parent']}{' · ' + r['variety'] if r['variety'] else ''}.")
                st.rerun()
    _day_check(rows, tot, used)


def _day_check(rows, tot, used) -> None:
    st.markdown("##### End of day check")
    out = bc.day_check(rows, tot, used)
    df = pd.DataFrame([{"Fruit": x["parent"] + (f" · {x['variety']}" if x["variety"] else ""),
                        "Unit": _unit(x["unit"]), "Need": fmt_num(round(x["need"], 1)),
                        "Boxes": fmt_num(x["boxes"]), "Fruit taken": _n(x["fruit"]), "MT": _n(x["mt"]),
                        "GT": _n(x["gt"]), "Dump": _n(x["dump"]), "Not graded": _n(x["not_graded"]),
                        "Dispatched": _n(x["dispatched"]), "MT left": _n(x["mt_left"]),
                        "Check": "✓ balanced" if x["ok"] else "; ".join(x["notes"])} for x in out])
    if df.empty:
        return

    def colour(row):
        bad = row["Check"] != "✓ balanced"
        return ["background-color:#FCEBEB" if bad else ""] * len(row)
    st.dataframe(common.numbered(df).style.apply(colour, axis=1), hide_index=True, width="stretch")
    st.caption("Fruit taken = MT + GT + Dump (+ not graded). MT = dispatched + MT left. Red = does not balance.")


# ------------------------------------------------------------------ Actual dispatch

def render_dispatch(user: User) -> None:
    ctx = _ctx(user, "bcd", "Actual dispatch",
               "Per customer + delivery point: type what is sent, in the SKU's own unit. It comes out of the MT "
               "stock of the Batching plan. Saving makes the Delivery Order and **locks** it.")
    if ctx is None:
        return
    day, city, lines, rows, data, parent_df, bdata = ctx
    from pages_src.production import _po_quantities
    po_qty, po_ids, extras = _po_quantities(lines)
    by_ind = bc.indent_lines(lines, po_qty, po_ids, [e for e in extras if e["day"] == day], pcp._ask_variety)
    if not by_ind:
        st.info("No items to dispatch for this date and city.")
        return
    took = pc.taken(data[preprod.PREPROD_ACTUAL], day, city)
    saved = bc.grading(bdata[CITY_GRADING], day, city)
    tot = bc.fruit_totals(rows, took, _opts(parent_df), saved)
    _dispatch_body(user, day, city, by_ind, rows, tot, bdata)


@st.fragment
def _dispatch_body(user, day, city, by_ind, rows, tot, bdata) -> None:
    unlocked = bc.locks(bdata[DISPATCH_LOCKS])
    states = {iid: bc.dispatch_state(bdata[DISPATCH_LINES], unlocked, iid) for iid in by_ind}
    names = {r["key"]: r["parent"] + (f" · {r['variety']}" if r["variety"] else "") for r in rows}
    units = {r["key"]: _unit(r["unit"]) for r in rows}
    used_all = bc.mt_used(bdata[DISPATCH_LINES], day, city)
    pool = " ".join(
        f"<span class='bc-pool{' neg' if v['mt'] - used_all.get(k, 0) < -1e-9 else ''}'>MT {names.get(k, k)} left "
        f"{fmt_num(round(v['mt'] - used_all.get(k, 0), 1))} of {fmt_num(round(v['mt'], 1))} {units.get(k, '')}</span>"
        if v["mt"] else f"<span class='bc-pool neg'>MT {names.get(k, k)} not graded</span>"
        for k, v in tot.items() if v["boxes"] or used_all.get(k))
    if pool:
        st.markdown(pool, unsafe_allow_html=True)
    labels = {}
    for iid, d in by_ind.items():
        s = states[iid]
        tag = "🔒 Dispatched" if s and s["locked"] else ("Unlocked" if s else "Not dispatched")
        labels[f"{d['customer']} · {d['store']} · {iid} · {tag}"] = iid
    pick = st.pills("Customer · delivery point", list(labels), default=list(labels)[0],
                    key=f"bcd_pick_{day}_{city}") or list(labels)[0]
    iid = labels[pick]
    _card(user, day, city, iid, by_ind[iid], states[iid], tot, bdata)
    st.divider()
    _day_check(rows, tot, used_all)


def _card(user, day, city, iid, d, s, tot, bdata) -> None:
    pct = bc.extra_pct(d["customer"])
    others = bc.mt_used(bdata[DISPATCH_LINES], day, city, skip=iid)
    locked = bool(s) and s["locked"]
    items = s.get("items", {}) if s else {}
    st.markdown(f"#### {d['customer']} · {d['store']} · {iid}")
    if locked:
        st.success(f"🔒 Dispatched as **{s['doc_no']}** at {s['at'][11:16] or s['at']} by {s['by']}.")
    elif s:
        st.warning(f"Unlocked: {s['doc_no']} is still counted until a new dispatch replaces it.")
    widths = [0.35, 2.8, 1, 1.2, 1.4, 1.1, 1.8]
    for col, h in zip(st.columns(widths), ["#", "Customer SKU", "Asked", "Dispatch", "Unit", "= from MT", "Status"]):
        col.markdown(f"<div class='bc-h'>{h}</div>", unsafe_allow_html=True)
    nonce = st.session_state.get("bcd_nonce", 0)
    base = f"bcd_{nonce}_{day}_{iid}"
    extra_ok = st.session_state.get(f"{base}_extra", False)
    out, bad, over_mt, typed_mt = [], [], [], {}
    for i, x in enumerate(d["lines"]):
        old = items.get(x["name"].casefold(), {}).get("dispatch_qty")
        start = float(old) if old not in (None, "") else float(x["asked"])
        c = st.columns(widths, vertical_alignment="center")
        c[0].markdown(f"<div class='bc-ro'>{i + 1}</div>", unsafe_allow_html=True)
        c[1].markdown(f"<div class='bc-v'>{x['name']}{' <i>(PO only)</i>' if x['po_only'] else ''}</div>",
                      unsafe_allow_html=True)
        c[2].markdown(f"<div class='bc-ro'>{fmt_num(x['asked'])}</div>", unsafe_allow_html=True)
        if locked:
            q = start
            c[3].markdown(f"<div class='bc-v'><b>{fmt_num(q)}</b></div>", unsafe_allow_html=True)
        else:
            with c[3].container(key=f"bcnum_d_{i}_{nonce}"):
                q = st.number_input(f"Dispatch {x['name']}", min_value=0.0, step=1.0, value=start,
                                    key=f"{base}_{i}", label_visibility="collapsed")
        c[4].markdown(f"<div class='bc-ro'>{x['word']}</div>", unsafe_allow_html=True)
        mt = round((q or 0) * x["per"], 3)
        typed_mt[x["key"]] = typed_mt.get(x["key"], 0.0) + mt
        c[5].markdown(f"<div class='bc-ro'>{fmt_num(mt)} {_unit(x['unit'])}</div>", unsafe_allow_html=True)
        kind, label = bc.check(x["asked"], q, pct, extra_ok)
        c[6].markdown(_chip(kind, label), unsafe_allow_html=True)
        if kind == "bad":
            bad.append(x["name"])
        out.append({"customer_sku_name": x["name"], "lot": x["lot"], "indent_qty": x["indent_qty"],
                    "dispatch_qty": q or 0, "price": x["price"], "reason": "", "club_key": x["key"],
                    "per": x["per"], "from_mt": mt, "unit": x["unit"]})
    for k, v in typed_mt.items():
        have = tot.get(k, {}).get("mt", 0.0) - others.get(k, 0.0)
        if v > have + 1e-9:
            over_mt.append(f"{k.split('|')[0]}: {fmt_num(round(v, 1))} from MT, {fmt_num(round(max(have, 0), 1))} left")
    if locked:
        _locked_tools(user, iid, d, s)
        return
    if over_mt:
        st.warning("More than the MT stock left (allowed; shows red on the end of day check): " + "; ".join(over_mt))
    st.checkbox(f"Send extra (up to {fmt_num(pct)} % over what was asked)", key=f"{base}_extra")
    c = st.columns([1.3, 1.6, 1, 2.2], vertical_alignment="bottom")
    vehicle = c[0].text_input("Vehicle no.", value=s.get("vehicle", "") if s else "", key=f"{base}_veh")
    driver = c[1].text_input("Driver · phone", value=s.get("driver", "") if s else "", key=f"{base}_drv")
    at = c[2].text_input("Time", value=config.now_ist().strftime("%H:%M"), key=f"{base}_at")
    with c[3].popover("Dispatch · lock", icon=":material/lock:", width="stretch", disabled=bool(bad)):
        st.markdown(f"**Dispatch {d['customer']} · {d['store']} and lock it?** It can't be changed after this "
                    "(an owner can unlock).")
        if st.button("Yes, dispatch", type="primary", icon=":material/local_shipping:", key=f"{base}_go"):
            head = {"indent_id": iid, "delivery_date": day, "city": city, "customer": d["customer"],
                    "store": d["store"], "vehicle": vehicle.strip(), "driver": driver.strip(),
                    "dispatched_at": f"{day} {at.strip()}"}
            try:
                doc = dispatch.save_dispatch(get_backend(), head, out, user.email)
            except SheetError as e:
                st.error(f"Not saved. {e}")
                return
            st.session_state["bcd_nonce"] = nonce + 1
            common.flash("success", f"Dispatched and locked. Delivery Order {doc}.")
            st.rerun()
    if bad:
        st.caption("Fix the red lines first: over the limit, or tick **Send extra**.")


def _locked_tools(user, iid, d, s) -> None:
    rows = list(s["items"].values())
    head = {"doc_no": s["doc_no"], "indent_id": iid, "po": "", "delivery_date": rows[0].get("delivery_date", ""),
            "customer": d["customer"], "store": d["store"], "city": d["city"], "vehicle": s.get("vehicle", ""),
            "driver": s.get("driver", ""), "dispatched_at": s["at"]}
    c = st.columns([2, 2, 3])
    c[0].download_button(f"Delivery Order {s['doc_no']}", lambda: dispatch.delivery_order_pdf(head, rows),
                         file_name=f"{s['doc_no']}.pdf", mime="application/pdf", icon=":material/download:",
                         key=f"bcd_pdf_{iid}", on_click="ignore")
    with c[1].popover("Unlock", icon=":material/lock_open:"):
        why = st.text_input("Why?", key=f"bcd_why_{iid}", placeholder="Wrong qty typed …")
        if st.button("Yes, unlock", key=f"bcd_unl_{iid}", disabled=not why.strip()):
            try:
                bc.save_unlock(get_backend(), iid, s["doc_no"], why.strip(), user.email)
            except SheetError as e:
                st.error(f"Not saved. {e}")
                return
            common.flash("success", f"{iid} unlocked. Dispatch again to replace {s['doc_no']}.")
            st.rerun()
