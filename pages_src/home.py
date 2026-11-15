"""Home: today's / tomorrow's indents at a glance.

Only customers with an indent that day are listed, one compact row each,
with a chip per store: green = PO uploaded, yellow = indent placed, PO not
uploaded yet. Indents waiting for a PO are listed below with Edit / Upload PO.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import streamlit as st

from core import config, indents
from core.auth import User
from core.schema import STATUS_SUBMITTED
from core.sheets import SheetError
from pages_src import common, indent_actions, state



def _fmt_day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%a %d %b}" if word else f"{d:%a %d %b}"


def _open(indent_id: str) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is not None:
        state.open_for_edit(cur, None, created_at=indents.created_at(df, indent_id))
        common.flash("info", f"{indent_id} opened for editing. Change what you need, then press Update indent.")


@st.dialog("Replace the form?", dismissible=False)
def _confirm_open(indent_id: str) -> None:
    st.write(f"You have unsaved entries on the Indent page. Opening **{indent_id}** will replace them.")
    c = st.columns(2)
    if c[0].button("Open " + indent_id, type="primary", width="stretch"):
        st.session_state.pop("home_open", None)
        _open(indent_id)
        st.switch_page(common.PAGES["indent"])
    if c[1].button("Cancel", width="stretch"):
        st.session_state.pop("home_open", None)
        st.rerun()


def _tile(label: str, value, sub: str = "", tone: str = "") -> str:
    return (f"<div class='mt-tile {tone}'><div class='lbl'>{escape(label)}</div>"
            f"<div class='val'>{value}</div><div class='sub'>{escape(sub)}</div></div>")


def _act_card(r, ind) -> None:
    ok = bool(r.can_edit)
    frozen = r.status in ("Frozen", "Cancelled")
    why = ("Deleted" if r.status == "Cancelled" else "Frozen with a PO") if frozen \
        else f"Editing closed at {indents.deadline_text(r.delivery_date)}"
    with st.container(border=True, key=f"mtcard_hm_{r.indent_id}"):
        st.markdown(
            f"<div class='mt-card-head'><b>{escape(r.customer)}</b> · {escape(r.store)} "
            f"{common.badge(r.status)}</div>"
            f"<div class='mt-muted'><span class='mt-id'>{escape(r.indent_id)}</span> · {int(r.lines)} item{'s' if int(r.lines) != 1 else ''} · "
            f"₹ {r.total_amount:,.0f}</div>", unsafe_allow_html=True)
        c = st.columns(2)
        editing = ind["mode"] == "edit" and ind["indent_id"] == r.indent_id
        if c[0].button("Edit", icon=":material/edit:", key=f"hm_e_{r.indent_id}",
                       disabled=not ok, width="stretch", help=None if ok else why):
            if state.has_unsaved_work() and not editing:
                st.session_state["home_open"] = r.indent_id
                st.rerun()
            if not editing:
                _open(r.indent_id)
            st.switch_page(common.PAGES["indent"])
        if c[1].button("Upload PO" if not frozen else "PO done", icon=":material/upload_file:",
                       key=f"hm_p_{r.indent_id}", disabled=frozen, width="stretch",
                       type="primary" if not frozen else "secondary",
                       help="Upload the customer's PO (PDF) and freeze this indent"):
            indent_actions.ask("po", r.indent_id)


def render(user: User) -> None:
    common.show_flash()
    try:
        df = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Data could not be loaded.")
        return

    summ = indents.visible_to(indents.summary(df), user)
    summ = summ[summ["status"] != "Cancelled"] if not summ.empty else summ
    today = config.now_ist().date()

    head = st.columns([3, 1.2, 1.2], vertical_alignment="bottom")
    head[0].markdown("### Daily operations")
    head[0].caption(f"Indents placed and their PO status · {indents.scope_text(user)}.")
    if head[1].button("Create indent", icon=":material/add_circle:", type="primary", width="stretch"):
        st.switch_page(common.PAGES["indent"])
    waiting_all = int((summ["status"] == STATUS_SUBMITTED).sum()) if not summ.empty else 0
    if head[2].button(f"Upload PO · {waiting_all} waiting" if waiting_all else "Upload PO",
                      icon=":material/upload_file:", type="primary", width="stretch", key="home_po_btn",
                      help="See every indent and upload the customer's PO"):
        st.switch_page(common.PAGES["po"])

    # ---- delivery day (today / tomorrow) and city
    days = [(today + timedelta(days=k)).isoformat() for k in (0, 1)]
    k = "home_day"
    if k not in st.session_state or st.session_state[k] not in days:
        st.session_state[k] = today.isoformat()
    day = st.segmented_control("Delivery day", days, key=k, format_func=_fmt_day, required=True) \
        or today.isoformat()
    rows = summ[summ["delivery_date"].astype(str) == day] if not summ.empty else summ
    cities = sorted(set(rows["city"].astype(str))) if not rows.empty else []
    if len(cities) > 1:
        city = st.pills("City", ["All cities"] + cities, default="All cities", key="home_city")
        if city and city != "All cities":
            rows = rows[rows["city"] == city]

    if rows.empty:
        st.info(f"No indents for {_fmt_day(day)} yet.")
        indent_actions.show_dialog(user)
        return

    done = rows[rows["status"] == "Frozen"]
    open_ = rows[rows["status"] == STATUS_SUBMITTED]
    cur = indents.current_rows(df)
    cur = cur[cur["indent_id"].isin(set(rows["indent_id"]))]
    qty = int(cur["qty"].sum()) if not cur.empty else 0
    st.markdown("<div class='mt-tiles'>" + "".join([
        _tile("Indents", len(rows), f"{rows['customer'].nunique()} customer(s)", "info"),
        _tile("PO uploaded", len(done), "ready to dispatch", "good"),
        _tile("Waiting for PO", len(open_), "indent placed, no PO yet", "warn" if len(open_) else ""),
        _tile("Qty (lots)", f"{qty:,}", f"{len(cur)} lines"),
    ]) + "</div>", unsafe_allow_html=True)
    n = len(rows)
    st.markdown(f"<div class='mt-bar'><span style='width:{len(done) / n * 100:.2f}%;background:#2da44e'></span>"
                f"<span style='width:{len(open_) / n * 100:.2f}%;background:#e3b341'></span></div>",
                unsafe_allow_html=True)

    # ---- one compact row per customer (only customers with an indent)
    st.markdown("<div class='mt-legend'><span class='mt-chip done'>PO uploaded</span>"
                "<span class='mt-chip open'>waiting for PO</span></div>", unsafe_allow_html=True)
    html = []
    for (cust, c_city), part in rows.groupby(["customer", "city"], sort=True):
        part = part.sort_values(by=["status", "store"], key=lambda s: s.map({"Frozen": 1}).fillna(0)
                                if s.name == "status" else s.astype(str).str.casefold())
        d, w = int((part["status"] == "Frozen").sum()), int((part["status"] == STATUS_SUBMITTED).sum())
        chips = "".join(
            f"<span class='mt-chip {'done' if r.status == 'Frozen' else 'open'}' "
            f"title='{escape(r.indent_id)} · {'PO uploaded' if r.status == 'Frozen' else 'waiting for PO'}'>"
            f"{escape(r.store)}</span>" for r in part.itertuples())
        state_cls = "done" if w == 0 else "open"
        html.append(
            f"<div class='mt-crow {state_cls}'><div class='who'><b>{escape(cust)}</b>"
            f"<span class='mt-muted'> · {escape(c_city)}</span></div>"
            f"<div class='cnt'><span class='g'>{d} PO</span> · <span class='y'>{w} waiting</span></div>"
            f"<div class='chips'>{chips}</div></div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    # ---- indents still waiting for a PO, with their actions
    if not open_.empty:
        st.markdown("**Waiting for PO**")
        ind = state.get()
        recs = list(indents.open_first(open_, then=["customer", "store"], ascending=[True, True]).itertuples())
        for i in range(0, len(recs), 2):
            pair = st.columns(2)
            for col, r in zip(pair, recs[i:i + 2]):
                with col:
                    _act_card(r, ind)

    if st.session_state.get("home_open"):
        _confirm_open(st.session_state["home_open"])
    else:
        indent_actions.show_dialog(user)
