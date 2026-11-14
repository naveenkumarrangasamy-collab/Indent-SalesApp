"""Indent-level actions shared by the home screen and All indents:
Upload PO (freezes the indent) and Delete (marks it Cancelled)."""
from __future__ import annotations

import streamlit as st

from core import config, indents, mailer
from core.auth import User
from core.schema import STATUS_SUBMITTED
from core.sheets import SheetError, get_backend
from pages_src import common, state

KEY = "indent_action"   # (action, indent_id) while a dialog is open


def ask(action: str, indent_id: str) -> None:
    for k in ("pending_edit", "pending_remove", "pending_action", "review_open", "home_open", "mi_line"):
        st.session_state.pop(k, None)   # only one dialog at a time
    st.session_state[KEY] = (action, indent_id)
    st.rerun()


def _close() -> None:
    st.session_state.pop(KEY, None)


def _unsaved_here(indent_id: str) -> bool:
    ind = state.get()
    return ind["mode"] == "edit" and ind["indent_id"] == indent_id and state.changed_vs_base()


def _strip(cur) -> None:
    h = cur.header
    st.markdown(
        "<div class='mt-strip'>"
        f"<span><b>Indent</b>{cur.indent_id}</span><span><b>Delivery</b>{h.delivery_date}</span>"
        f"<span><b>Customer</b>{h.customer}</span><span><b>Store</b>{h.store}</span>"
        f"<span><b>Items</b>{len(cur.lines)}</span></div>", unsafe_allow_html=True)


@st.dialog("Upload PO", dismissible=False)
def _po_dialog(indent_id: str, user: User) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is None:
        _close()
        st.rerun()
    _strip(cur)
    blocked = ""
    if cur.status != STATUS_SUBMITTED:
        blocked = f"This indent is {cur.status.lower()}; a PO can only be added to a submitted indent."
    elif _unsaved_here(indent_id):
        blocked = ("You have unsaved changes to this indent on the Indent page. "
                   "Update or discard them first.")
    if blocked:
        st.warning(blocked)
        if st.button("Close", width="stretch"):
            _close()
            st.rerun()
        return
    to = ", ".join(mailer.settings()["to"])
    st.caption("Uploading the customer's PO freezes the indent: after confirming, it can no longer "
               f"be edited or deleted. The PDF is e-mailed to {to} with subject "
               f"'{cur.header.customer}'.")
    up = st.file_uploader("PO file (PDF)", type=["pdf"], key=f"po_file_{indent_id}")
    if up is not None:
        st.warning(f"Is **{up.name}** the PO for customer **{cur.header.customer}** and store "
                   f"**{cur.header.store}** (delivery {cur.header.delivery_date})?")
    b = st.columns(2)
    if b[0].button("Confirm and freeze", icon=":material/lock:", type="primary", width="stretch",
                   disabled=up is None):
        link, note = "", ""
        folder = config.po_drive_folder_id()
        backend = get_backend()
        if folder or backend.mode == "local":
            try:
                with st.spinner("Saving the PO file…"):
                    link = backend.upload_pdf(f"{indent_id} - {up.name}", up.getvalue(), folder)
            except SheetError as e:
                note = f" The file itself was not stored: {e}"
        try:
            with st.spinner("Freezing the indent…"):
                v = indents.freeze(indent_id, cur.version, up.name, user.email, po_file_link=link)
        except SheetError as e:
            st.error(f"Not frozen. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        with st.spinner("E-mailing the PO…"):
            sent, mail_msg = mailer.send_po_mail(cur, up.name, up.getvalue(), user.email)
        _close()
        common.flash("success", f"{indent_id} is frozen with PO {up.name} (version {v})." + note)
        common.flash("success" if sent else "warning", mail_msg)
        st.rerun()
    if b[1].button("Cancel", width="stretch"):
        _close()
        st.rerun()


@st.dialog("Delete indent?", dismissible=False)
def _delete_dialog(indent_id: str, user: User) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is None:
        _close()
        st.rerun()
    _strip(cur)
    st.write("The indent is marked **Cancelled**: it is removed from production and the store / "
             "delivery date becomes free for a new indent. All versions stay in the Google Sheet.")
    b = st.columns(2)
    if b[0].button("Yes, delete", icon=":material/delete:", type="primary", width="stretch"):
        try:
            with st.spinner("Deleting…"):
                indents.cancel(indent_id, cur.version, user.email)
        except SheetError as e:
            st.error(f"Not deleted. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        _close()
        common.flash("success", f"{indent_id} deleted (marked Cancelled).")
        st.rerun()
    if b[1].button("Cancel", width="stretch"):
        _close()
        st.rerun()


def show_dialog(user: User) -> None:
    """Call once per page run, after the page content."""
    action = st.session_state.get(KEY)
    if not action:
        return
    kind, indent_id = action
    (_po_dialog if kind == "po" else _delete_dialog)(indent_id, user)
