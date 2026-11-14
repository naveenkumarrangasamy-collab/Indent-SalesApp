"""My indents: list, open, correct, version history, PO freeze."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from core import indents, masters
from core.lots import lot_size
from core.models import IndentLine, to_number
from core.auth import User
from core.schema import STATUS_FROZEN
from core.sheets import SheetError
from pages_src import common, indent_actions, state

MAX_VERSIONS_SHOWN = 10


def fmt_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(iso)


def _open_in_form(cur, load=None) -> None:
    state.open_for_edit(cur, load, created_at=st.session_state.get("mi_created_at", ""))
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
    st.markdown("### All indents" if user.is_owner or user.city_scoped else "### My indents")
    if user.city_scoped:
        st.caption("Indents of every user in " + ", ".join(user.cities) + ". Open (not yet PO) indents are on top.")
    else:
        st.caption("Open (not yet PO) indents are on top; PO-frozen and deleted ones follow.")
    try:
        df = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    summ = indents.summary(df)
    summ = indents.visible_to(summ, user)
    if summ.empty:
        st.info("No submitted indents yet.")
        return

    f = st.columns([2, 1, 1, 1])
    q = f[0].text_input("Search", placeholder="Indent id, store, customer…", label_visibility="collapsed")
    status = f[1].selectbox("Status", ["All", "Submitted", "Frozen", "Cancelled"], label_visibility="collapsed")
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
        "Editable": view["can_edit"].map(lambda b: "yes" if b else "closed"),
    })
    if user.is_owner or user.city_scoped:
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
    cancelled = cur.status == "Cancelled"
    frozen = cur.status == STATUS_FROZEN or cancelled
    created = indents.created_at(df, indent_id)
    st.session_state["mi_created_at"] = created
    open_ = indents.can_edit(created)
    deadline = indents.edit_deadline(created).strftime("%d %b %Y, %I:%M %p") if created else ""
    why = (("Deleted" if cancelled else "Frozen with a PO") if frozen
           else f"Edit window closed at {deadline}") if (frozen or not open_) else ""
    _line_rows(cur, user, editable=open_ and not frozen, why=why)
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
    elif cancelled:
        st.info("This indent was deleted (Cancelled). It is kept here for history only.")
    else:
        c = st.columns([1.2, 1, 1, 2.6])
        can = open_ and not frozen
        if c[0].button("Edit whole indent", icon=":material/edit_note:", type="primary", disabled=not can,
                       help="Open the indent on the Indent page to change delivery details or add items"
                       if can else why):
            _request_open(cur)
        if c[1].button("Delete indent", icon=":material/delete:", disabled=not can,
                       help="Delete this indent (asks first)" if can else why):
            indent_actions.ask("delete", indent_id)
        if c[2].button("Upload PO", icon=":material/upload_file:", disabled=frozen,
                       help="Upload the customer's PO (PDF) and freeze this indent" if not frozen
                       else "PO already uploaded"):
            indent_actions.ask("po", indent_id)
        if frozen:
            c[3].caption("Frozen with a PO: read-only.")
        elif not open_:
            c[3].caption(f"Edit window closed at {deadline}. A PO can still be uploaded.")
        else:
            c[3].caption(f"Editable until **{deadline}**.")

    indent_actions.show_dialog(user)
    tabs = st.tabs(["Versions", "Change log", "PO"])
    with tabs[0]:
        _versions(df, cur, frozen or not open_)
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
        note = str(v.get("change_note", "") or "")
        if note:
            c[3].caption(note)
        if c[6].button("Load", icon=":material/history:", key=f"load_{cur.indent_id}_{v['version']}",
                       disabled=frozen,
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
    try:
        po = indents.read_po_freeze()
        po = po[po["indent_id"] == cur.indent_id]
    except SheetError:
        po = pd.DataFrame()
    if po.empty:
        st.caption("No PO yet. Use **Upload PO** above (or on the home screen) to add the customer's "
                   "PO as a PDF; that freezes the indent.")
        return
    r = po.iloc[-1]
    link = str(r.get("po_file_link", "") or "")
    st.success(f"Frozen with PO **{r['po_file_name']}** for {r['po_customer']} / {r['po_store']}, "
               f"confirmed by {r['confirmed_by']} on {fmt_ts(r['confirmed_at'])}.")
    if link.startswith("http"):
        st.link_button("Open PO file", link, icon=":material/picture_as_pdf:")


# ------------------------------------------------------------ per-line edit / delete

_W = [1.0, 2.5, 0.9, 0.6, 0.9, 0.6, 0.8, 0.9, 0.85, 0.95]


def _line_rows(cur, user: User, editable: bool, why: str = "") -> None:
    has_variety = any(x.variety for x in cur.lines)
    head = st.columns(_W)
    labels = ["Parent SKU", "Customer SKU Name", "Variety" if has_variety else "", "Lot", "Lot Size",
              "Qty", "Price", "Amount", "", ""]
    for col, label in zip(head, labels):
        col.markdown(f"<span class='mt-muted'>{label}</span>", unsafe_allow_html=True)
    for i, x in enumerate(cur.lines):
        c = st.columns(_W, vertical_alignment="center")
        c[0].write(x.parent_sku)
        c[1].write(x.customer_sku_name)
        c[2].write(x.variety if has_variety else "")
        c[3].write(x.lot)
        c[4].write(lot_size(x.customer_sku_name) or "—")
        c[5].markdown(f"<span class='num'>{int(x.qty) if float(x.qty).is_integer() else x.qty}</span>",
                      unsafe_allow_html=True)
        c[6].markdown(f"<span class='num'>{x.price:,.2f}</span>", unsafe_allow_html=True)
        c[7].markdown(f"<span class='num'>{x.amount:,.2f}</span>", unsafe_allow_html=True)
        if c[8].button("Edit", icon=":material/edit:", key=f"le_{cur.indent_id}_{i}",
                       disabled=not editable, width="stretch",
                       help="Edit qty, price or variety of this item" if editable else why):
            st.session_state.pop(indent_actions.KEY, None)
            st.session_state["mi_line"] = ("edit", cur.indent_id, cur.version, x.customer_sku_name)
            st.rerun()
        if c[9].button("Delete", icon=":material/delete:", key=f"ld_{cur.indent_id}_{i}",
                       disabled=not editable, width="stretch",
                       help="Remove this item from the indent" if editable else why):
            st.session_state.pop(indent_actions.KEY, None)
            st.session_state["mi_line"] = ("delete", cur.indent_id, cur.version, x.customer_sku_name)
            st.rerun()
    st.caption(f"{len(cur.lines)} item(s) · Total amount ₹ {cur.total_amount:,.2f}"
               + ("" if editable else " · read-only"))
    action = st.session_state.get("mi_line")
    if action and action[1] == cur.indent_id:
        if action[2] != cur.version:  # someone saved in between
            st.session_state.pop("mi_line", None)
            st.warning("This indent changed since you clicked; please try again.")
        elif action[0] == "edit":
            _edit_line_dialog(cur, action[3], user)
        else:
            _delete_line_dialog(cur, action[3], user)


def _save_lines(cur, new_lines: list[IndentLine], user: User, what: str) -> None:
    try:
        with st.spinner("Saving a new version…"):
            v, _ = indents.submit_update(cur.indent_id, cur.version, cur.header, new_lines, user.email)
    except indents.SheetError as e:
        st.error(f"Not saved. {e}")
        return
    st.session_state.pop("mi_line", None)
    common.flash("success", f"{what} {cur.indent_id} is now version {v}.")
    st.rerun()


@st.dialog("Edit item", dismissible=False)
def _edit_line_dialog(cur, name: str, user: User) -> None:
    line = next((x for x in cur.lines if x.customer_sku_name == name), None)
    if line is None:
        st.session_state.pop("mi_line", None)
        st.rerun()
    st.markdown(f"**{name}**  \n<span class='mt-muted'>{line.parent_sku} · lot {line.lot}"
                f"{' · ' + lot_size(name) if lot_size(name) else ''}</span>", unsafe_allow_html=True)
    try:
        varieties = masters.load_masters().varieties_for(line.parent_sku)
    except indents.SheetError:
        varieties = []
    variety = line.variety
    if varieties:
        opts = varieties if line.variety in varieties or not line.variety else varieties + [line.variety]
        variety = st.selectbox("Variety", opts, index=opts.index(line.variety) if line.variety in opts else None)
    c = st.columns(2)
    qty = c[0].number_input("Qty", min_value=1, step=1, format="%d",
                            value=int(line.qty) if float(line.qty).is_integer() and line.qty >= 1 else 1)
    price = c[1].number_input("Price / lot", min_value=0.01, step=1.0, value=float(line.price) or 0.01)
    new = IndentLine(parent_sku=line.parent_sku, customer_sku_name=name, variety=variety or "",
                     lot=line.lot, qty=float(qty), price=float(price))
    changes = []
    if int(to_number(line.qty)) != int(qty):
        changes.append(f"Qty: {line.qty:g} → {qty}")
    if round(line.price, 2) != round(float(price), 2):
        changes.append(f"Price: {line.price:,.2f} → {price:,.2f}")
    if (variety or "") != line.variety:
        changes.append(f"Variety: {line.variety or '—'} → {variety}")
    st.markdown("**Changes:** " + ("; ".join(changes) if changes else "none yet")
                + f"  \nAmount: ₹ {new.amount:,.2f}")
    b = st.columns(2)
    if b[0].button("✓ Save changes", type="primary", width="stretch",
                   disabled=not changes or (bool(varieties) and not variety)):
        lines = [new if x.customer_sku_name == name else x for x in cur.lines]
        _save_lines(cur, lines, user, "Item updated:")
    if b[1].button("Cancel", width="stretch"):
        st.session_state.pop("mi_line", None)
        st.rerun()


@st.dialog("Delete item?", dismissible=False)
def _delete_line_dialog(cur, name: str, user: User) -> None:
    st.write(f"Delete **{name}** from **{cur.indent_id}**?")
    st.caption("This saves a new version without this item. Earlier versions stay in the sheet.")
    only_one = len(cur.lines) <= 1
    if only_one:
        st.warning("This is the only item. An indent needs at least one item, so it can't be deleted.")
    b = st.columns(2)
    if b[0].button("Yes, delete", type="primary", width="stretch", disabled=only_one):
        _save_lines(cur, [x for x in cur.lines if x.customer_sku_name != name], user, "Item deleted:")
    if b[1].button("Cancel", width="stretch"):
        st.session_state.pop("mi_line", None)
        st.rerun()
