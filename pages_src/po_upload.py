"""Upload PO: every indent the user can see, waiting for a PO first.

Uploading the customer's PO (PDF) freezes the indent and e-mails the PDF
(see indent_actions._po_dialog). A PO can be added after the edit cutoff.
"""
from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from core import config, indents
from core.auth import User
from core.schema import STATUS_FROZEN, STATUS_SUBMITTED
from core.sheets import SheetError
from pages_src import common, indent_actions

SHOW = ["Waiting for PO", "PO done", "All"]


def _fmt_day(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%a %d %b}" if word else f"{d:%a %d %b %Y}"


def _po_info() -> dict[str, dict]:
    """Latest PO_Freeze row per indent."""
    try:
        po = indents.read_po_freeze()
    except SheetError:
        return {}
    if po is None or po.empty or "indent_id" not in po.columns:
        return {}
    out = {}
    for r in po.to_dict("records"):
        out[str(r.get("indent_id", ""))] = r
    return out


def _tile(label: str, value, sub: str = "", tone: str = "") -> str:
    return (f"<div class='mt-tile {tone}'><div class='lbl'>{escape(label)}</div>"
            f"<div class='val'>{value}</div><div class='sub'>{escape(sub)}</div></div>")


def _items_table(lines: pd.DataFrame, indent_id: str) -> None:
    rows = lines[lines["indent_id"] == indent_id] if not lines.empty else lines
    if rows.empty:
        st.caption("No items.")
        return
    show = rows[["customer_sku_name", "variety", "lot", "lot_size", "qty", "price", "amount"]].rename(
        columns={"customer_sku_name": "SKU", "variety": "Variety", "lot": "Lot", "lot_size": "Lot size",
                 "qty": "Qty", "price": "Price", "amount": "Amount"})
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption(f"{len(rows)} items · qty {rows['qty'].sum():,.0f} · ₹ {rows['amount'].sum():,.0f}")


def _card(r, lines: pd.DataFrame, po: dict, today: str) -> None:
    waiting = r.status == STATUS_SUBMITTED
    late = waiting and str(r.delivery_date) < today
    who = escape(str(r.created_by).split("@")[0])
    with st.container(border=True, key=f"mtcard_po_{r.indent_id}"):
        st.markdown(
            f"<div class='mt-card-head'><b>{escape(r.customer)}</b> · {escape(r.store)} "
            f"{common.badge(r.status)}</div>"
            f"<div class='mt-muted'>{'🔴 ' if late else ''}Delivery <b>{escape(_fmt_day(r.delivery_date))}</b>"
            f" · {escape(str(r.city))}</div>"
            f"<div class='mt-muted'><span class='mt-id'>{escape(r.indent_id)}</span> · by {who} · "
            f"<b>₹ {r.total_amount:,.0f}</b></div>", unsafe_allow_html=True)
        if not waiting:
            p = po.get(r.indent_id, {})
            name = str(p.get("po_file_name", "") or "PO")
            link = str(p.get("po_file_link", "") or "")
            when = str(p.get("confirmed_at", ""))[:16].replace("T", " ")
            by = escape(str(p.get("confirmed_by", "")).split("@")[0])
            shown = escape(name)
            label = f"<a href='{escape(link)}' target='_blank'>{shown}</a>" if link.startswith("http") else shown
            st.markdown(f"<div class='mt-muted'>✅ PO {label} · {escape(when)}{' · ' + by if by else ''}</div>",
                        unsafe_allow_html=True)
        c = st.columns(2)
        with c[0].popover(f"{r.lines} item{'s' if r.lines != 1 else ''}", icon=":material/list:", width="stretch"):
            st.markdown(f"**{r.indent_id}** · {r.customer} · {r.store} · delivery {r.delivery_date}")
            _items_table(lines, r.indent_id)
        if waiting:
            if c[1].button("Upload PO", icon=":material/upload_file:", key=f"po_up_{r.indent_id}",
                           type="primary", width="stretch"):
                indent_actions.ask("po", r.indent_id)
        else:
            c[1].button("PO done", icon=":material/lock:", key=f"po_dn_{r.indent_id}",
                        disabled=True, width="stretch")


def render(user: User) -> None:
    _page(user)


