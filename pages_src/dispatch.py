"""Dispatch, Returns and Dispatch check pages (23 Nov; OWNERS ONLY while being tried).
Logic and storage: core/dispatch.py. Nothing here is shown to sales or warehouse users."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from core import config, dispatch, indents, preprod
from core.auth import User
from core.models import fmt_num, to_number
from core.schema import DISPATCH_LINES, RETURN_LINES
from core.sheets import SheetError, get_backend
from pages_src import common
from pages_src.preprod_actual import BP_CSS, _hint

DS_CSS = """<style>
.ds-flow{display:flex;gap:.4rem;flex-wrap:wrap;margin:.2rem 0 .8rem}
.ds-st{display:inline-flex;align-items:center;padding:.25rem .7rem;border-radius:999px;font-size:.8rem;font-weight:600;
border:1px solid #E6E9EF;background:#F7F8FA;color:#6B6F7B}
.ds-st.d{background:#E3F3E9;color:#1E6B3C;border-color:#CDE9D8}.ds-st.n{background:#FFF3C4;color:#6B4E00;border:2px solid #E8B10A}
.ds-neu{background:#EEF0F4;color:#4B4F5A}
table.ds{width:100%;border-collapse:separate;border-spacing:0;border:1px solid #E6E9EF;border-radius:10px;overflow:hidden;font-size:.9rem}
table.ds th{background:#FAFBFC;color:#6B6F7B;font-weight:400;text-align:left;padding:.5rem .6rem;border-bottom:1px solid #E6E9EF}
table.ds td{padding:.5rem .6rem;border-bottom:1px solid #EEF0F4}
.ds-dot{display:inline-block;width:.7rem;height:.7rem;border-radius:50%}
.g{background:#3D9A6A}.y{background:#E8B10A}.e{background:#D5D8DE}.r{background:#D64545}
</style>"""
STEPS = ["Indent", "Pre-production", "Batching", "Dispatch", "Returns", "Final invoice"]


def _css(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", v)


_CLS = {"ok": "bp-ok", "warn": "bp-warn", "bad": "bp-bad"}


def _chip(spec: str) -> str:
    if not spec:
        return ""
    cls, text = spec.split("|", 1)
    return f'<span class="bp-chip {_CLS.get(cls, "ds-neu")}">{text}</span>'


def _flow(s: dict) -> None:
    """Step bar from the indent's real state: done steps green, the first open step yellow."""
    done = [True, s["frozen"], s["batched_all"], bool(s["dispatch"]), bool(s["returns"]), bool(s["returns"])]
    now = next((i for i, d in enumerate(done) if not d), len(done))
    parts = []
    for i, (name, d) in enumerate(zip(STEPS, done)):
        cls = "d" if d else "n" if i == now else ""
        parts.append(f'<span class="ds-st {cls}">{"✓ " if d else f"{i + 1} "}{name}{" · now" if i == now else ""}</span>')
    st.markdown('<div class="ds-flow">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def _guard(user: User, title: str, text: str) -> bool:
    common.show_flash()
    st.markdown(f"### {title}")
    st.caption("Owners only (trial). " + text)
    st.markdown(BP_CSS + DS_CSS, unsafe_allow_html=True)
    if not user.is_owner:
        st.error("This page is for owners only for now.")
        return False
    return True


def _load(user: User, prefix: str):
    """Date / city filters like the Production sheet -> (day, lines, preprod data, dispatch data) or None."""
    from pages_src import production
    res = production._filtered(user, prefix)
    if res is None:
        return None
    lines = res[0].copy()
    day = st.session_state.get(f"{prefix}_ctx", (None, production.ALL_DATES))[1]
    if day == production.ALL_DATES:
        st.info("Pick one delivery date.")
        return None
    lines["qty_n"] = lines["qty"].map(to_number)
    lines = lines[lines["qty_n"] > 0]
    try:
        pdata = preprod.read_all()
        ddata = dispatch.read_all()
    except SheetError as e:
        common.sheet_error(e)
        return None
    return day, lines, pdata, ddata


def _group(r) -> str:
    from core.production_calc import customer_group
    return customer_group(r["customer"], r["store"])


def _batched(pdata, day: str, city: str, group: str) -> dict[str, float]:
    """{sku key: used (pcs / kg / punnets)} summed over the counts, from the Batching plan."""
    out: dict[str, float] = {}
    for (k, _spec), v in preprod.used_saved(pdata[preprod.BATCHING_PLAN], day, city, group).items():
        out[k] = out.get(k, 0.0) + v
    return out


def _per(r) -> float:
    return preprod.need_unit(r["customer_sku_name"], r.get("lot", ""), r.get("parent_sku", ""))[1] or 1.0


def _indent_states(lines: pd.DataFrame, day: str, pdata, ddata) -> dict[str, dict]:
    """Per indent: head + which steps are done (for the pills and Dispatch check)."""
    po = indents.latest_po()
    out = {}
    for iid, g in lines.groupby("indent_id", sort=False):
        r = g.iloc[0]
        grp = _group(r)
        frozen = preprod.freeze_state(pdata[preprod.PREPROD_FREEZE], day, r["city"], grp)[0]
        took = preprod.taken(pdata[preprod.PREPROD_ACTUAL], day, r["city"], grp)
        bat = _batched(pdata, day, r["city"], grp)
        keys = {preprod._k(n) for n in g["customer_sku_name"]}
        d = dispatch.dispatched(ddata[DISPATCH_LINES], iid)
        rt = dispatch.returned(ddata[RETURN_LINES], iid)
        out[iid] = {"city": r["city"], "customer": r["customer"], "store": r["store"], "group": grp,
                    "lines": g, "frozen": frozen, "took": bool(took), "po": po.get(str(iid), {}).get("po_number", ""),
                    "batched_all": keys and keys <= set(bat), "batched_any": bool(keys & set(bat)),
                    "dispatch": d, "returns": rt, "status": str(r.get("status", ""))}
    return out


# ------------------------------------------------------------------ Dispatch

def render_dispatch(user: User) -> None:
    if not _guard(user, "Dispatch", "Type what is loaded for each indent. It starts from the Batching plan; "
                  "saving makes the Delivery Order (proforma)."):
        return
    ctx = _load(user, "ds")
    if ctx is None:
        return
    day, lines, pdata, ddata = ctx
    states = _indent_states(lines, day, pdata, ddata)
    ready = {i: s for i, s in states.items() if s["frozen"]}
    waiting = [f"{i} {s['customer']}" for i, s in states.items() if not s["frozen"]]
    if waiting:
        st.caption("Waiting for Pre-production freeze: " + ", ".join(waiting))
    if not ready:
        st.info("No indent is ready yet: freeze the customer in Pre-production actual and save the Batching plan.")
        return
    labels = {f"{i} · {s['customer']} - {s['store']} · "
              f"{'Dispatched ' + s['dispatch']['doc_no'] if s['dispatch'] else 'Ready'}": i for i, s in ready.items()}
    pick = st.pills("Indent", list(labels), default=list(labels)[0], key=f"ds_pick_{day}") or list(labels)[0]
    iid = labels[pick]
    _dispatch_body(user, day, iid, ready[iid], states, pdata, ddata)


def _dispatch_body(user, day, iid, s, states, pdata, ddata) -> None:
    pct = preprod.extra_limit_pct()
    g = s["lines"].reset_index(drop=True)
    st.markdown(f"#### {iid} · {s['customer']} - {s['store']} · {s['city']}")
    _flow(s)
    bat = _batched(pdata, day, s["city"], s["group"])
    same_group = [i for i, o in states.items() if o["group"] == s["group"] and o["city"] == s["city"] and i != iid]
    saved = s["dispatch"].get("items", {}) if s["dispatch"] else {}
    if s["dispatch"]:
        st.success(f"Dispatched as **{s['dispatch']['doc_no']}** at {s['dispatch']['at'][11:16]} by "
                   f"{s['dispatch']['by']}. Change and save again to replace it.")
    _hint(1, "Type what is actually loaded in each <b>yellow box</b>. It starts from the Batching plan; change it "
             "if the truck load is different.")
    widths = [0.4, 3, 1.3, 1.5, 1.6, 1.5, 1.7]
    for col, h in zip(st.columns(widths), ["#", "Customer SKU name", "Required", "Batched", "Dispatch qty (type here)",
                                           "vs required", "vs batching"]):
        col.markdown(f'<div class="bp-h">{h}</div>', unsafe_allow_html=True)
    base = f"ds_{day}_{iid}"
    items, bad = [], []
    with st.container(key=f"bpin_ds_{_css(base)}"):
        for i, r in g.iterrows():
            key = preprod._k(r["customer_sku_name"])
            word = str(r.get("lot", "") or "").lower()
            per = _per(r)
            others = sum(to_number(states[o]["dispatch"].get("items", {}).get(key, {}).get("dispatch_qty"))
                         for o in same_group if states[o]["dispatch"])
            b_lots = round(bat[key] / per - others, 3) if key in bat else None
            qty = r["qty_n"]
            old = saved.get(key, {}).get("dispatch_qty")
            start = to_number(old) if old not in (None, "") else (b_lots if b_lots is not None else qty)
            c = st.columns(widths, vertical_alignment="center")
            c[0].markdown(f'<span class="bp-ro">{i + 1}</span>', unsafe_allow_html=True)
            c[1].markdown(r["customer_sku_name"])
            c[2].markdown(f'<b>{fmt_num(qty)} {word}</b>', unsafe_allow_html=True)
            c[3].markdown(f'<span class="bp-ro">{fmt_num(b_lots) + " " + word if b_lots is not None else "–"}'
                          f'{" (after other stores)" if others and b_lots is not None else ""}</span>',
                          unsafe_allow_html=True)
            v = c[4].number_input(f"Dispatch {r['customer_sku_name']}", min_value=0.0, step=1.0, value=float(start),
                                  key=f"{base}_{i}", label_visibility="collapsed")
            vi, vb = dispatch.check(qty, v, b_lots, pct)
            c[5].markdown(_chip(vi), unsafe_allow_html=True)
            c[6].markdown(_chip(vb), unsafe_allow_html=True)
            if vi.startswith("bad") or vb.startswith("bad"):
                bad.append(r["customer_sku_name"])
            items.append({"customer_sku_name": r["customer_sku_name"], "lot": r.get("lot", ""), "indent_qty": qty,
                          "dispatch_qty": v, "price": to_number(r.get("price")), "reason": ""})
    reason = ""
    if bad:
        st.error("Over the limit or more than batching: " + "; ".join(bad))
        reason = st.text_input("Reason to go ahead anyway", key=f"{base}_why",
                               placeholder="Customer asked for more, extra stock from yesterday …")
    c = st.columns([1.3, 1.6, 1, 2], vertical_alignment="bottom")
    old_head = s["dispatch"] or {}
    vehicle = c[0].text_input("Vehicle no.", value=old_head.get("vehicle", ""), key=f"{base}_veh")
    driver = c[1].text_input("Driver · phone", value=old_head.get("driver", ""), key=f"{base}_drv")
    at = c[2].text_input("Dispatched at", value=config.now_ist().strftime("%H:%M"), key=f"{base}_at")
    blocked = bool(bad) and not reason.strip()
    if c[3].button("Dispatch and make Delivery Order", type="primary", icon=":material/local_shipping:",
                   disabled=blocked, key=f"{base}_go"):
        head = {"indent_id": iid, "delivery_date": day, "city": s["city"], "customer": s["customer"],
                "store": s["store"], "vehicle": vehicle.strip(), "driver": driver.strip(),
                "dispatched_at": f"{day} {at.strip()}"}
        for it in items:
            it["reason"] = reason.strip()
        try:
            doc = dispatch.save_dispatch(get_backend(), head, items, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        common.flash("success", f"Dispatched. Delivery Order {doc} is ready to download.")
        st.rerun()
    if s["dispatch"]:
        rows = list(s["dispatch"]["items"].values())
        head = {"doc_no": s["dispatch"]["doc_no"], "indent_id": iid, "po": s["po"], "delivery_date": day,
                "customer": s["customer"], "store": s["store"], "city": s["city"], "vehicle": s["dispatch"]["vehicle"],
                "driver": s["dispatch"]["driver"], "dispatched_at": s["dispatch"]["at"]}
        st.download_button(f"Delivery Order {head['doc_no']} (PDF)", lambda: dispatch.delivery_order_pdf(head, rows),
                           file_name=f"{head['doc_no']}.pdf", mime="application/pdf", icon=":material/download:",
                           key=f"{base}_dopdf", on_click="ignore")


# ------------------------------------------------------------------ Returns

def render_returns(user: User) -> None:
    if not _guard(user, "Returns", "Mark what the store sent back. Saving makes the final invoice "
                  "(billed = dispatched − returned)."):
        return
    ctx = _load(user, "rt")
    if ctx is None:
        return
    day, lines, pdata, ddata = ctx
    states = {i: s for i, s in _indent_states(lines, day, pdata, ddata).items() if s["dispatch"]}
    if not states:
        st.info("Nothing dispatched for this date yet.")
        return
    labels = {f"{i} · {s['customer']} - {s['store']} · "
              f"{'Invoiced ' + s['returns']['invoice_no'] if s['returns'] else 'Dispatched'}": i
              for i, s in states.items()}
    pick = st.pills("Indent", list(labels), default=list(labels)[0], key=f"rt_pick_{day}") or list(labels)[0]
    iid = labels[pick]
    s = states[iid]
    st.markdown(f"#### {iid} · {s['customer']} - {s['store']} · {s['city']}")
    _flow(s)
    st.caption(f"Dispatched as {s['dispatch']['doc_no']} at {s['dispatch']['at'][11:16]}.")
    if s["returns"]:
        st.success(f"Returns saved; final invoice **{s['returns']['invoice_no']}**. Change and save again to replace.")
    _hint(2, "Type what the store sent back (or rejected) and why. <b>Billed</b> is worked out for you.")
    widths = [0.4, 3, 1.2, 1.2, 1.5, 1.8, 1.2]
    for col, h in zip(st.columns(widths), ["#", "Customer SKU name", "Required", "Dispatched", "Returned (type here)",
                                           "Reason", "Billed"]):
        col.markdown(f'<div class="bp-h">{h}</div>', unsafe_allow_html=True)
    base = f"rt_{day}_{iid}"
    parents = {preprod._k(n): p for n, p in zip(s["lines"]["customer_sku_name"], s["lines"]["parent_sku"])}
    old = s["returns"].get("items", {}) if s["returns"] else {}
    items, over = [], []
    with st.container(key=f"bpin_rt_{_css(base)}"):
        for i, (key, r) in enumerate(s["dispatch"]["items"].items()):
            word = str(r.get("lot", "") or "").lower()
            disp = to_number(r["dispatch_qty"])
            o = old.get(key, {})
            c = st.columns(widths, vertical_alignment="center")
            c[0].markdown(f'<span class="bp-ro">{i + 1}</span>', unsafe_allow_html=True)
            c[1].markdown(r["customer_sku_name"])
            c[2].markdown(f'<b>{fmt_num(to_number(r.get("indent_qty")))} {word}</b>', unsafe_allow_html=True)
            c[3].markdown(f'<span class="bp-ro">{fmt_num(disp)} {word}</span>', unsafe_allow_html=True)
            ret = c[4].number_input(f"Returned {r['customer_sku_name']}", min_value=0.0, step=1.0,
                                    value=to_number(o.get("returned")) if o else 0.0, key=f"{base}_{i}",
                                    label_visibility="collapsed")
            reasons = ["–"] + dispatch.RETURN_REASONS
            why = c[5].selectbox(f"Reason {r['customer_sku_name']}", reasons,
                                 index=reasons.index(o.get("reason")) if o and o.get("reason") in reasons else 0,
                                 key=f"{base}_{i}_why", label_visibility="collapsed", disabled=not ret)
            billed = disp - ret
            if billed < -1e-9:
                over.append(r["customer_sku_name"])
            c[6].markdown(f"**{fmt_num(max(billed, 0))} {word}**")
            items.append({"customer_sku_name": r["customer_sku_name"], "lot": r.get("lot", ""), "dispatched": disp,
                          "returned": ret, "reason": "" if why == "–" or not ret else why, "billed": max(billed, 0),
                          "price": to_number(r.get("price")), "parent_sku": parents.get(key, "")})
    if over:
        st.error("Returned is more than dispatched: " + "; ".join(over))
    if st.button("Save returns and make final invoice", type="primary", icon=":material/receipt_long:",
                 disabled=bool(over), key=f"{base}_go"):
        try:
            inv = dispatch.save_returns(get_backend(), iid, s["dispatch"]["doc_no"],
                                        [{k: v for k, v in it.items() if k != "parent_sku"} for it in items],
                                        user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        common.flash("success", f"Returns saved. Final invoice {inv} is ready to download.")
        st.rerun()
    if s["returns"]:
        rows = []
        for key, r in s["returns"]["items"].items():
            rows.append({**r, "parent_sku": parents.get(key, "")})
        head = {"invoice_no": s["returns"]["invoice_no"], "indent_id": iid, "doc_no": s["dispatch"]["doc_no"],
                "po": s["po"], "date": s["returns"]["at"][:10], "customer": s["customer"], "store": s["store"],
                "city": s["city"]}
        st.download_button(f"Final invoice {head['invoice_no']} (PDF)", lambda: dispatch.invoice_pdf(head, rows),
                           file_name=f"{head['invoice_no']}.pdf", mime="application/pdf", icon=":material/download:",
                           key=f"{base}_invpdf", on_click="ignore")


# ------------------------------------------------------------------ Dispatch check

def _dots(s: dict) -> list[str]:
    pre = "g" if s["frozen"] else "y" if s["took"] else "e"
    bat = "g" if s["batched_all"] else "y" if s["batched_any"] else "e"
    dis = "g" if s["dispatch"] else "e"
    ret = "g" if s["returns"] else "y" if s["dispatch"] else "e"
    inv = "g" if s["returns"] else "e"
    po = "g" if s["po"] or s["status"].lower() == "frozen" else "e"
    return ["g", po, pre, bat, dis, ret, inv]


def _note(s: dict) -> str:
    if s["returns"]:
        return f"Invoice {s['returns']['invoice_no']}"
    if s["dispatch"]:
        return f"Dispatched {s['dispatch']['at'][11:16]} · {s['dispatch']['doc_no']}"
    if s["frozen"]:
        return "Ready for dispatch" if s["batched_all"] else "Batching in progress"
    if s["took"]:
        return "Take-out started"
    return "PO uploaded" if s["po"] else "Waiting for PO"


def render_check(user: User) -> None:
    if not _guard(user, "Dispatch check", "Every indent, every step, one place."):
        return
    ctx = _load(user, "dc")
    if ctx is None:
        return
    day, lines, pdata, ddata = ctx
    states = _indent_states(lines, day, pdata, ddata)
    n = len(states)
    disp = sum(1 for s in states.values() if s["dispatch"])
    inb = sum(1 for s in states.values() if s["frozen"] and not s["dispatch"])
    tc = st.columns(4)
    for col, (k, v, colr) in zip(tc, [("Indents", n, "#31333F"), ("Dispatched", disp, "#1E6B3C"),
                                      ("In batching", inb, "#7A4F00"), ("Not started", n - disp - inb, "#A32018")]):
        col.markdown(f'<div class="bp-tile"><div class="k">{k}</div><div class="v" style="color:{colr}">{v}</div>'
                     '</div>', unsafe_allow_html=True)
    st.markdown('<div class="bp-h" style="margin:.6rem 0 .3rem"><span class="ds-dot g"></span> done &nbsp; '
                '<span class="ds-dot y"></span> in progress &nbsp; <span class="ds-dot e"></span> not started</div>',
                unsafe_allow_html=True)
    heads = ["Customer · indent", "Indent", "PO", "Pre-production", "Batching", "Dispatch", "Returns", "Invoice", "Note"]
    body = ""
    for iid, s in states.items():
        dots = "".join(f'<td style="text-align:center"><span class="ds-dot {d}"></span></td>' for d in _dots(s))
        body += (f"<tr><td><b>{s['customer']}</b> · {s['city']}<div class='bp-h'>{iid} · {s['store']} · "
                 f"{len(s['lines'])} items</div></td>{dots}<td class='bp-h'>{_note(s)}</td></tr>")
    st.markdown('<table class="ds"><tr>' + "".join(f"<th>{h}</th>" for h in heads) + "</tr>" + body + "</table>",
                unsafe_allow_html=True)

    st.markdown("##### Item by item")
    pick = st.selectbox("Indent", list(states), format_func=lambda i: f"{i} · {states[i]['customer']} - "
                        f"{states[i]['store']}", key=f"dc_pick_{day}")
    s = states[pick]
    took = preprod.taken(pdata[preprod.PREPROD_ACTUAL], day, s["city"], s["group"])
    bat = _batched(pdata, day, s["city"], s["group"])
    po_q = indents.po_info(indents.read_po_freeze(), pick).get("qty") or {}
    po_q = {preprod._k(k): v for k, v in po_q.items()}
    rows = []
    for i, r in s["lines"].reset_index(drop=True).iterrows():
        key = preprod._k(r["customer_sku_name"])
        word = str(r.get("lot", "") or "").lower()
        boxes = sum(took.get(key, {}).get("boxes", {}).values())
        d = s["dispatch"].get("items", {}).get(key) if s["dispatch"] else None
        rt = s["returns"].get("items", {}).get(key) if s["returns"] else None
        rows.append({"#": i + 1, "Item": r["customer_sku_name"], "Required": f"{fmt_num(r['qty_n'])} {word}",
                     "PO": fmt_num(po_q[key]) if key in po_q else "–",
                     "Taken out": f"{fmt_num(boxes)} box" if boxes else "–",
                     "Batched": f"{fmt_num(bat[key] / _per(r))} {word}" if key in bat else "–",
                     "Dispatched": fmt_num(to_number(d["dispatch_qty"])) if d else "–",
                     "Returned": fmt_num(to_number(rt["returned"])) if rt else "–",
                     "Billed": fmt_num(to_number(rt["billed"])) if rt else "–"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Taken out and Batched are for the whole customer on this date (stores clubbed, like batching).")
