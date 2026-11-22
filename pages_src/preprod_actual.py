"""Pre-production actual and Batching plan pages (22 Nov; owners only while being tried).
Logic and storage: core/preprod.py. The existing Production / Batching sheets are unchanged."""
from __future__ import annotations

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
    return {"pcs": "pcs", "kg": "kg"}.get(unit, "packs")


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


@st.fragment
def _actual_body(user: User, day: str, city: str, group: str, dem: pd.DataFrame, m, data) -> None:
    rows = dem[(dem["city"] == city) & (dem["group"] == group)].reset_index(drop=True)
    frozen, f_at, f_by = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, group)
    took = preprod.taken(data[preprod.PREPROD_ACTUAL], day, city, group)
    hist = preprod.rounds(data[preprod.PREPROD_ACTUAL], day, city, group)
    nonce = st.session_state.get("pa_nonce", 0)
    base = f"pa_{nonce}_{day}_{city}_{group}"

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
            cols = c[2].columns(max(len(specs), 1)) if specs else []
            for j, s in enumerate(specs):
                so_far = t["boxes"].get(s, 0)
                lab = f"{preprod.spec_label(s)} · {fmt_num(so_far)} taken"
                if frozen:
                    cols[j].metric(preprod.spec_label(s), f"{fmt_num(so_far)} {opt['unit'].lower()}")
                    continue
                add = cols[j].number_input(lab, min_value=0, step=1, value=0, key=f"{base}_{i}_{s}",
                                           help="Boxes taken out now (this round). Saved totals are added up.")
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


def _plan_body(user: User, day: str, city: str, group: str, dem: pd.DataFrame, m, data, pct: float) -> None:
    rows = dem[(dem["city"] == city) & (dem["group"] == group)].reset_index(drop=True)
    took = preprod.taken(data[preprod.PREPROD_ACTUAL], day, city, group)
    saved = preprod.used_saved(data[preprod.BATCHING_PLAN], day, city, group)
    st.markdown(f"#### {group} · {city}")

    ed_rows, meta = [], []
    for i, r in rows.iterrows():
        key = preprod._k(r["customer_sku_name"])
        t = took.get(key, {"country": "", "boxes": {}})
        opt = _opts(m, data, r).get(t["country"], {"box_kg": None, "unit": "Box"})
        for s, n in t["boxes"].items():
            pb = preprod.per_box(s, r["unit"], opt.get("box_kg"))
            ed_rows.append({"#": str(i + 1), "Customer SKU name": r["customer_sku_name"], "Country": t["country"],
                            "Count": preprod.spec_label(s), "Boxes": fmt_num(n),
                            "In boxes": f"{fmt_num(n * pb)} {_unit_word(r['unit'])}" if pb else "",
                            "Used": saved.get((key, s))})
            meta.append({"i": i, "spec": s, "boxes": n, "in": n * pb if pb else None, "country": t["country"]})
    if not ed_rows:
        st.info("No boxes were taken out for this customer.")
        return
    unit_cap = "pcs or kg" if set(rows["unit"]) - {"pcs"} else "pcs"
    table = pd.DataFrame(ed_rows)
    table["Used"] = pd.to_numeric(table["Used"], errors="coerce")
    ed = st.data_editor(table, key=f"bp_ed_{day}_{city}_{group}", hide_index=True, width="stretch",
                        disabled=["#", "Customer SKU name", "Country", "Count", "Boxes", "In boxes"],
                        column_config={"Used": st.column_config.NumberColumn(
                            f"Used ({unit_cap})", min_value=0, step=1, help="Good pieces (kg) from these boxes "
                            "that went to this customer.")})

    used_by_line: dict[int, float] = {}
    any_by_line: dict[int, bool] = {}
    left_by_line: dict[int, float] = {}
    over_box = []
    for mrow, u in zip(meta, ed["Used"]):
        u = None if pd.isna(u) else float(u)
        i = mrow["i"]
        if u is not None:
            used_by_line[i] = used_by_line.get(i, 0) + u
            any_by_line[i] = True
            if mrow["in"] is not None:
                left_by_line[i] = left_by_line.get(i, 0) + max(mrow["in"] - u, 0)
                if u > mrow["in"] + 1e-9:
                    over_box.append(f"{rows.loc[i, 'customer_sku_name']} {preprod.spec_label(mrow['spec'])}")
    summary, blocked = [], []
    for i, r in rows.iterrows():
        used = used_by_line.get(i, 0.0)
        st_ = preprod.batch_status(r["need"], used, any_by_line.get(i, False), pct)
        if st_ == "Over limit":
            blocked.append(r["customer_sku_name"])
        w = _unit_word(r["unit"])
        extra = used - r["need"]
        summary.append({"#": str(i + 1), "Customer SKU name": r["customer_sku_name"],
                        "Needed": f"{fmt_num(r['need'])} {w}", "Max": f"{fmt_num(preprod.max_allowed(r['need'], pct))}",
                        "Used": fmt_num(used) if any_by_line.get(i) else "",
                        "Extra / short": "" if not any_by_line.get(i) else
                        (f"+{fmt_num(extra)} ({fmt_num(round(extra / r['need'] * 100, 1))} %)" if extra > 0 and r["need"]
                         else f"{fmt_num(-extra)} short" if extra < 0 else "0"),
                        "Left in boxes": f"{fmt_num(left_by_line[i])} {w}" if i in left_by_line else "",
                        "Status": f"{ICON.get(st_, '')} {st_}"})
    st.markdown("##### Per item")
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    if over_box:
        st.error("Used is more than the boxes hold: " + "; ".join(over_box))
    if blocked:
        st.error(f"Over the {fmt_num(pct)} % limit: " + "; ".join(blocked) + ". Fix it to save.")
    if st.button("Save batching plan", type="primary", icon=":material/save:", disabled=bool(blocked or over_box),
                 key=f"bp_save_{day}_{city}_{group}"):
        out = []
        for mrow, u in zip(meta, ed["Used"]):
            if pd.isna(u):
                continue
            r = rows.loc[mrow["i"]]
            out.append({"customer_sku_name": r["customer_sku_name"], "country": mrow["country"], "spec": mrow["spec"],
                        "boxes": mrow["boxes"], "used": float(u), "unit": r["unit"]})
        try:
            n = preprod.save_plan(get_backend(), day, city, group, out, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        common.flash("success", f"Batching plan saved ({n} line(s)).")
        st.rerun()