@st.fragment
def _page(user: User) -> None:
    """Upload PO page body as a fragment: its toggles and filters rerun only this
    part, not the whole app (faster, smoother). st.rerun() inside still
    reruns the whole app when a full refresh is needed."""
    common.show_flash()
    try:
        df = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    summ = indents.visible_to(indents.summary(df), user)
    summ = summ[summ["status"].isin([STATUS_SUBMITTED, STATUS_FROZEN])] if not summ.empty else summ
    lines = indents.current_rows(df) if not df.empty else pd.DataFrame(columns=["indent_id"])
    po = _po_info()

    head = st.columns([3, 1.2], vertical_alignment="bottom")
    head[0].markdown("### Upload PO")
    head[0].caption("Check each indent and upload the customer's PO (PDF). Uploading freezes the indent "
                    "and e-mails the PDF. A PO can be added even after the edit cutoff. "
                    f"Showing {indents.scope_text(user)}.")
    if head[1].button("Create indent", icon=":material/add_circle:", width="stretch"):
        st.switch_page(common.PAGES["indent"])

    if summ.empty:
        st.info("No indents yet. Indents appear here as soon as they are submitted.")
        indent_actions.show_dialog(user)
        return

    waiting = summ[summ["status"] == STATUS_SUBMITTED]
    done = summ[summ["status"] == STATUS_FROZEN]
    today = config.now_ist().date().isoformat()
    overdue = waiting[waiting["delivery_date"].astype(str) < today]
    st.markdown("<div class='mt-tiles'>" + "".join([
        _tile("Waiting for PO", len(waiting), "indents to upload", "warn" if len(waiting) else "good"),
        _tile("Past delivery date", len(overdue), "still without a PO", "bad" if len(overdue) else ""),
        _tile("PO done", len(done), "frozen", "good"),
    ]) + "</div>", unsafe_allow_html=True)

    # ---- filters
    show = st.segmented_control("Show", SHOW, default=SHOW[0], key="po_show", required=True) or SHOW[0]
    base = {"Waiting for PO": waiting, "PO done": done, "All": summ}[show]

    f = st.columns([1, 1, 1.2])
    days = sorted(set(base["delivery_date"].astype(str)), reverse=True)
    day = f[0].selectbox("Delivery date", ["All dates"] + days, key="po_day",
                         format_func=lambda d: d if d == "All dates" else _fmt_day(d))
    cities = sorted(set(base["city"].astype(str)))
    city = f[1].selectbox("City", ["All cities"] + cities, key="po_city") if len(cities) > 1 else None
    find = f[2].text_input("Search store or indent", key="po_find", placeholder="e.g. Nelamangala or IN-012")

    rows = base
    if day != "All dates":
        rows = rows[rows["delivery_date"].astype(str) == day]
    if city and city != "All cities":
        rows = rows[rows["city"] == city]
    custs = sorted(set(rows["customer"].astype(str)))
    if len(custs) > 1:
        cust = st.pills("Customer", ["All customers"] + custs, default="All customers", key="po_cust")
        if cust and cust != "All customers":
            rows = rows[rows["customer"] == cust]
    if find.strip():
        q = find.strip().casefold()
        rows = rows[rows["store"].str.casefold().str.contains(q, regex=False)
                    | rows["indent_id"].str.casefold().str.contains(q, regex=False)]

    if rows.empty:
        st.caption("Nothing matches these filters." if show != "Waiting for PO"
                   else "No indents are waiting for a PO here. 🎉")
        indent_actions.show_dialog(user)
        return

    # waiting first, oldest delivery first; done newest first
    rows = rows.assign(_w=(rows["status"] != STATUS_SUBMITTED).astype(int),
                       _d=rows["delivery_date"].astype(str))
    rows = pd.concat([rows[rows["_w"] == 0].sort_values(["_d", "customer", "store"]),
                      rows[rows["_w"] == 1].sort_values(["_d", "customer", "store"],
                                                        ascending=[False, True, True])])

    from pages_src import bulk_download
    bulk_download.render(user, df, list(rows["indent_id"]), "po_bulk", po)
    recs = list(rows.itertuples())
    for i in range(0, len(recs), 2):
        pair = st.columns(2)
        for col, r in zip(pair, recs[i:i + 2]):
            with col:
                _card(r, lines, po, today)

    indent_actions.show_dialog(user)
