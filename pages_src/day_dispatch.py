"""Dispatch and Returns at the end of the day (27 Nov, trial). Logic: core/day_dispatch.py.

Dispatch: one card per indent (customer · delivery point); per item the PO qty (indent qty until the PO comes),
MT left, what was sent so far and ONE amber box for what goes now. 'Dispatch and lock' saves a round that can
never be changed; more can be sent later as a new round (also above the PO = extra stock).
Returns: the same cards for what was sent; what came back is typed once (more can be added). The check table
shows sent = with the customer + returned, and billed = never above the PO."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core import day_dispatch as dd
from core import prod_actual as pa
from core import processed2 as p2
from core.auth import User
from core.schema import DAY_DISPATCH, DAY_RETURNS
from core.sheets import SheetError, get_backend
from pages_src import common

CSS = """<style>
[class*="st-key-ddin"] [data-baseweb="input"], [class*="st-key-ddin"] [data-baseweb="base-input"]
  {border-color:#EF9F27 !important;}
.dd-chip{font-size:.8rem;padding:2px 10px;border-radius:8px;white-space:nowrap}
.dd-h{font-size:.8rem;color:#64748B}
.dd-t{font-weight:600;font-size:1rem}
</style>"""
CHIP = {"todo": ("#FAEEDA", "#633806"), "part": ("#FFF6C2", "#633806"), "done": ("#EAF3DE", "#27500A"),
        "bad": ("#FCEBEB", "#791F1F"), "none": ("#F1F5F9", "#475569")}
STATUS_BG = {"Billed as PO": "#EAF3DE", "Returns pending": "#F1F5F9", "Not sent": "#FAEEDA", "Not asked": ""}


def _g(v) -> str:
    if v is None or v == "":
        return ""
    return f"{float(v):,.2f}".rstrip("0").rstrip(".")


def _chip(text: str, kind: str) -> str:
    bg, fg = CHIP[kind]
    return f'<span class="dd-chip" style="background:{bg};color:{fg}">{text}</span>'


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%-I:%M %p")
    except Exception:  # noqa: BLE001
        return ""


def _who(email: str) -> str:
    return str(email or "").split("@")[0]


def _load(user: User, pre: str):
    """Date + city pickers and everything both pages read. None when it cannot load."""
    try:
        m = masters.load_masters()
        data = {"lots": pa.read(), "saved": p2.read(), "lines": indents.current_rows(indents.read_lines()),
                "po": indents.read_po_freeze(), "disp": dd.read(DAY_DISPATCH), "ret": dd.read(DAY_RETURNS),
                "links": indents.po_item_links()}
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return None
    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = common.day_input(top[0], f"{pre}_day").isoformat()
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key=f"{pre}_city") or cities[0]
    items = dd.asked(data["lines"], data["po"], day, city, data["links"])
    sent = dd.totals(data["disp"], day, city, "dispatch_qty")
    back = dd.totals(data["ret"], day, city, "returned_qty")
    return {**data, "day": day, "city": city, "items": items, "sent": sent, "back": back,
            "d_rounds": dd.rounds(data["disp"], day, city, "dispatch_id"),
            "r_rounds": dd.rounds(data["ret"], day, city, "return_id"),
            "made": dd.mt_made(data["lots"], data["saved"], day, city)}


def _by_indent(items: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for it in items:
        out.setdefault(it["indent_id"], []).append(it)
    return dict(sorted(out.items(), key=lambda kv: (kv[1][0]["customer"].casefold(), kv[1][0]["store"].casefold())))


def _customer_pills(groups: dict, pre: str) -> dict:
    names = list(dict.fromkeys(g[0]["customer"] for g in groups.values()))
    if len(names) < 2:
        return groups
    count = {n: sum(1 for g in groups.values() if g[0]["customer"] == n) for n in names}
    pick = st.pills("Customer", ["All"] + names, default="All", key=f"{pre}_cust",
                    format_func=lambda n: n if n == "All" else f"{n} · {count[n]}") or "All"
    return groups if pick == "All" else {k: g for k, g in groups.items() if g[0]["customer"] == pick}


def _head(cols, names) -> None:
    for c, n in zip(cols, names):
        c.markdown(f'<span class="dd-h">{n}</span>', unsafe_allow_html=True)


# ------------------------------------------------------------------ Dispatch

def render(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Dispatch")
    d = _load(user, "dd")
    if d is None:
        return
    if not d["items"]:
        st.info("No indents for this date and city.")
        return
    groups = _by_indent(d["items"])
    k = lambda it: (it["indent_id"], dd._n(it["customer_sku_name"]))   # noqa: E731
    asked = sum(it["asked"] for it in d["items"])
    sent = sum(d["sent"].get(k(it), 0.0) for it in d["items"])
    short = sum(max(it["asked"] - d["sent"].get(k(it), 0.0), 0.0) for it in d["items"])
    extra = sum(max(d["sent"].get(k(it), 0.0) - it["asked"], 0.0) for it in d["items"])
    t = st.columns(5)
    t[0].metric("Indents sent", f"{len([g for g in groups if g in d['d_rounds']])} of {len(groups)}")
    t[1].metric("PO qty", _g(asked) or "0")
    t[2].metric("Sent", _g(sent) or "0")
    t[3].metric("Short vs PO", _g(short) or "0")
    t[4].metric("Extra over PO", _g(extra) or "0")
    left = {key: v - dd.pool_used(d["disp"], d["day"], d["city"]).get(key, 0.0) for key, v in d["made"].items()}
    for iid, its in _customer_pills(groups, "dd").items():
        _dispatch_card(iid, its, d, left, user)
    _stock(d)


def _dispatch_card(iid: str, its: list[dict], d: dict, left: dict, user: User) -> None:
    rounds = d["d_rounds"].get(iid, [])
    got = {it["customer_sku_name"]: d["sent"].get((iid, dd._n(it["customer_sku_name"])), 0.0) for it in its}
    full = all(got[it["customer_sku_name"]] >= it["asked"] - 1e-9 for it in its)
    head = its[0]
    with st.container(border=True, key=f"ddcard_{iid}"):
        a, b = st.columns([3, 2])
        po = f" · PO {head['po_numbers']}" if head["po_numbers"] else ("" if head["has_po"] else " · no PO yet")
        a.markdown(f'<span class="dd-t">{head["customer"]} · {head["store"]} · {iid}</span>'
                   f'<span class="dd-h">{po}</span>', unsafe_allow_html=True)
        if rounds:
            last = rounds[-1]
            txt = f"🔒 Sent {_when(last['at'])} · {_who(last['by'])}" + (f" · {len(rounds)} rounds" if len(rounds) > 1 else "")
            b.markdown(_chip(txt, "done" if full else "part"), unsafe_allow_html=True)
        else:
            b.markdown(_chip("To dispatch", "todo"), unsafe_allow_html=True)
        box = st.expander("Send more (extra stock)") if full and rounds else st.container()
        with box:
            w = [3.2, 1, 1, 1, 1, 1.3, 1.5]
            _head(st.columns(w), ["Item", "PO qty" if head["has_po"] else "Indent qty", "MT left", "Sent so far",
                                  "Still to send", "Dispatch now", "Vs PO" if head["has_po"] else "Vs indent"])
            now: dict[str, float] = {}
            for i, it in enumerate(its):
                name = it["customer_sku_name"]
                c = st.columns(w, vertical_alignment="center")
                c[0].markdown(name + (" · *not on indent*" if it.get("po_only") else "")
                              + (" · *not on PO*" if it["has_po"] and it["po_qty"] is None else ""))
                c[1].markdown(_g(it["asked"]) or "0")
                pool = left.get(it["pool_key"]) if it["pool_key"] else None
                c[2].markdown("–" if pool is None else f"{_g(pool / it['per']) or '0'}"
                              + ("" if it["unit"] == "packs" else f" ({_g(pool)} kg)"))
                c[3].markdown(_g(got[name]) or "0")
                rest = max(it["asked"] - got[name], 0.0)
                c[4].markdown(_g(rest) or "0")
                q = c[5].number_input("Dispatch now", min_value=0.0, value=float(rest), step=1.0, format="%g",
                                      label_visibility="collapsed", key=f"ddin_{iid}_{i}_{len(rounds)}")
                now[name] = q or 0.0
                tot = got[name] + now[name]
                diff = tot - it["asked"]
                txt = "Same" if abs(diff) < 1e-9 else f"{_g(-diff)} short" if diff < 0 else f"+{_g(diff)} extra"
                over = pool is not None and now[name] * it["per"] > pool + 1e-9
                c[6].markdown(_chip(txt, "done" if abs(diff) < 1e-9 else "bad" if diff < 0 else "part")
                              + (' <span class="dd-h">more than MT left</span>' if over else ""),
                              unsafe_allow_html=True)
            f = st.columns([1.6, 4])
            with f[0].popover("Dispatch and lock", icon=":material/lock:", width="stretch"):
                st.markdown("Once sent, it **can't be changed**. More can be sent later as a new round.")
                if st.button("Yes, dispatch", type="primary", key=f"ddgo_{iid}_{len(rounds)}"):
                    rows = dd.dispatch_rows(its, now, d["day"], d["city"], user.email)
                    if not rows:
                        st.toast("Enter a quantity for at least one item.")
                    else:
                        try:
                            dd.save(get_backend(), DAY_DISPATCH, rows)
                            common.flash("success", f"{iid}: dispatch saved and locked ({len(rows)} item(s)).")
                            st.rerun()
                        except SheetError as e:
                            common.sheet_error(e, "Could not save the dispatch.")
            f[1].markdown('<span class="dd-h">Once sent, it can\'t be changed.</span>', unsafe_allow_html=True)


def _stock(d: dict) -> None:
    rows = dd.stock_rows(d["made"], d["items"], d["sent"], d["back"])
    st.markdown("#### End of day · MT made vs sent")
    if not rows:
        st.caption("Nothing saved on Production Detail Process for this date yet.")
        return
    df = pd.DataFrame(rows, columns=dd.STOCK_HEAD).astype(object)
    pct = [r["Sold of MT"] for r in rows]
    show = df.copy()
    for col in ("MT made", "Asked", "Dispatched", "MT left", "Returned"):
        show[col] = [_g(v) or "0" for v in df[col]]
    show["Sold of MT"] = ["" if v is None else f"{round(v * 100)}%" for v in pct]

    def paint(col):
        return [f"background-color:{p2_band(v)}" for v in pct]

    def neg(col):
        return ["background-color:#FCEBEB" if r["MT left"] < -1e-9 else "" for r in rows]
    st.dataframe(show.style.apply(paint, subset=["Sold of MT"]).apply(neg, subset=["MT left"]),
                 hide_index=True, width="stretch")
    gt = _gt_dump(d)
    st.caption("MT left = MT made − dispatched (red when more was sent than was made). Sold of MT = (dispatched − "
               "returned) ÷ MT made. Piece lots are in packs, kg lots in kg." + gt)


def p2_band(v) -> str:
    b = p2.eff_band(v)
    return {"green": "#EAF3DE", "amber": "#FAEEDA", "yellow": "#FFF6C2", "red": "#FCEBEB"}.get(b, "")


def _gt_dump(d: dict) -> str:
    _, tot = p2.category_rows(d["lots"], d["saved"], {d["day"]}, d["city"])
    if not tot or not tot.get("j"):
        return ""
    return (f" Whole day in kg: used **{_g(tot['j'])}** · MT **{_g(tot['k'])}** · GT **{_g(tot['l'])}** · "
            f"dump **{_g(tot['m'])}**.")


# ------------------------------------------------------------------- Returns

def render_returns(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Returns")
    d = _load(user, "dr")
    if d is None:
        return
    groups = {iid: its for iid, its in _by_indent(d["items"]).items() if iid in d["d_rounds"]}
    if not groups:
        st.info("Nothing was dispatched for this date and city yet. Returns come after **Dispatch**.")
        return
    chk = dd.check_rows([it for g in groups.values() for it in g], d["sent"], d["back"], d["r_rounds"])
    t = st.columns(5)
    t[0].metric("Returns entered", f"{len([g for g in groups if g in d['r_rounds']])} of {len(groups)}")
    t[1].metric("Sent", _g(sum(r["Sent"] for r in chk)) or "0")
    t[2].metric("Returned", _g(sum(r["Returned"] or 0 for r in chk)) or "0")
    t[3].metric("With customer", _g(sum(r["With customer"] for r in chk)) or "0")
    t[4].metric("Billed (never above PO)", _g(sum(r["Billed"] for r in chk)) or "0")
    for iid, its in _customer_pills(groups, "dr").items():
        _return_card(iid, its, d, user)
    st.markdown("#### Dispatch check")
    df = pd.DataFrame(chk, columns=dd.CHECK_HEAD).astype(object)
    show = df.copy()
    for col in ("PO qty", "Indent qty", "Sent", "Extra sent", "Returned", "With customer", "Billed"):
        show[col] = ["" if v is None or (isinstance(v, float) and pd.isna(v)) else (_g(v) or "0") for v in df[col]]

    def paint(v):
        bg = STATUS_BG.get(v, "#FCEBEB" if "over PO" in str(v) or "more than" in str(v) else "#FFF6C2")
        return f"background-color:{bg}" if bg else ""
    st.dataframe(show.style.map(paint, subset=["Status"]), hide_index=True, width="stretch")
    st.caption("Sent = with customer + returned. Billed is the smaller of what the customer kept and the PO qty "
               "(indent qty when there is no PO). Red = the customer still holds more than the PO.")
    st.download_button("CSV", data=show.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"Dispatch_check_{d['day']}.csv", mime="text/csv", icon=":material/download:",
                       key="dr_csv")


def _return_card(iid: str, its: list[dict], d: dict, user: User) -> None:
    its = [it for it in its if d["sent"].get((iid, dd._n(it["customer_sku_name"])), 0.0) > 0]
    if not its:
        return
    rounds = d["r_rounds"].get(iid, [])
    head = its[0]
    with st.container(border=True, key=f"drcard_{iid}"):
        a, b = st.columns([3, 2])
        a.markdown(f'<span class="dd-t">{head["customer"]} · {head["store"]} · {iid}</span>', unsafe_allow_html=True)
        b.markdown(_chip(f"🔒 Returns in {_when(rounds[-1]['at'])} · {_who(rounds[-1]['by'])}", "done") if rounds
                   else _chip("Returns pending", "todo"), unsafe_allow_html=True)
        box = st.expander("Add more returns") if rounds else st.container()
        with box:
            w = [3, 1, 1, 1.1, 1.3, 1.8, 1.1, 1]
            _head(st.columns(w), ["Item", "PO qty" if head["has_po"] else "Indent qty", "Sent", "Returned so far",
                                  "Returned now", "Reason", "With customer", "Billed"])
            now, why, bad = {}, {}, False
            for i, it in enumerate(its):
                name = it["customer_sku_name"]
                key = (iid, dd._n(name))
                s, r0 = d["sent"].get(key, 0.0), d["back"].get(key, 0.0)
                c = st.columns(w, vertical_alignment="center")
                c[0].markdown(name)
                c[1].markdown(_g(it["asked"]) or "0")
                c[2].markdown(_g(s))
                c[3].markdown(_g(r0) or "0")
                q = c[4].number_input("Returned now", min_value=0.0, value=0.0, step=1.0, format="%g",
                                      label_visibility="collapsed", key=f"ddin_r_{iid}_{i}_{len(rounds)}") or 0.0
                now[name] = q
                why[name] = c[5].selectbox("Reason", dd.REASONS, label_visibility="collapsed",
                                           key=f"dr_why_{iid}_{i}_{len(rounds)}") if q else ""
                ck = dd.check(it["asked"], s, r0 + q, True)
                bad = bad or r0 + q > s + 1e-9
                c[6].markdown(_g(ck["with_customer"]) or "0")
                c[7].markdown(_chip(_g(ck["billed"]) or "0", "bad" if ck["over"] > 1e-9 or r0 + q > s + 1e-9 else "done"),
                              unsafe_allow_html=True)
            if bad:
                st.error("Returned can't be more than what was sent.")
            f = st.columns([1.8, 4])
            with f[0].popover("Save returns and lock", icon=":material/lock:", width="stretch", disabled=bad):
                st.markdown("Once saved, it **can't be changed**. Items left at 0 are saved as *nothing came back*.")
                if st.button("Yes, save returns", type="primary", key=f"drgo_{iid}_{len(rounds)}"):
                    try:
                        dd.save(get_backend(), DAY_RETURNS, dd.return_rows(its, now, why, d["day"], d["city"],
                                                                           user.email))
                        common.flash("success", f"{iid}: returns saved and locked.")
                        st.rerun()
                    except SheetError as e:
                        common.sheet_error(e, "Could not save the returns.")
