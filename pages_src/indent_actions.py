"""Indent-level actions shared by the home screen and All indents:
Upload PO, End of POs (multi-PO customers), Lock (processing started) and
Delete (marks it Cancelled)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, indents, mailer, po_reader
from core.masters import load_masters
from core.auth import User
from core.models import fmt_num, fmt_q
from core.schema import PO_ITEM_MAP, STATUS_FROZEN, WAITING_FOR_PO
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
    st.session_state.pop(f"po_no_{indent_id}", None)
    st.session_state.pop("po_mismatch", None)


def _diff_table(rows: list[dict]) -> None:
    st.dataframe(pd.DataFrame([{
        "#": i + 1, "Customer SKU Name": r["customer_sku_name"], "Indent qty": fmt_q(r["indent_qty"]),
        "PO qty": fmt_q(r["po_qty"]),
        "Difference": ("+" if r["diff"] > 0 else "") + fmt_num(r["diff"])} for i, r in enumerate(rows)]),
        hide_index=True, width="stretch", column_config={"#": st.column_config.NumberColumn("#", width=40)})


@st.dialog("Upload PO", dismissible=False, width="large")
def _po_dialog(indent_id: str, user: User) -> None:
    df = indents.read_lines()
    cur = indents.snapshot(df, indent_id)
    if cur is None:
        _close()
        st.rerun()
    _strip(cur)
    multi = indents.is_multi_po(cur.header.customer)
    info = indents.po_info(indents.read_po_freeze(), indent_id) if multi else None
    blocked = ""
    replacing = cur.status == STATUS_FROZEN and user.is_owner and not multi
    if replacing:
        st.warning("This indent already has a PO. Uploading again **replaces** it (only the new PO counts).")
    elif cur.status not in WAITING_FOR_PO:
        blocked = f"This indent is {cur.status.lower()}; no more POs can be added."
    elif _unsaved_here(indent_id):
        blocked = ("You have unsaved changes to this indent on the Indent page. "
                   "Update or discard them first.")
    if blocked:
        st.warning(blocked)
        if st.button("Close", width="stretch"):
            _close()
            st.rerun()
        return
    if multi:
        st.info(f"{cur.header.customer}: add every PO for this indent, one at a time "
                f"({info['pos']} received so far). Press **End of POs** after the last one; the indent "
                "is then frozen and the differences are shown.", icon=":material/library_add:")
    pre = _prefill(indent_id)
    can_freeze = cur.header.customer.strip().casefold() in config.no_po_customers() and not multi and not replacing
    how = st.selectbox("PO", ["Freeze", "Upload PO"], key=f"po_how_{indent_id}") if can_freeze else "Upload PO"
    no_po = how == "Freeze"
    if no_po:
        st.info("No PO file needed. The quantities below start from the indent: change only what differs, "
                "then press **Freeze**. What you freeze is the PO (unchanged = same as the indent).",
                icon=":material/lock:")
        if not pre.get("po_qty") and "init" not in pre:
            pre["po_qty"] = {x.customer_sku_name: float(x.qty) for x in cur.lines}

    # 1. the PO file (read automatically when it is a text PDF)
    c = st.columns([1, 1.6])
    files = st.session_state.setdefault("po_files", {})
    if no_po:
        files.pop(indent_id, None)
    else:
        up = c[1].file_uploader("PO file (PDF, Excel or screenshot)" if can_freeze else "PO file (PDF or Excel)",
                                type=["pdf", "xlsx", "xls", "csv"] + (["png", "jpg", "jpeg", "webp"] if can_freeze else []),
                                key=f"po_file_{indent_id}")
        if up is not None:
            files[indent_id] = (up.name, up.getvalue())
        elif indent_id in files:
            c[1].caption(f"Using **{files[indent_id][0]}** chosen earlier (choose another file to replace it).")
    file_name, file_bytes = files.get(indent_id, (None, None))
    ext = (file_name or "").rsplit(".", 1)[-1].casefold()
    is_pdf, is_sheet = ext == "pdf", ext in ("xlsx", "xls", "csv")
    read = (_read(file_bytes) if is_pdf else _read_sheet(file_bytes, ext, cur.header.store)) \
        if file_bytes and (is_pdf or is_sheet) else None
    if file_bytes and not (is_pdf or is_sheet):
        with st.expander("The screenshot", expanded=False):
            st.image(file_bytes, width=360)
    no_key = f"po_no_{indent_id}"
    if read and read.po_number and not st.session_state.get(no_key):
        st.session_state[no_key] = read.po_number
    po_number = c[0].text_input("PO number", key=no_key, placeholder="as printed on the PO")
    pre["po_number"] = po_number
    so_far = (info or {}).get("qty") or {}
    so_far = {k.strip().casefold(): v for k, v in so_far.items()}

    learned: list[dict] = []
    if read and read.lines:
        this_po, learned = _read_table(cur, read, po_number, indent_id, user)
    else:
        if read is not None:
            st.warning(" ".join(read.checks) or "No item lines found in this file: type the quantities.")
        this_po = _manual_table(cur, pre, indent_id, multi, so_far)
    _earlier_pos(cur, indent_id, this_po)
    tot_i = sum(float(x.qty) for x in cur.lines)
    st.caption(f"Indent total **{fmt_num(tot_i)}** · this PO **{fmt_num(sum(this_po.values()))}**"
               + (f" · earlier POs **{fmt_num(sum(so_far.values()))}**" if multi else ""))

    # 3. differences (multi-PO: shown after End of POs)
    diffs = [] if multi else [r for r in indents.po_vs_indent(cur.lines, {"qty": this_po}, customer=cur.header.customer) if not r["ok"]]
    if diffs:
        st.warning(f"**{len(diffs)} item(s) differ from the indent.** The PO is still uploaded; the "
                   "difference is flagged on the indent and in the hourly tracker.")
        _diff_table(diffs)

    to = ", ".join(mailer.po_recipients(cur.header))
    st.caption(("Each PO is e-mailed (SO / PO) at once to " if multi else
                "Uploading freezes the indent. The SO / PO e-mail goes at once to ")
               + (to or "nobody yet (add recipients on the Access page)") + ".")
    mail_again = replacing and st.checkbox("E-mail the replaced PO again", value=False, key=f"po_mail_{indent_id}")
    b = st.columns(3 if multi else 2)
    label = "Replace PO" if replacing else "Add this PO" if multi else ("Upload with differences" if diffs else "Upload PO")
    if no_po:
        label = "Freeze with differences" if diffs else "Freeze"
        file_name = "No PO file (frozen in the app)"
    need = [w for w, ok in (("choose the PO file", file_bytes or no_po), ("type the PO qty of at least one item",
                                                                this_po)) if not ok]
    if need:
        st.caption("To upload: " + " and ".join(need) + ".")
    if b[0].button(label, icon=":material/upload_file:", type="primary", width="stretch",
                   disabled=bool(need)):
        link, note = "", ""
        folder = config.po_drive_folder_id()
        backend = get_backend()
        if file_bytes and (folder or backend.mode == "local"):
            try:
                with st.spinner("Saving the PO file…"):
                    link = backend.upload_pdf(f"{indent_id} - {file_name}", file_bytes, folder)
            except SheetError as e:
                note = f" The file itself was not stored: {e}"
        try:
            with st.spinner("Saving the PO…"):
                _learn(learned)
                this_po, note_new = _name_new_items(backend, cur, this_po, user)
                note += note_new
                v, frozen_now = indents.freeze(indent_id, cur.version, file_name, user.email, po_file_link=link,
                                               po_qty=this_po, po_number=po_number.strip(),
                                               po_has_extra=any(k not in {x.customer_sku_name for x in cur.lines}
                                                                for k in this_po), replace=replacing)
        except SheetError as e:
            st.error(f"PO not saved. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        snap = indents.snapshot(indents.read_lines(fresh=True), indent_id) or cur
        if replacing and not mail_again:
            sent, mail_msg = True, "No e-mail sent (PO replaced)."
        else:
            with st.spinner("E-mailing the SO / PO…"):
                sent, mail_msg = mailer.send_so_mail(snap, file_name, file_bytes, user.email,
                                                     po_number=po_number.strip(), po_qty=this_po)
        _clear_po_state(indent_id)
        _close()
        what = f"PO {po_number or file_name}"
        common.flash("success", f"{indent_id}: {what} added. Add the next PO or press End of POs." if multi
                     else f"{indent_id} is frozen with {what} (version {v})."
                     + (f" {len(diffs)} item(s) differ from the indent." if diffs else "") + note)
        common.flash("success" if sent else "warning", mail_msg)
        st.rerun()
    if multi and b[1].button("End of POs", icon=":material/done_all:", width="stretch",
                             disabled=info["pos"] == 0,
                             help="No more POs for this indent: freeze it and show the differences"):
        st.session_state[KEY] = ("end", indent_id)
        st.rerun()
    if b[-1].button("Cancel", width="stretch"):
        _close()
        st.rerun()


def _name_new_items(backend, cur, this_po: dict, user: User) -> tuple[dict, str]:
    """24 Nov: an item on the PO that is not on the indent gets a name in our style ('Plum - 2 pcs' ->
    '2PC - Plum') and, when its fruit is known, is added to the master (All Cux City + New) so it can
    be picked on later indents. The PO is saved either way."""
    from core import master_add, masters
    on_indent = {" ".join(x.customer_sku_name.split()).casefold() for x in cur.lines}
    out, add = {}, []
    try:
        m = masters.load_masters()
        parents = sorted({str(p) for p in m.sku["Parent SKU"] if str(p).strip()})
    except Exception:  # noqa: BLE001 - naming is a convenience; never block the PO
        m, parents = None, []
    for k, v in this_po.items():
        if " ".join(str(k).split()).casefold() in on_indent:
            out[k] = v
            continue
        name = master_add.new_sku_name(str(k)) or str(k)
        out[name] = out.get(name, 0.0) + v
        parent = master_add.guess_parent(name, parents) if parents else ""
        if m is not None and parent and not m.parent_of(cur.header.city, cur.header.customer, name):
            add.append({"Parent SKU": parent, "Customer SKU Name": name, "Variety": "",
                        "Lot": master_add.lot_of(name)})
    if not add:
        return out, ""
    try:
        master_add.add_items(backend, cur.header.city, cur.header.customer, add, user.email)
        masters.clear_cache()
    except Exception:  # noqa: BLE001
        return out, ""
    return out, f" {len(add)} new item(s) added to the SKU list."


NOT_OURS = "— not in our list"


@st.cache_data(show_spinner="Reading the PO…", max_entries=20)
def _read(data: bytes):
    return po_reader.read_pdf(data)


@st.cache_data(show_spinner="Reading the PO…", max_entries=20)
def _read_sheet(data: bytes, ext: str, store: str = ""):
    """24 Nov: a PO sent as Excel / CSV: item + qty columns read like an attached order (same matching
    and checks as a PDF PO). Unreadable -> no lines, quantities typed by hand."""
    return read_sheet(data, ext, store)


def read_sheet(data: bytes, ext: str, store: str = ""):
    import io

    import pandas as pd
    from core import order_reader
    try:
        if ext == "csv":
            got = order_reader.sheet_lines(pd.read_csv(io.BytesIO(data), header=None, dtype=object).values.tolist())
            text = ""
        else:
            got = order_reader._excel(data, store)
            text = got.text or ""
    except Exception as e:  # noqa: BLE001 - any unreadable file
        return po_reader.POReadResult(lines=[], checks=[f"Could not read this file ({e}). Type the quantities."])
    if got is None or not got.lines:
        return po_reader.POReadResult(lines=[], checks=["No item and qty columns found in this file: "
                                                        "type the quantities."])
    return po_reader.POReadResult(lines=list(got.lines), po_number=po_reader._po_number(text), text=text)


def _candidates(cur) -> list[str]:
    names = [x.customer_sku_name for x in cur.lines]
    try:
        m = load_masters()
        h = cur.header
        for p in m.parents(h.city, h.customer):
            names += m.sku_names(h.city, h.customer, p)
    except Exception:  # noqa: BLE001 - the indent's own items are enough to match
        pass
    return list(dict.fromkeys(names))


def _item_map(customer: str) -> dict[str, str]:
    try:
        df = indents._cached_tab(PO_ITEM_MAP)
    except SheetError:
        return {}
    if df.empty:
        return {}
    df = df[df["Customer"].astype(str).str.strip().str.casefold() == customer.strip().casefold()]
    out = {}
    for r in df.to_dict("records"):
        for k in (r.get("PO Item Code"), r.get("PO Item Name")):
            if str(k or "").strip() and str(r.get("Customer SKU Name") or "").strip():
                out[str(k).strip()] = str(r["Customer SKU Name"]).strip()
    return out


def _norm(s) -> str:
    return " ".join(str(s or "").split()).casefold()


def _learn(rows: list[dict]) -> None:
    """Save the user's matches to PO_Item_Map, so the next PO matches by itself."""
    if rows:
        try:
            get_backend().append_dicts(PO_ITEM_MAP, rows)
            indents.clear_cache()
        except SheetError:
            pass


