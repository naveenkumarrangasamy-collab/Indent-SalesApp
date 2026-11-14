"""My indents: list, open, correct, version history, PO freeze."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core import indents
from core.auth import User
from core.schema import STATUS_FROZEN
from core.sheets import SheetError
from pages_src import common, state

MAX_VERSIONS_SHOWN = 10


def fmt_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(iso)


def _open_in_form(cur, load=None) -> None:
    state.open_for_edit(cur, load)
    v = f" (copied from version {load.version})" if load is not None and load.version != cur.version else ""
    common.flash("info", f"{cur.indent_id} loaded for correction{v}. Change what you need, then press "
                         "Update indent.")
    st.switch_page(common.PAGES["indent"])


def _request_open(cur, load=None) -> None:
    """Ask before replacing unsaved work in the Indent form."""
    ind = state.get()
    same = ind["mode"] == "edit" and ind["indent_id"] == cur.indent_id
    if state.has_unsaved_work() and not (same and load is None):
        st.session_state["mi_confirm"] = (cur.indent_id, load.version if load is not None else None)
        st.rerun()
    if same and load is None:
        st.switch_page(common.PAGES["indent"])
    _open_in_form(cur, load)


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### All indents" if user.is_owner else "### My indents")
    try:
        df = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    summ = indents.summary(df)
    if not user.is_owner:
        summ = summ[summ["created_by"].str.lower() == user.email]
    if summ.empty:
        st.info("No submitted indents yet.")
        return

    f = st.columns([2, 1, 1, 1])
    q = f[0].text_input("Search", placeholder="Indent id, store, customer…", label_visibility="collapsed")
    status = f[1].selectbox("Status", ["All", "Submitted", "Frozen"], label_visibility="collapsed")
    cities = ["All cities"] + sorted(summ["city"].unique())
    city = f[2].selectbox("City", cities, label_visibility="collapsed")
    dates = ["All dates"] + sorted(summ["delivery_date"].unique(), reverse=True)
    ddate = f[3].selectbox("Delivery date", dates, label_visibility="collapsed")

    view = summ
    if q:
        ql = q.lower()
        view = view[view.apply(lambda r: ql in " ".join(map(str, r.values)).lower(), axis=1)]
    if status != "All":
        view = view[view["status"] == status]
    if city != "All cities":
        view = view[view["city"] == city]
    if ddate != "All dates":
        view = view[view["delivery_date"] == ddate]

    show = pd.DataFrame({
        "Indent": view["indent_id"], "Status": view["status"], "Ver": view["version"],
        "Delivery": view["delivery_date"], "City": view["city"], "Customer": view["customer"],
        "Store": view["store"], "Items": view["lines"], "Amount": view["total_amount"],
        "Last edited": view["last_edited_at"].map(fmt_ts), "By": view["last_edited_by"],
    })
    if user.is_owner:
        show["Created by"] = view["created_by"].values
    st.caption(f"{len(view)} indent(s). Click a row to open it.")
    sel = st.dataframe(show, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="single-row", key="mi_table",
                       column_config={"Amount": st.column_config.NumberColumn(format="%.2f")})
    rows = sel.selection.rows if sel and sel.selection else []
    if rows:
        st.session_state["mi_open"] = show.iloc[rows[0]]["Indent"]
    open_id = st.session_state.get("mi_open")
    if open_id and open_id in set(summ["indent_id"]):
        st.divider()
        _detail(df, open_id, user)


def _detail(df: pd.DataFrame, indent_id: str, user: User) -> None:
    cur = indents.snapshot(df, indent_id)
    if cur is None:
        return
    h = cur.header
    st.markdown(f"#### {indent_id} &nbsp; {common.badge(cur.status)} &nbsp; "
                f"<span class='mt-muted'>version {cur.version}</span>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mt-strip'>"
        f"<span><b>Date</b>{h.delivery_date}</span><span><b>City</b>{h.city}</span>"
        f"<span><b>Customer</b>{h.customer}</span><span><b>Store</b>{h.store}</span>"
        f"<span><b>Time</b>{h.expected_time}</span>"
        f"<span><b>Last saved</b>{fmt_ts(cur.submitted_at)} by {cur.submitted_by}</span></div>",
        unsafe_allow_html=True)
    lines = pd.DataFrame([{"Parent SKU": x.parent_sku, "Customer SKU Name": x.customer_sku_name,
                           "Variety": x.variety, "Lot": x.lot, "Qty": x.qty, "Price": x.price,
                           "Amount": x.amount} for x in cur.lines])
    if not lines["Variety"].astype(bool).any():
        lines = lines.drop(columns=["Variety"])
    st.dataframe(lines, hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                "Price": st.column_config.NumberColumn(format="%.2f"),
                                "Amount": st.column_config.NumberColumn(format="%.2f")})
    st.caption(f"Total amount ₹ {cur.total_amount:,.2f}")

    frozen = cur.status == STATUS_FROZEN
    confirm = st.session_state.get("mi_confirm")
    if confirm and confirm[0] == indent_id:
        load_v = confirm[1]
        st.warning("You have unsaved work on the Indent page. Opening this indent will replace it.")
        c = st.columns([1, 1, 3])
        if c[0].button("Replace and open", type="primary"):
            st.session_state.pop("mi_confirm", None)
            _open_in_form(cur, indents.snapshot(df, indent_id, load_v) if load_v else None)
        if c[1].button("Keep my work"):
            st.session_state.pop("mi_confirm", None)
            st.rerun()
    elif not frozen:
        if st.button("✏️ Correct this indent", type="primary"):
            _request_open(cur)
    else:
        st.info("This indent is frozen with a PO and is read-only.")

    tabs = st.tabs(["Versions", "Change log", "PO & freeze"])
    with tabs[0]:
        _versions(df, cur, frozen)
    with tabs[1]:
        _change_log(indent_id)
    with tabs[2]:
        _po(cur, user)


def _versions(df: pd.DataFrame, cur, frozen: bool) -> None:
    vers = indents.versions(df, cur.indent_id)
    total = len(vers)
    vers = vers.head(MAX_VERSIONS_SHOWN)
    head = st.columns([0.6, 1, 1.6, 2.2, 0.6, 1, 0.9])
    for col, label in zip(head, ["Ver", "Status", "Saved at", "By", "Items", "Amount", ""]):
        col.markdown(f"<span class='mt-muted'>{label}</span>", unsafe_allow_html=True)
    for _, v in vers.iterrows():
        c = st.columns([0.6, 1, 1.6, 2.2, 0.6, 1, 0.9])
        c[0].write(f"v{v['version']}")
        c[1].write(v["status"])
        c[2].write(fmt_ts(v["submitted_at"]))
        c[3].write(v["submitted_by"])
        c[4].write(str(v["lines"]))
        c[5].write(f"{v['amount']:,.2f}")
        if c[6].button("Load", key=f"load_{cur.indent_id}_{v['version']}", disabled=frozen,
                       help="Copy this version into the form. It is saved only when you press Update."):
            _request_open(cur, indents.snapshot(df, cur.indent_id, int(v["version"])))
    if total > MAX_VERSIONS_SHOWN:
        st.caption(f"Showing the last {MAX_VERSIONS_SHOWN} of {total} versions. All versions stay in the sheet.")


def _change_log(indent_id: str) -> None:
    try:
        log = indents.read_change_log()
    except SheetError as e:
        common.sheet_error(e)
        return
    log = log[log["indent_id"] == indent_id]
    if log.empty:
        st.caption("No changes recorded yet (version 1 only).")
        return
    show = pd.DataFrame({
        "When": log["changed_at"].map(fmt_ts), "From→To": "v" + log["from_version"] + "→v" + log["to_version"],
        "By": log["changed_by"], "Change": log["change_type"].str.replace("_", " "),
        "SKU": log["customer_sku_name"], "Field": log["field"],
        "Old": log["old_value"], "New": log["new_value"]}).iloc[::-1]
    st.dataframe(show, hide_index=True, width="stretch")


def _po(cur, user: User) -> None:
    s = st.session_state
    if cur.status == STATUS_FROZEN:
        try:
            po = indents.read_po_freeze()
            po = po[po["indent_id"] == cur.indent_id]
        except SheetError:
            po = pd.DataFrame()
        if not po.empty:
            r = po.iloc[-1]
            st.success(f"Frozen with PO **{r['po_file_name']}** for {r['po_customer']} / {r['po_store']}, "
                       f"confirmed by {r['confirmed_by']} on {fmt_ts(r['confirmed_at'])}.")
        else:
            st.success("Frozen with a PO.")
        return

    ind = state.get()
    if ind["mode"] == "edit" and ind["indent_id"] == cur.indent_id and state.changed_vs_base():
        st.warning("You have unsaved changes to this indent on the Indent page. "
                   "Update or discard them before uploading the PO.")
        return

    rev = s.get(f"po_rev_{cur.indent_id}", 0)
    up = st.file_uploader("Upload the customer PO to freeze this indent",
                          type=["pdf", "png", "jpg", "jpeg", "xlsx", "xls", "csv"],
                          key=f"po_{cur.indent_id}_{rev}")
    if up is None:
        st.caption("After the PO is confirmed, the indent becomes read-only. "
                   "Only the PO file name is stored.")
        return
    st.warning(f"Is the selected PO (**{up.name}**) for customer **{cur.header.customer}** "
               f"and store **{cur.header.store}**?")
    c = st.columns([1, 1, 3])
    if c[0].button("Confirm", type="primary", key=f"po_ok_{cur.indent_id}"):
        with st.spinner("Freezing…"):
            try:
                v = indents.freeze(cur.indent_id, cur.version, up.name, user.email)
            except SheetError as e:
                st.error(f"Not frozen. {e}")
                return
        if ind["mode"] == "edit" and ind["indent_id"] == cur.indent_id:
            state.start_new()
        common.flash("success", f"{cur.indent_id} is frozen with PO {up.name} (version {v}).")
        st.rerun()
    if c[1].button("Cancel", key=f"po_cancel_{cur.indent_id}"):
        s[f"po_rev_{cur.indent_id}"] = rev + 1
        st.rerun()
