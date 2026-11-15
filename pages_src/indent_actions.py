"""Indent-level actions shared by the home screen and All indents:
Upload PO (freezes the indent) and Delete (marks it Cancelled)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, indents, mailer
from core.auth import User
from core.models import fmt_num
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


def _prefill(indent_id: str) -> dict:
    return st.session_state.setdefault("po_prefill", {}).setdefault(indent_id, {})


def _clear_po_state(indent_id: str) -> None:
    st.session_state.get("po_prefill", {}).pop(indent_id, None)
    st.session_state.get("po_files", {}).pop(indent_id, None)
    st.session_state.pop("po_mismatch", None)


@st.dialog("Upload PO", dismissible=False, width="large")
def _po_dialog(indent_id: str, user: User) -> None:
    df = indents.read_lines()
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
    pre = _prefill(indent_id)

    # 1. the PO file (kept while the indent is being corrected)
    c = st.columns([1, 1.6])
    po_number = c[0].text_input("PO number", value=pre.get("po_number", ""), key=f"po_no_{indent_id}",
                                placeholder="as printed on the PO")
    up = c[1].file_uploader("PO file (PDF)", type=["pdf"], key=f"po_file_{indent_id}")
    files = st.session_state.setdefault("po_files", {})   # kept while the indent is corrected
    if up is not None:
        files[indent_id] = (up.name, up.getvalue())
    elif indent_id in files:
        c[1].caption(f"Using **{files[indent_id][0]}** chosen earlier (choose another file to replace it).")
    file_name, file_bytes = files.get(indent_id, (None, None))

    # 2. PO quantities, item by item
    st.markdown("**Quantities on the PO** · type each item's qty exactly as on the customer's PO")
    if "init" not in pre:   # what the table starts with; fixed while the dialog is open
        pre["init"] = dict(pre.get("po_qty", {}))
        st.session_state["po_ed_rev"] = pre["rev"] = st.session_state.get("po_ed_rev", 0) + 1
    saved = pre["init"]
    base = pd.DataFrame([{"Customer SKU Name": x.customer_sku_name, "Lot": x.lot,
                          "Indent qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                          "PO qty": saved.get(x.customer_sku_name)} for x in cur.lines])
    base["PO qty"] = pd.to_numeric(base["PO qty"], errors="coerce")
    ed = st.data_editor(base, key=f"po_ed_{indent_id}_{pre.get('rev', 0)}", hide_index=True, width="stretch",
                        disabled=["Customer SKU Name", "Lot", "Indent qty"],
                        column_config={"PO qty": st.column_config.NumberColumn(min_value=0, step=1,
                                                                               format="%d")})
    po_qty = {r["Customer SKU Name"]: (None if pd.isna(r["PO qty"]) else float(r["PO qty"]))
              for r in ed.to_dict("records")}
    pre["po_qty"], pre["po_number"] = po_qty, po_number
    extra = st.checkbox("The PO has items that are not in this indent", key=f"po_extra_{indent_id}")
    cmp = indents.po_compare(cur.lines, po_qty)
    missing = [r for r in cmp if r["po_qty"] is None]
    bad = [r for r in cmp if r["po_qty"] is not None and not r["ok"]]
    tot_i = sum(r["indent_qty"] for r in cmp)
    tot_p = sum(r["po_qty"] or 0 for r in cmp)
    st.caption(f"Indent total **{fmt_num(tot_i)}** · PO total entered **{fmt_num(tot_p)}**"
               + (f" · {len(missing)} item(s) still to enter" if missing else ""))

    # 3. mismatch: cannot upload, correct the indent first
    if st.session_state.get("po_mismatch") == indent_id and (bad or extra):
        with st.container(border=True, key="mt_po_mismatch"):
            st.error("**The PO does not match the indent, so it cannot be uploaded.** "
                     "Edit the indent so every item matches the PO, then upload again.")
            if bad:
                st.dataframe(pd.DataFrame([{
                    "Customer SKU Name": r["customer_sku_name"], "Indent qty": fmt_num(r["indent_qty"]),
                    "PO qty": fmt_num(r["po_qty"]),
                    "Difference": ("+" if r["diff"] > 0 else "") + fmt_num(r["diff"])} for r in bad]),
                    hide_index=True, width="stretch")
            if extra:
                st.markdown("- The PO has items that are not in this indent: add them with **Add item**.")
            b = st.columns(2)
            if b[0].button("Edit indent to match PO", icon=":material/edit:", type="primary",
                           width="stretch"):
                fix = {"po_qty": {k: v for k, v in po_qty.items() if v is not None},
                       "po_number": po_number}
                state.open_for_edit(cur, None, created_at=indents.created_at(df, indent_id), po_fix=fix)
                st.session_state.pop("po_mismatch", None)
                _close()
                common.flash("warning", f"{indent_id}: change the items to match the PO, then press "
                                        "**Update indent**.")
                st.switch_page(common.PAGES["indent"])
            if b[1].button("Close", width="stretch"):
                st.session_state.pop("po_mismatch", None)
                _close()
                st.rerun()
        return

    to = ", ".join(mailer.po_recipients(cur.header))
    st.caption("Uploading freezes the indent: it can no longer be edited. The SO / PO e-mail goes at "
               f"once to {to or 'nobody yet (add recipients on the Access page)'}.")
    b = st.columns(2)
    if b[0].button("Check and upload", icon=":material/fact_check:", type="primary", width="stretch",
                   disabled=not file_bytes or bool(missing)):
        if bad or extra:
            st.session_state["po_mismatch"] = indent_id
            st.rerun()
        link, note = "", ""
        folder = config.po_drive_folder_id()
        backend = get_backend()
        if folder or backend.mode == "local":
            try:
                with st.spinner("Saving the PO file…"):
                    link = backend.upload_pdf(f"{indent_id} - {file_name}", file_bytes, folder)
            except SheetError as e:
                note = f" The file itself was not stored: {e}"
        try:
            with st.spinner("Checking and freezing the indent…"):
                v = indents.freeze(indent_id, cur.version, file_name, user.email, po_file_link=link,
                                   po_qty={k: v for k, v in po_qty.items() if v is not None},
                                   po_number=po_number.strip(), po_has_extra=extra)
        except indents.POMismatchError:
            st.session_state["po_mismatch"] = indent_id
            indents.clear_cache()
            st.rerun()
        except SheetError as e:
            st.error(f"Not frozen. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        frozen = indents.snapshot(indents.read_lines(fresh=True), indent_id) or cur
        with st.spinner("E-mailing the SO / PO…"):
            sent, mail_msg = mailer.send_so_mail(frozen, file_name, file_bytes, user.email,
                                                 po_number=po_number.strip())
        _clear_po_state(indent_id)
        _close()
        common.flash("success", f"{indent_id} is frozen with PO {po_number or file_name} (version {v})." + note)
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