HOW = {"map": "✓ saved match", "name": "✓ same name", "close": "✓ close name", "guess": "? best guess",
       "": "✗ pick SKU"}


def _read_table(cur, read, po_number: str, indent_id: str, user: User) -> tuple[dict, list[dict]]:
    """The lines read from the PDF, matched to our SKUs; the user can change
    'Our SKU'. A new name link (PO name = our SKU) is remembered in PO_Item_Map
    only when an owner ticks Approve (19 Nov). Returns (PO qty per SKU, links to save)."""
    h = cur.header
    cands = _candidates(cur)
    lines = po_reader.match(read.lines, cands, _item_map(h.customer),
                            prefer=[x.customer_sku_name for x in cur.lines])
    ok = not read.checks
    msg = (f"**Read from the PDF:** {len(lines)} line(s) · qty **{fmt_num(read.total_qty)}**"
           + (f" · PO value ₹{read.total:,.2f}" if read.total else "")
           + (" · totals check ✓" if ok and read.total else ""))
    (st.success if ok else st.warning)(msg + ("" if ok else "\n\n" + "\n".join(f"- {c}" for c in read.checks)))
    store = po_reader.store_hint(po_number, config.po_store_prefixes())
    if store and store.strip().casefold() != h.store.strip().casefold():
        st.error(f"PO number {po_number} looks like **{store}**, but this indent is for **{h.store}**.")
    owner = bool(getattr(user, "is_owner", False))
    base = pd.DataFrame([{"#": i + 1, "On the PO": x.name, "Code": x.code, "Qty": fmt_num(x.qty),
                          "Our SKU": x.sku or None, "Match": HOW.get(x.how, "") + (" · ⚠ hard to read" if x.unsure else ""),
                          **({"Approve": False} if owner else {})} for i, x in enumerate(lines)])
    ed = st.data_editor(base, key=f"po_read_{indent_id}_{hash(read.po_number)}_{len(lines)}",
                        hide_index=True, width="stretch",
                        disabled=["#", "On the PO", "Code", "Qty", "Match"],
                        column_config={"#": st.column_config.NumberColumn("#", width=40, format="%d"),"Our SKU": st.column_config.SelectboxColumn(
                            options=cands + [NOT_OURS], width="large"),
                            "Approve": st.column_config.CheckboxColumn(
                                "Approve", help="Same item: remember this PO name for next time")})
    picks = [p if isinstance(p, str) and p.strip() else None for p in ed["Our SKU"]]
    approved = list(ed["Approve"]) if owner else [False] * len(lines)
    if any(p is None for p in picks):
        st.caption("✗ lines: pick **Our SKU** (or “not in our list”).")
    if any(x.how in ("close", "guess", "") for x in lines):
        st.caption("? lines: check **Our SKU**. " + ("Tick **Approve** to link the PO name to our SKU for next time."
                                                    if owner else "An Owner approves new name links."))
    this_po: dict[str, float] = {}
    learned = []
    stamp = config.now_iso()
    for x, pick, ok in zip(lines, picks, approved):
        key = pick if pick and pick != NOT_OURS else x.name
        this_po[key] = this_po.get(key, 0.0) + x.qty
        if ok and pick and pick != NOT_OURS and x.how != "map" and _norm(pick) != _norm(x.name):
            learned.append({"Customer": h.customer, "PO Item Code": x.code, "PO Item Name": x.name,
                            "Customer SKU Name": pick, "Updated_At": stamp})
    return this_po, learned


