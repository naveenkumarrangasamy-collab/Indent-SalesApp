"""Home: a one-screen summary of today's / tomorrow's indents.

Buttons for Create indent and Upload PO, three tiles (indents, PO uploaded,
waiting for PO), and one single-line row per customer that has an indent,
with its status: green = PO uploaded for every store, yellow = waiting for
PO. Customers without an indent are not listed. The list scrolls inside a
fixed box so the page fits one laptop or phone screen.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import streamlit as st

from core import config, indents
from core.auth import User
from core.schema import STATUS_FROZEN, STATUS_SUBMITTED
from core.sheets import SheetError
from pages_src import common, indent_actions


def _fmt_day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%d %b}" if word else f"{d:%a %d %b}"


def _tile(label: str, value, sub: str = "", tone: str = "") -> str:
    return (f"<div class='mt-tile {tone}'><div class='lbl'>{escape(label)}</div>"
            f"<div class='val'>{value}</div><div class='sub'>{escape(sub)}</div></div>")


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

    # ---- one aligned row: title · delivery day · Create indent · Upload PO
    days = [(today + timedelta(days=k)).isoformat() for k in (0, 1)]
    k = "home_day"
    if k not in st.session_state or st.session_state[k] not in days:
        st.session_state[k] = today.isoformat()
    rows_all = summ
    waiting_all = int((summ["status"] == STATUS_SUBMITTED).sum()) if not summ.empty else 0
    with st.container(key="mtbar_home"):
        c = st.columns([1.5, 1.7, 1, 1], vertical_alignment="center", gap="small")
        c[0].markdown(f"<div class='mt-h'>Daily operations<span>{escape(indents.scope_text(user))}</span></div>",
                      unsafe_allow_html=True)
        day = c[1].segmented_control("Delivery day", days, key=k, format_func=_fmt_day, required=True,
                                     label_visibility="collapsed") or today.isoformat()
        if c[2].button("Create indent", icon=":material/add_circle:", type="primary", width="stretch"):
            st.switch_page(common.PAGES["indent"])
        if c[3].button(f"Upload PO · {waiting_all}" if waiting_all else "Upload PO",
                       icon=":material/upload_file:", type="primary", width="stretch", key="home_po_btn",
                       help="Indents waiting for a PO, and the PO upload"):
            st.switch_page(common.PAGES["po"])
    cities = sorted(set(rows_all["city"].astype(str))) if not rows_all.empty else []
    city = None
    if len(cities) > 1:
        city = st.pills("City", ["All cities"] + cities, default="All cities", key="home_city",
                        label_visibility="collapsed")
    rows = rows_all[rows_all["delivery_date"].astype(str) == day] if not rows_all.empty else rows_all
    if city and city != "All cities":
        rows = rows[rows["city"] == city]

    if rows.empty:
        st.info(f"No indents for {_fmt_day(day)} yet.")
        indent_actions.show_dialog(user)
        return

    done = int((rows["status"] == STATUS_FROZEN).sum())
    waiting = int((rows["status"] == STATUS_SUBMITTED).sum())
    n = len(rows)
    st.markdown("<div class='mt-tiles k3'>" + "".join([
        _tile("Indents", n, f"{rows['customer'].nunique()} customer(s)", "info"),
        _tile("PO uploaded", done, "done", "good"),
        _tile("Waiting for PO", waiting, "no PO yet", "warn" if waiting else ""),
    ]) + "</div>"
        f"<div class='mt-bar'><span style='width:{done / n * 100:.2f}%;background:#2da44e'></span>"
        f"<span style='width:{waiting / n * 100:.2f}%;background:#e3b341'></span></div>",
        unsafe_allow_html=True)

    # ---- one line per customer with an indent; the list scrolls inside its box
    groups = list(rows.groupby(["customer", "city"], sort=True))
    # customers still waiting first
    groups.sort(key=lambda g: (int((g[1]["status"] == STATUS_SUBMITTED).sum()) == 0, str(g[0][0]).casefold()))
    html = []
    for (cust, c_city), part in groups:
        d = int((part["status"] == STATUS_FROZEN).sum())
        w = int((part["status"] == STATUS_SUBMITTED).sum())
        stores = len(part)
        tip = escape("; ".join(f"{r.store}: {'PO uploaded' if r.status == STATUS_FROZEN else 'waiting for PO'}"
                               for r in part.itertuples()))
        state = ("<span class='st done'>PO uploaded</span>" if w == 0
                 else f"<span class='st open'>Waiting for PO · {w}</span>")
        html.append(f"<div class='mt-line {'done' if w == 0 else 'open'}' title='{tip}'>"
                    f"<span class='nm'><b>{escape(cust)}</b> <span class='ct'>· {escape(c_city)}</span></span>"
                    f"<span class='cnt'>{d}/{stores} PO</span>{state}</div>")
    with st.container(height=_list_height(len(groups)), key="mt_home_list", border=False):
        st.markdown("".join(html), unsafe_allow_html=True)
    indent_actions.show_dialog(user)


def _list_height(n: int) -> int:
    """Rows are ~46 px; the box never grows past ~6 rows, then it scrolls."""
    return max(60, min(n, 6) * 46 + 8)
