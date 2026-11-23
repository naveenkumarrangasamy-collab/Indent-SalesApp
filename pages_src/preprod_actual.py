"""Pre-production actual and Batching plan pages (22 Nov; owners only while being tried).
Logic and storage: core/preprod.py. The existing Production / Batching sheets are unchanged."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from core import masters, preprod
from core.auth import User
from core.models import fmt_num
from core.sheets import SheetError, get_backend
from pages_src import common

ICON = {"Enough": "🟢", "Not enough": "🟡", "Not started": "🔴", "Taken": "⚪",
        "Covered": "🟢", "Short": "🟡", "Pending": "🔴", "Over limit": "⛔"}


# ------------------------------------------------------------------ shared

def _context(user: User, prefix: str):
    """Date / city filters (same as the Production sheet), then the day's demand per customer.
    Returns (day, demand, masters, saved tabs) or None (a message was shown)."""
    from pages_src import production
    res = production._filtered(user, prefix)
    if res is None:
        return None
    lines = res[0]
    day = st.session_state.get(f"{prefix}_ctx", (None, production.ALL_DATES))[1]
    if day == production.ALL_DATES:
        st.info("Pick one delivery date.")
        return None
    try:
        m = masters.load_masters()
        data = preprod.read_all()
        from core import mapping_sheet
        data["_mapping"] = mapping_sheet.load()
    except SheetError as e:
        common.sheet_error(e)
        return None
    dem = preprod.demand(lines)
    if dem.empty:
        st.info("No items with a quantity for this date.")
        return None
    return day, dem, m, data


def _groups(dem: pd.DataFrame) -> list[tuple[str, str]]:
    return list(dict.fromkeys(zip(dem["city"], dem["group"])))


def _label(city: str, group: str, many_cities: bool, state: str) -> str:
    return f"{group}{f' ({city})' if many_cities else ''} · {state}"


def _unit_word(unit: str) -> str:
    return {"pcs": "pcs", "kg": "kg", "punnets": "punnets"}.get(unit, "packs")


def _opts(m, data, r) -> dict:
    """Countries for one SKU: the New Mapping sheet first (Combination 1, then its Parent tab),
    else the old masters (Batching_Master / New tab / Mapping Whole)."""
    from core import config, mapping_sheet
    unit = "Tray" if str(r["parent_sku"]).casefold() in {p.casefold() for p in config.tray_parents()} else "Box"
    combos, parent = data.get("_mapping", (None, None)) if mapping_sheet.use_new() else (None, None)
    o = mapping_sheet.options(combos, parent, r["city"], r["customer"], r["customer_sku_name"], r["parent_sku"],
                              r.get("variety", ""), unit)
    if not o:
        o = preprod.country_options(m, data[preprod.BATCHING_MASTER], r["city"], r["customer"],
                                    r["customer_sku_name"], r["parent_sku"])
    return o or {preprod.ANY: {"spec": [], "unit": "Box", "box_kg": None, "source": "none"}}


def _hold(boxes: dict, unit: str, opt: dict) -> float | None:
    total, known = 0.0, True
    for s, n in boxes.items():
        pb = preprod.per_box(s, unit, opt.get("box_kg"))
        if pb is None:
            known = False
        else:
            total += n * pb
    return total if known and boxes else (None if boxes else 0.0)


# ------------------------------------------------------------------ Pre-production actual

def render_actual(user: User) -> None:
    common.show_flash()
    st.markdown("### Pre-production actual")
    st.caption("Owners only (trial). Boxes taken out of storage for each customer, at each count. Save a "
               "take-out as often as needed; **Freeze** the customer when all its stock is out. Frozen "
               "customers move to the **Batching plan**.")
    if not user.is_owner:
        st.error("This page is for owners only for now.")
        return
    ctx = _context(user, "pa")
    if ctx is None:
        return
    day, dem, m, data = ctx
    groups = _groups(dem)
    many = len({c for c, _ in groups}) > 1
    states = {}
    for city, group in groups:
        fr = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, group)[0]
        any_taken = bool(preprod.taken(data[preprod.PREPROD_ACTUAL], day, city, group))
        states[(city, group)] = preprod.FROZEN if fr else preprod.OPEN if any_taken else preprod.NOT_STARTED
    labels = {_label(c, g, many, states[(c, g)]): (c, g) for c, g in groups}
    pick = st.pills("Customer", list(labels), default=list(labels)[0], key=f"pa_grp_{day}") or list(labels)[0]
    city, group = labels[pick]
    _actual_body(user, day, city, group, dem, m, data)


PA_CSS = """<style>
[class*="st-key-pacnt"] [data-testid="stNumberInputStepUp"],[class*="st-key-pacnt"] [data-testid="stNumberInputStepDown"]{display:none}
[class*="st-key-pacnt"] label p{font-weight:600;font-size:.9rem;white-space:nowrap}
[class*="st-key-pacnt_has"] [data-testid="stNumberInputContainer"]{border:2px solid #3D9A6A !important;background:#F2FAF5 !important;border-radius:8px}
[class*="st-key-pacnt_has"] [data-testid="stNumberInputContainer"] *{background-color:transparent !important}
.pa-taken{font-size:.78rem;color:#1E6B3C;margin-top:-.4rem}
</style>"""


def _css(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", v)


@st.fragment
def _actual_body(user: User, day: str, city: str, group: str, dem: pd.DataFrame, m, data) -> None:
    rows = dem[(dem["city"] == city) & (dem["group"] == group)].reset_index(drop=True)
    frozen, f_at, f_by = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, group)
    took = preprod.taken(data[preprod.PREPROD_ACTUAL], day, city, group)
    hist = preprod.rounds(data[preprod.PREPROD_ACTUAL], day, city, group)
    nonce = st.session_state.get("pa_nonce", 0)
    base = f"pa_{nonce}_{day}_{city}_{group}"

    st.markdown(PA_CSS, unsafe_allow_html=True)
    head = f"#### {group} · {city}"
    if frozen:
        st.markdown(head)
        st.success(f"🔒 Frozen by {f_by} at {f_at[11:16] or f_at}. No more take-outs; enter pieces used on the "
                   "Batching plan.")
    else:
        st.markdown(head + f"  \n<span class='mt-muted'>Indents {', '.join(sorted(set(', '.join(rows['indents']).split(', '))))}"
                    f" · {len(hist)} take-out(s) saved</span>", unsafe_allow_html=True)

    entries, n_enough, n_short = [], 0, 0
    for i, r in rows.iterrows():
        key = preprod._k(r["customer_sku_name"])
        t = took.get(key, {"country": "", "boxes": {}})
        opts = _opts(m, data, r)
        unit = r["unit"]
        with st.container(border=True):
            c = st.columns([3.2, 2, 5.2, 1.8])
            c[0].markdown(f"**{i + 1}. {r['customer_sku_name']}**")
            var = f"{r['variety']} · " if r["variety"] else ""
            c[0].caption(f"{var}{fmt_num(r['qty'])} × {fmt_num(r['per'])} = **{fmt_num(r['need'])} "
                         f"{_unit_word(unit)}** needed")
            countries = list(opts)
            fixed = t["country"] if t["boxes"] else ""
            if fixed and fixed not in countries:
                countries = [fixed] + countries
            country = c[1].selectbox("Country", countries, index=countries.index(fixed) if fixed else 0,
                                     key=f"{base}_{i}_cty", disabled=bool(fixed) or frozen,
                                     help="Fixed after the first take-out." if fixed else None)
            opt = opts.get(country, {"spec": [], "unit": "Box", "box_kg": None})
            kg = f" · {fmt_num(opt['box_kg'])} kg {opt['unit'].lower()}" if opt.get("box_kg") else ""
            c[1].caption(f"Suggested: {preprod.suggestion(r['need'], unit, opt)}{kg}")
            if opt.get("source"):
                c[1].caption(f"From: {opt['source']}")
            specs = list(opt["spec"]) + [s for s in t["boxes"] if s not in opt["spec"]]
            if not specs:
                c[2].warning("No counts for this SKU in the master yet (Batching_Master / New / Mapping Whole).")
            per_row = 5
            for start in range(0, len(specs), per_row):
                chunk = specs[start:start + per_row]
                cols = c[2].columns(per_row)
                for j, s in enumerate(chunk):
                    so_far = t["boxes"].get(s, 0)
                    wkey = f"{base}_{i}_{s}"
                    has = bool(st.session_state.get(wkey))
                    with cols[j].container(key=f"pacnt_{'has' if has else 'no'}_{_css(wkey)}"):
                        if frozen:
                            st.metric(preprod.spec_label(s), f"{fmt_num(so_far)} {opt['unit'].lower()}")
                            continue
                        add = st.number_input(preprod.spec_label(s), min_value=0, step=1, value=0, key=wkey,
                                              help="Boxes taken out now (this round). Saved totals are added up.")
                        if so_far:
                            st.markdown(f'<div class="pa-taken">{fmt_num(so_far)} taken</div>',
                                        unsafe_allow_html=True)
                    if add:
                        entries.append({"customer_sku_name": r["customer_sku_name"], "parent_sku": r["parent_sku"],
                                        "country": country, "spec": s, "boxes": int(add)})
            hold = _hold(t["boxes"], unit, opt)
            status = preprod.actual_status(r["need"], hold, sum(t["boxes"].values()))
            n_enough += status == "Enough"
            n_short += status in ("Not enough", "Not started")
            c[3].markdown(f"{ICON.get(status, '')} **{status}**")
            if hold:
                c[3].caption(f"Boxes hold {fmt_num(hold)} {_unit_word(unit)}")

    st.caption(f"{n_enough} of {len(rows)} items have enough boxes.")
    if not frozen:
        c = st.columns([2, 2, 2, 3])
        reason = c[0].selectbox("Reason", preprod.REASONS, index=0 if hist.empty else 1, key=f"{base}_reason",
                                label_visibility="collapsed")
        if c[1].button(f"Save take-out · round {len(hist) + 1}", type="primary", icon=":material/outbox:",
                       disabled=not entries, width="stretch", key=f"{base}_save"):
            try:
                n = preprod.save_round(get_backend(), day, city, group, entries, reason, user.email)
            except SheetError as e:
                st.error(f"Not saved. {e}")
                return
            st.session_state["pa_nonce"] = nonce + 1
            common.flash("success", f"Take-out saved ({n} line(s)).")
            st.rerun()
        with c[2].popover("Freeze", icon=":material/lock:", disabled=bool(entries)):
            st.markdown(f"**Freeze {group}?** No more take-outs after this; it moves to the Batching plan.")
            if n_short:
                st.warning(f"{n_short} item(s) are short or not started.")
            if st.button("Yes, freeze", type="primary", key=f"{base}_frz"):
                _freeze(day, city, group, True, user)
        if entries:
            c[3].caption("Boxes typed above are not saved yet: save the take-out before freezing.")
    else:
        with st.popover("Unfreeze", icon=":material/lock_open:"):
            st.markdown("Unfreeze lets more boxes be taken out for this customer.")
            if st.button("Yes, unfreeze", key=f"{base}_unf"):
                _freeze(day, city, group, False, user)

    st.markdown("##### Take-out history")
    if hist.empty:
        st.caption("Nothing taken out yet.")
    else:
        st.dataframe(hist, hide_index=True, width="stretch")


def _freeze(day: str, city: str, group: str, frozen: bool, user: User) -> None:
    try:
        preprod.set_frozen(get_backend(), day, city, group, frozen, user.email)
    except SheetError as e:
        st.error(f"Not saved. {e}")
        return
    common.flash("success", f"{group} {'frozen' if frozen else 'unfrozen'}.")
    st.rerun()


# ------------------------------------------------------------------ Batching plan

def render_plan(user: User) -> None:
    common.show_flash()
    st.markdown("### Batching plan")
    pct = preprod.extra_limit_pct()
    st.caption(f"Owners only (trial). Customers **frozen** in Pre-production actual. Enter the good pieces "
               f"(or kg) **used** from the boxes taken out; up to {fmt_num(pct)} % over the indent is allowed. "
               "What is left in the boxes is worked out and saved.")
    if not user.is_owner:
        st.error("This page is for owners only for now.")
        return
    ctx = _context(user, "bp")
    if ctx is None:
        return
    day, dem, m, data = ctx
    groups = _groups(dem)
    many = len({c for c, _ in groups}) > 1
    ready = [(c, g) for c, g in groups if preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, c, g)[0]]
    waiting = [g for c, g in groups if (c, g) not in ready]
    if waiting:
        st.caption("Waiting (not frozen in Pre-production actual): " + ", ".join(waiting))
    if not ready:
        st.info("No customer is frozen yet for this date.")
        return
    labels = {_label(c, g, many, "Frozen"): (c, g) for c, g in ready}
    pick = st.pills("Customer", list(labels), default=list(labels)[0], key=f"bp_grp_{day}") or list(labels)[0]
    city, group = labels[pick]
    _plan_body(user, day, city, group, dem, m, data, pct)


BP_CSS = """<style>
[class*="st-key-bpin"] [data-testid="stNumberInputContainer"]{background:#FFFDF0 !important;border:2px solid #E8B10A !important;border-radius:8px !important}
[class*="st-key-bpin"] [data-testid="stNumberInputContainer"] *{background-color:transparent !important}
[class*="st-key-bpin"] [data-testid="stNumberInputContainer"] input{font-size:1.05rem}
.bp-hint{display:flex;gap:.5rem;align-items:center;background:#FFF8DB;border:1px solid #F2DF9B;color:#6B4E00;border-radius:8px;padding:.55rem .8rem;font-size:.9rem;margin:.3rem 0 .7rem}
.bp-step{flex:none;display:inline-flex;align-items:center;justify-content:center;width:1.3rem;height:1.3rem;border-radius:50%;background:#E8B10A;color:#fff;font-size:.75rem;font-weight:700}
.bp-h{font-size:.8rem;color:#6B6F7B}.bp-ro{color:#6B6F7B}
.bp-chip{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-size:.8rem;font-weight:600}
.bp-ok{background:#E3F3E9;color:#1E6B3C}.bp-warn{background:#FDF0D5;color:#7A4F00}.bp-bad{background:#FCE4E2;color:#A32018}
.bp-bar{height:6px;border-radius:3px;background:#EEF0F4;overflow:hidden;margin:.3rem 0;max-width:220px}
.bp-fill{height:6px;background:#3D9A6A}.bp-fill.w{background:#E8B10A}.bp-fill.r{background:#D64545}
.bp-tile{border:1px solid #E6E9EF;border-radius:10px;padding:.5rem .8rem}.bp-tile .k{font-size:.8rem;color:#6B6F7B}
.bp-tile .v{font-size:1.4rem;font-weight:700}
</style>"""
CHIP = {"Covered": "bp-ok", "Short": "bp-warn", "Pending": "bp-bad", "Over limit": "bp-bad"}


def _hint(n: int, text: str) -> None:
    st.markdown(f'<div class="bp-hint"><span class="bp-step">{n}</span><span>{text}</span></div>',
                unsafe_allow_html=True)


def _cell(col, head: str, value: str) -> None:
    col.markdown(f'<div class="bp-h">{head}</div><b>{value}</b>', unsafe_allow_html=True)


def _plan_body(user: User, day: str, city: str, group: str, dem: pd.DataFrame, m, data, pct: float) -> None:
    rows = dem[(dem["city"] == city) & (dem["group"] == group)].reset_index(drop=True)
    took = preprod.taken(data[preprod.PREPROD_ACTUAL], day, city, group)
    saved = preprod.used_saved(data[preprod.BATCHING_PLAN], day, city, group)
    saved_item = preprod.item_saved(data[preprod.BATCHING_PLAN], day, city, group)
    st.markdown(BP_CSS, unsafe_allow_html=True)
    st.markdown(f"#### {group} · {city}")
    base = f"{day}_{city}_{group}"
    css_key = re.sub(r"[^A-Za-z0-9_-]", "_", base)        # container keys become CSS class names

    meta = []
    for i, r in rows.iterrows():
        key = preprod._k(r["customer_sku_name"])
        t = took.get(key, {"country": "", "boxes": {}})
        opt = _opts(m, data, r).get(t["country"], {"box_kg": None, "unit": "Box"})
        for s_, n in t["boxes"].items():
            pb = preprod.per_box(s_, r["unit"], opt.get("box_kg"))
            meta.append({"i": i, "spec": s_, "boxes": n, "in": n * pb if pb else None, "country": t["country"],
                         "key": key})
    if not meta:
        st.info("No boxes were taken out for this customer.")
        return

    # ---- step 1: used per count (yellow boxes)
    _hint(1, "Type the good pieces (or kg) used in each <b>yellow box</b>. The grey columns are filled in for you.")
    widths = [0.4, 3, 2, 0.9, 0.8, 1.2, 1.6]
    heads = ["#", "Customer SKU name", "Country", "Count", "Boxes", "In boxes", "Used (type here)"]
    hc = st.columns(widths)
    for c, h in zip(hc, heads):
        c.markdown(f'<div class="bp-h">{h}</div>', unsafe_allow_html=True)
    used_vals = []
    with st.container(key=f"bpin_used_{css_key}"):
        for j, mrow in enumerate(meta):
            r = rows.loc[mrow["i"]]
            w = _unit_word(r["unit"])
            c = st.columns(widths, vertical_alignment="center")
            c[0].markdown(f'<span class="bp-ro">{mrow["i"] + 1}</span>', unsafe_allow_html=True)
            c[1].markdown(r["customer_sku_name"])
            c[2].markdown(f'<span class="bp-ro">{mrow["country"]}</span>', unsafe_allow_html=True)
            c[3].markdown(f'<span class="bp-ro">{preprod.spec_label(mrow["spec"])}</span>', unsafe_allow_html=True)
            c[4].markdown(f'<span class="bp-ro">{fmt_num(mrow["boxes"])}</span>', unsafe_allow_html=True)
            c[5].markdown(f'<span class="bp-ro">{fmt_num(mrow["in"]) + " " + w if mrow["in"] is not None else ""}'
                          '</span>', unsafe_allow_html=True)
            old = saved.get((mrow["key"], mrow["spec"]))
            v = c[6].number_input(f"Used {r['customer_sku_name']} {mrow['spec']}", min_value=0.0, step=1.0,
                                  value=float(old) if old is not None else None, placeholder=f"type {w}",
                                  key=f"bp_u_{base}_{j}", label_visibility="collapsed")
            used_vals.append(v)

    used_by, any_by, left_by, over_box = {}, {}, {}, []
    left_known = {i: True for i in range(len(rows))}
    for mrow, u in zip(meta, used_vals):
        i = mrow["i"]
        if mrow["in"] is None:
            left_known[i] = False
        if u is None:
            continue
        used_by[i] = used_by.get(i, 0.0) + u
        any_by[i] = True
        if mrow["in"] is not None:
            left_by[i] = left_by.get(i, 0.0) + max(mrow["in"] - u, 0)
            if u > mrow["in"] + 1e-9:
                over_box.append(f"{rows.loc[i, 'customer_sku_name']} {preprod.spec_label(mrow['spec'])}")

    # ---- step 2: per item
    st.markdown("##### Per item")
    states = [preprod.batch_status(r["need"], used_by.get(i, 0.0), any_by.get(i, False), pct)
              for i, r in rows.iterrows()]
    tc = st.columns(4)
    for col, (k, v, colr) in zip(tc, [("Items", len(rows), "#31333F"),
                                      ("Covered", states.count("Covered"), "#1E6B3C"),
                                      ("Short", states.count("Short"), "#7A4F00"),
                                      ("Still to enter", states.count("Pending") + states.count("Over limit"),
                                       "#A32018")]):
        col.markdown(f'<div class="bp-tile"><div class="k">{k}</div><div class="v" style="color:{colr}">{v}</div>'
                     '</div>', unsafe_allow_html=True)
    _hint(2, "For the left over, type the <b>MT Grade</b>, <b>GT Qty</b> and <b>Dump</b> (unusable). "
             "<b>Back to box</b> is worked out for you.")
    blocked, too_much, items_out = [], [], []
    for i, r in rows.iterrows():
        key = preprod._k(r["customer_sku_name"])
        w = _unit_word(r["unit"])
        used, st_ = used_by.get(i, 0.0), states[i]
        if st_ == "Over limit":
            blocked.append(r["customer_sku_name"])
        extra = used - r["need"]
        left = left_by.get(i) if any_by.get(i) and left_known[i] else None
        pct_done = min(used / r["need"] * 100, 100) if r["need"] else 0
        bar = "r" if st_ == "Over limit" else "w" if st_ == "Short" else ""
        with st.container(border=True, key=f"bpin_item_{css_key}_{i}"):
            top = st.columns([6, 1], vertical_alignment="center")
            top[0].markdown(f'<b>{i + 1}. {r["customer_sku_name"]}</b><div class="bp-bar"><div class="bp-fill {bar}" '
                            f'style="width:{pct_done:.0f}%"></div></div>', unsafe_allow_html=True)
            top[1].markdown(f'<div style="text-align:right"><span class="bp-chip {CHIP.get(st_, "bp-bad")}">{st_}'
                            '</span></div>', unsafe_allow_html=True)
            c = st.columns(8, vertical_alignment="bottom")
            c[0].markdown(f'<div class="bp-h">Needed</div><b>{fmt_num(r["need"])} {w}</b><div class="bp-h">max '
                          f'{fmt_num(preprod.max_allowed(r["need"], pct))}</div>', unsafe_allow_html=True)
            _cell(c[1], "Used", f"{fmt_num(used)} {w}" if any_by.get(i) else "–")
            _cell(c[2], "Extra / short", "–" if not any_by.get(i) else
                  f"+{fmt_num(extra)}" if extra > 0 else f"{fmt_num(-extra)} short" if extra < 0 else "0")
            _cell(c[3], "Left over", f"{fmt_num(left)} {w}" if left is not None else "–")
            og, od, om = saved_item.get(key, (None, None, None))
            mt = c[4].number_input("MT Grade", min_value=0.0, step=1.0, value=om, placeholder=w,
                                   key=f"bp_mt_{base}_{i}")
            gt = c[5].number_input("GT Qty", min_value=0.0, step=1.0, value=og, placeholder=w,
                                   key=f"bp_gt_{base}_{i}")
            dump = c[6].number_input("Dump", min_value=0.0, step=1.0, value=od, placeholder=w,
                                     key=f"bp_dump_{base}_{i}")
            back = preprod.back_to_box(left, gt, dump, mt)
            if back is not None and back < -1e-9:
                too_much.append(r["customer_sku_name"])
            _cell(c[7], "Back to box", f"{fmt_num(back)} {w}" if back is not None else "–")
        if gt is not None or dump is not None or mt is not None:
            items_out.append({"customer_sku_name": r["customer_sku_name"], "country": "", "spec": preprod.ITEM,
                              "boxes": "", "used": "", "unit": r["unit"], "mt_grade": "" if mt is None else mt,
                              "gt_qty": "" if gt is None else gt, "dump": "" if dump is None else dump})
    if over_box:
        st.error("Used is more than the boxes hold: " + "; ".join(over_box))
    if blocked:
        st.error(f"Over the {fmt_num(pct)} % limit: " + "; ".join(blocked) + ". Fix it to save.")
    if too_much:
        st.error("MT Grade + GT Qty + Dump is more than the left over: " + "; ".join(too_much))
    if st.button("Save batching plan", type="primary", icon=":material/save:",
                 disabled=bool(blocked or over_box or too_much), key=f"bp_save_{base}"):
        out = []
        for mrow, u in zip(meta, used_vals):
            if u is None:
                continue
            r = rows.loc[mrow["i"]]
            out.append({"customer_sku_name": r["customer_sku_name"], "country": mrow["country"], "spec": mrow["spec"],
                        "boxes": mrow["boxes"], "used": float(u), "unit": r["unit"]})
        out += items_out
        try:
            n = preprod.save_plan(get_backend(), day, city, group, out, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        common.flash("success", f"Batching plan saved ({n} line(s)).")
        st.rerun()