def _earlier_pos(cur, indent_id: str, this_po: dict) -> None:
    """24 Nov: POs already uploaded for this indent (Swiggy: several) and, per item, what is still pending
    after them and this PO. Shown only when there is an earlier PO."""
    earlier = indents.po_list(indents.read_po_freeze(), indent_id)
    if not earlier:
        return
    rows = indents.po_progress(cur.lines, earlier, this_po)
    heads = [f"PO {p['number'] or i + 1}" for i, p in enumerate(earlier)]
    tab = []
    for r in rows:
        pend = r["pending"]
        state = ("Not on indent" if r["indent"] is None else "Done" if abs(pend) < 1e-9
                 else f"Pending {fmt_num(pend)}" if pend > 0 else f"Extra {fmt_num(-pend)}")
        tab.append({"Customer SKU name": r["name"],
                    "Indent": "" if r["indent"] is None else fmt_num(r["indent"]),
                    **{h: "" if q is None else fmt_num(q) for h, q in zip(heads, r["pos"])},
                    "This PO": "" if r["this"] is None else fmt_num(r["this"]),
                    "Pending": "" if r["indent"] is None else fmt_num(max(pend, 0)), "Status": state})
    df = pd.DataFrame(tab)
    pending = sum(1 for t in tab if t["Status"].startswith("Pending"))
    colour = {"Done": "#d8f0d8", "Not on indent": "#FFD3A1"}

    def paint(r):
        c = colour.get(r["Status"]) or ("#F8C9C9" if r["Status"].startswith("Pending") else "#FFE89A")
        return [f"background-color: {c}; color: #1a1a1a"] * len(r)
    with st.expander(f"Earlier POs · {len(earlier)} uploaded · {pending} item(s) still pending", expanded=True):
        st.caption(" · ".join(f"**{h}** {p['at'][:16]} by {p['by'].split('@')[0]}" for h, p in zip(heads, earlier)))
        st.dataframe(common.numbered(df).style.apply(paint, axis=1), hide_index=True, width="stretch")


def _manual_table(cur, pre: dict, indent_id: str, multi: bool, so_far: dict) -> dict:
    st.markdown("**Quantities on this PO** · as on the customer's PO; leave blank if an item is not on it")
    if "init" not in pre:
        pre["init"] = dict(pre.get("po_qty", {}))
        st.session_state["po_ed_rev"] = pre["rev"] = st.session_state.get("po_ed_rev", 0) + 1
    saved = pre["init"]
    base = pd.DataFrame([{"#": i + 1, "Customer SKU Name": x.customer_sku_name, "Lot": x.lot,
                          "Indent qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                          **({"Earlier POs": fmt_num(so_far.get(x.customer_sku_name.strip().casefold(), 0))}
                             if multi else {}),
                          "PO qty": saved.get(x.customer_sku_name)} for i, x in enumerate(cur.lines)])
    base["PO qty"] = pd.to_numeric(base["PO qty"], errors="coerce")
    ed = st.data_editor(base, key=f"po_ed_{indent_id}_{pre.get('rev', 0)}", hide_index=True, width="stretch",
                        disabled=[c_ for c_ in base.columns if c_ != "PO qty"],
                        column_config={"#": st.column_config.NumberColumn("#", width=40, format="%d"),
                                       "PO qty": st.column_config.NumberColumn(min_value=0, step=1,
                                                                               format="%d")})
    po_qty = {r["Customer SKU Name"]: (None if pd.isna(r["PO qty"]) else float(r["PO qty"]))
              for r in ed.to_dict("records")}
    pre["po_qty"] = po_qty
    with st.expander("Items on the PO that are not in this indent"):
        ex = st.data_editor(pd.DataFrame({"Item on PO": pd.Series(dtype=str), "PO qty": pd.Series(dtype=float)}),
                            key=f"po_extra_{indent_id}_{pre.get('rev', 0)}", num_rows="dynamic",
                            hide_index=True, width="stretch",
                            column_config={"PO qty": st.column_config.NumberColumn(min_value=0, step=1,
                                                                                   format="%d")})
    this_po = {k: v for k, v in po_qty.items() if v is not None}
    this_po.update({str(r["Item on PO"]).strip(): float(r["PO qty"]) for r in ex.to_dict("records")
                    if str(r.get("Item on PO") or "").strip() and not pd.isna(r.get("PO qty"))})
    return this_po


@st.dialog("End of POs?", dismissible=False, width="large")
def _end_dialog(indent_id: str, user: User) -> None:
    cur = indents.snapshot(indents.read_lines(fresh=True), indent_id)
    if cur is None or cur.status not in WAITING_FOR_PO:
        _close()
        st.rerun()
    _strip(cur)
    info = indents.po_info(indents.read_po_freeze(), indent_id)
    rows = indents.po_vs_indent(cur.lines, info, customer=cur.header.customer)
    bad = [r for r in rows if not r["ok"]]
    st.write(f"**{info['pos']} PO(s)** received" + (f": {', '.join(info['numbers'])}" if info["numbers"] else "")
             + ". After this, no more POs can be added and the indent is frozen.")
    if bad:
        st.warning(f"**{len(bad)} item(s) differ** between the indent and all POs together:")
        _diff_table(bad)
    else:
        st.success("All POs together match the indent.")
    b = st.columns(2)
    if b[0].button("Yes, end of POs", icon=":material/done_all:", type="primary", width="stretch"):
        try:
            with st.spinner("Freezing…"):
                indents.end_pos(indent_id, cur.version, user.email)
        except SheetError as e:
            st.error(f"Not done. {e}")
            return
        _close()
        common.flash("success", f"{indent_id}: end of POs, indent frozen."
                     + (f" {len(bad)} item(s) differ; see the hourly tracker." if bad else ""))
        st.rerun()
    if b[1].button("Cancel", width="stretch"):
        _close()
        st.rerun()


@st.dialog("Lock indent?", dismissible=False)
def _lock_dialog(indent_id: str, user: User) -> None:
    cur = indents.snapshot(indents.read_lines(fresh=True), indent_id)
    if cur is None:
        _close()
        st.rerun()
    _strip(cur)
    st.write("Processing has started: the indent can no longer be edited. The PO can still be uploaded "
             "later, and the SO / PO e-mail still goes out then.")
    b = st.columns(2)
    if b[0].button("Yes, lock", icon=":material/lock:", type="primary", width="stretch"):
        try:
            with st.spinner("Locking…"):
                indents.lock(indent_id, cur.version, user.email)
        except SheetError as e:
            st.error(f"Not locked. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        _close()
        common.flash("success", f"{indent_id} locked. Upload its PO when it comes.")
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
    st.write("The indent is marked **Deleted (Cancelled)**: it leaves production, batching and the "
             "e-mails, and the store / delivery date becomes free for a new indent. All versions stay "
             "in the Google Sheet.")
    if cur.status == "Frozen":
        st.warning("This indent already has a PO. The PO record stays in PO_Freeze; no e-mail is sent.")
    b = st.columns(2)
    if b[0].button("Yes, delete", icon=":material/delete:", type="primary", width="stretch"):
        try:
            with st.spinner("Deleting…"):
                indents.cancel(indent_id, cur.version, user.email, owner=user.is_owner)
        except SheetError as e:
            st.error(f"Not deleted. {e}")
            return
        if state.get()["mode"] == "edit" and state.get()["indent_id"] == indent_id:
            state.start_new()
        _close()
        common.flash("success", f"{indent_id} deleted.")
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
    {"po": _po_dialog, "end": _end_dialog, "lock": _lock_dialog}.get(kind, _delete_dialog)(indent_id, user)
