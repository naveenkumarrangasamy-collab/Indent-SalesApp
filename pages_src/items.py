"""Step 3: items (parent SKU, customer SKU name, variety, lot, qty, price)."""
from __future__ import annotations

from html import escape

from datetime import date

import pandas as pd
import streamlit as st

from core import changelog, config, indents
from core.auth import User
from core.masters import Masters
from core.lots import lot_size
from core.models import IndentLine, fmt_num, to_number
from core.sheets import SheetError
from pages_src import common, state


# ------------------------------------------------------------ add-line form

def _arev() -> int:
    return st.session_state.get("a_rev", 0)


def _ak(name: str) -> str:
    return f"a_{name}_{_arev()}"


def _on_parent() -> None:
    """New parent: everything after it on this line starts empty again."""
    s = st.session_state
    for n in ("sku", "variety", "qty", "price"):
        s.pop(_ak(n), None)
    s.pop("add_errors", None)


def _on_sku(m: Masters) -> None:
    """New customer SKU name: clear variety, qty and price for this line."""
    s = st.session_state
    for n in ("qty", "price"):
        s.pop(_ak(n), None)
    s.pop(_ak("variety"), None)
    s.pop("add_errors", None)
    hdr = state.header()
    sku = s.get(_ak("sku"))
    parent = s.get(_ak("parent")) or ""
    varieties = m.varieties_for(parent)
    if varieties:
        dv = m.default_variety(hdr.city, hdr.customer, sku or "")
        if dv in varieties:
            s[_ak("variety")] = dv


def _add_line(m: Masters) -> None:
    s = st.session_state
    hdr = state.header()
    parent = s.get(_ak("parent"))
    sku = s.get(_ak("sku"))
    variety = s.get(_ak("variety")) or ""
    lot = m.lot_for(hdr.city, hdr.customer, sku) if sku else ""
    qty = to_number(s.get(_ak("qty")))
    price = to_number(s.get(_ak("price")))
    errors = []
    if not parent:
        errors.append("Choose a parent SKU.")
    if not sku:
        errors.append("Choose a customer SKU name.")
    if parent and m.needs_variety(parent) and not variety and not m.variety_from_name(parent, sku or ""):
        errors.append("Choose a variety.")
    if not lot:
        errors.append("No lot is mapped for this SKU name. Ask the indent owner to add a "
                      "'Lot' column value for it in the sheet.")
    if qty <= 0:
        errors.append("Qty must be greater than 0.")
    elif not float(qty).is_integer():
        errors.append("Qty must be a whole number.")
    if price <= 0:
        errors.append("Price must be greater than 0.")
    current = state.lines()
    if sku and any(x.customer_sku_name.casefold() == sku.casefold() for x in current):
        errors.append(f"'{sku}' is already in this indent.")
    if errors:
        s["add_errors"] = errors
        return
    current.append(IndentLine(parent_sku=parent, customer_sku_name=sku,
                              variety=(m.variety_from_name(parent, sku) or variety)
                              if m.needs_variety(parent) else "",
                              lot=lot, qty=qty, price=price))
    state.set_lines(current, structural=True)
    s["a_rev"] = _arev() + 1  # fresh, empty add-line widgets
    s.pop("add_errors", None)


def _add_form(m: Masters) -> None:
    hdr = state.header()
    used = {x.customer_sku_name.casefold() for x in state.lines()}
    parents = m.parents(hdr.city, hdr.customer)
    s = st.session_state

    with st.container(border=True):
        st.markdown("**Add item**")
        c = st.columns([1.1, 2.4, 1.1, 0.8, 1.0, 0.8, 1.0])
        parent = c[0].selectbox("Parent SKU", parents, index=None, key=_ak("parent"),
                                placeholder="Choose", on_change=_on_parent)
        names = ([n for n in m.sku_names(hdr.city, hdr.customer, parent) if n.casefold() not in used]
                 if parent else [])
        placeholder = "Choose" if names else ("All added" if parent else "Choose parent first")
        sku = c[1].selectbox("Customer SKU name", names, index=None, key=_ak("sku"),
                             placeholder=placeholder, disabled=not names,
                             on_change=_on_sku, args=(m,))
        varieties = m.varieties_for(parent) if parent else []
        fixed = m.variety_from_name(parent, sku) if (parent and sku) else ""
        if fixed:
            c[2].selectbox("Variety", [fixed], index=0, disabled=True, key=_ak(f"variety_fixed_{fixed}"),
                           help="Taken from the customer SKU name; cannot be changed")
        elif varieties:
            c[2].selectbox("Variety", varieties, index=None, key=_ak("variety"), placeholder="Choose",
                           help="The SKU name does not say which variety; please choose")
        else:
            c[2].selectbox("Variety", ["Not needed"], index=0, disabled=True, key=_ak("variety_na"))
        lot_now = m.lot_for(hdr.city, hdr.customer, sku) if sku else ""
        c[3].text_input("Lot", value=lot_now or ("not mapped" if sku else ""), disabled=True,
                        help="Set automatically from the SKU mapping; it cannot be changed here.")
        c[4].text_input("Lot size", value=lot_size(sku) if sku else "", disabled=True,
                        help="Pack size written in the customer SKU name")
        c[5].number_input("Qty", min_value=0, value=None, step=1, format="%d", key=_ak("qty"),
                          placeholder="0", help="Whole numbers only")
        c[6].number_input("Price / lot", min_value=0.0, value=None, step=1.0, key=_ak("price"),
                          placeholder="0.00")

        if sku:
            if config.show_spec():
                origin, size = m.spec(hdr.city, hdr.customer, sku)
                spec = " · ".join(x for x in (origin, size) if x) or "origin / size not in Mapping Whole"
                st.caption(f"Spec: {spec}")
            if not lot_now:
                st.warning("No lot is mapped for this SKU name, so it can't be added yet.")

        qty, price = to_number(s.get(_ak("qty"))), to_number(s.get(_ak("price")))
        b1, b2 = st.columns([1, 4])
        b1.button("＋ Add item", on_click=_add_line, args=(m,), type="secondary",
                  width="stretch", disabled=bool(sku) and not lot_now)
        if qty > 0 and price > 0:
            b2.caption(f"Amount: ₹ {qty * price:,.2f}")
        for e in s.pop("add_errors", []):
            st.error(e)


# ------------------------------------------------------------ lines table

_ROW_W = [1.0, 2.5, 0.9, 0.6, 0.8, 0.6, 0.8, 0.9, 1.0, 0.8]
SAVED_HELP = "Items already saved on the indent cannot be removed. To drop it, set its qty to 0."


def _lines_table(m: Masters) -> None:
    lines = state.lines()
    if not lines:
        st.info("No items yet. Add the first item above.")
        return
    has_variety = any(m.needs_variety(x.parent_sku) or x.variety for x in lines)
    with st.container(key="mtdesk_items"):
        _lines_desktop(m, lines, has_variety)
    with st.container(key="mtmob_items"):
        _lines_phone(m, lines)


def _lines_phone(m: Masters, lines) -> None:
    for i, x in enumerate(lines):
        with st.container(border=True, key=f"mtcard_it_{i}"):
            needs = m.needs_variety(x.parent_sku)
            var = x.variety or ("<span style='color:#b42318'>choose variety</span>" if needs else "")
            size = lot_size(x.customer_sku_name)
            st.markdown(
                f"<div class='mt-card-head'><b>{escape(x.customer_sku_name)}</b></div>"
                f"<div class='mt-muted'>{escape(x.parent_sku)}{' · ' + var if var else ''}"
                f"{' · ' + escape(size) if size else ''}</div>"
                f"<div>Qty <b>{fmt_num(x.qty)}</b> {escape(x.lot)} × ₹{x.price:,.2f} = "
                f"<b>₹{x.amount:,.2f}</b></div>", unsafe_allow_html=True)
            c = st.columns(2)
            if c[0].button("Edit", icon=":material/edit:", key=f"it_me_{i}_{x.customer_sku_name}",
                           width="stretch"):
                st.session_state["pending_edit"] = x.customer_sku_name
                st.rerun()
            if state.is_saved_line(x.customer_sku_name):
                c[1].button("Saved item", icon=":material/lock:", key=f"it_ml_{i}_{x.customer_sku_name}",
                            disabled=True, width="stretch", help=SAVED_HELP)
            elif c[1].button("Delete", icon=":material/delete:", key=f"it_md_{i}_{x.customer_sku_name}",
                             width="stretch"):
                st.session_state["pending_remove"] = [x.customer_sku_name]
                st.rerun()


def _lines_desktop(m: Masters, lines, has_variety: bool) -> None:
    head = st.columns(_ROW_W)
    for col, label in zip(head, ["Parent SKU", "Customer SKU Name", "Variety" if has_variety else "",
                                 "Lot", "Lot Size", "Qty", "Price", "Amount", "", ""]):
        col.markdown(f"<span class='mt-muted'>{label}</span>", unsafe_allow_html=True)
    for i, x in enumerate(lines):
        c = st.columns(_ROW_W, vertical_alignment="center")
        c[0].write(x.parent_sku)
        c[1].write(x.customer_sku_name)
        if has_variety:
            needs = m.needs_variety(x.parent_sku)
            c[2].markdown(x.variety or ("<span style='color:#b42318'>choose</span>" if needs else "—"),
                          unsafe_allow_html=True)
        c[3].write(x.lot)
        c[4].write(lot_size(x.customer_sku_name) or "—")
        c[5].markdown(f"<span class='num'>{fmt_num(x.qty)}</span>", unsafe_allow_html=True)
        c[6].markdown(f"<span class='num'>{x.price:,.2f}</span>", unsafe_allow_html=True)
        c[7].markdown(f"<span class='num'>{x.amount:,.2f}</span>", unsafe_allow_html=True)
        if c[8].button("Edit", icon=":material/edit:", key=f"it_e_{i}_{x.customer_sku_name}",
                       width="stretch", help="Change qty, price or variety"):
            st.session_state["pending_edit"] = x.customer_sku_name
            st.rerun()
        if state.is_saved_line(x.customer_sku_name):
            c[9].markdown("<span class='mt-muted' title='Saved items cannot be removed; set qty to 0'>"
                          "🔒 saved</span>", unsafe_allow_html=True)
        elif c[9].button("Delete", icon=":material/delete:", key=f"it_d_{i}_{x.customer_sku_name}",
                         width="stretch", help="Remove this item"):
            st.session_state["pending_remove"] = [x.customer_sku_name]
            st.rerun()


@st.dialog("Edit item", dismissible=False)
def _edit_item(m: Masters) -> None:
    name = st.session_state.get("pending_edit")
    lines = state.lines()
    line = next((x for x in lines if x.customer_sku_name == name), None)
    if line is None:
        st.session_state.pop("pending_edit", None)
        st.rerun()
    size = lot_size(name)
    st.markdown(f"**{name}**  \n<span class='mt-muted'>{line.parent_sku} · lot {line.lot}"
                f"{' · ' + size if size else ''}</span>", unsafe_allow_html=True)
    varieties = m.varieties_for(line.parent_sku)
    fixed = m.variety_from_name(line.parent_sku, name)
    saved = state.is_saved_line(name)
    variety = ""
    if fixed:
        variety = st.selectbox("Variety", [fixed], index=0, disabled=True,
                               help="Taken from the customer SKU name; cannot be changed")
    elif saved and line.variety:
        variety = st.selectbox("Variety", [line.variety], index=0, disabled=True,
                               help="On a saved indent only qty and price can be changed")
    elif varieties:
        variety = st.selectbox("Variety", varieties,
                               index=varieties.index(line.variety) if line.variety in varieties else None,
                               placeholder="Choose")
    c = st.columns(2)
    low = 0 if saved else 1
    qty = c[0].number_input("Qty", min_value=low, step=1, format="%d",
                            value=max(low, int(line.qty)) if float(line.qty).is_integer() else low,
                            help="Set 0 when there is no indent for this item (saved items stay on the indent)"
                            if saved else "Whole numbers only")
    price = c[1].number_input("Price / lot", min_value=0.01, step=1.0,
                              value=float(line.price) if line.price > 0 else 1.0)
    new = IndentLine(parent_sku=line.parent_sku, customer_sku_name=name, variety=variety or "",
                     lot=line.lot, qty=float(qty), price=float(price))
    st.markdown(f"Amount: **₹ {new.amount:,.2f}**")
    b = st.columns(2)
    if b[0].button("Save", icon=":material/check:", type="primary", width="stretch",
                   disabled=bool(varieties) and not variety):
        state.set_lines([new if x.customer_sku_name == name else x for x in lines], structural=True)
        st.session_state.pop("pending_edit", None)
        st.rerun()
    if b[1].button("Cancel", width="stretch"):
        st.session_state.pop("pending_edit", None)
        st.rerun()


def _po_fix_banner() -> None:
    fix = state.po_fix() or {}
    cmp = indents.po_compare(state.lines(), fix.get("po_qty", {}))
    bad = [r for r in cmp if not r["ok"]]
    with st.container(border=True, key="mt_po_fix"):
        if not bad:
            st.success("All items now match the PO. Press **Update indent** to save, then upload the PO.")
            return
        st.error(f"**Match the indent to the customer's PO** {fix.get('po_number') or ''}: "
                 f"{len(bad)} item(s) differ.")
        st.dataframe(pd.DataFrame([{
            "Customer SKU Name": r["customer_sku_name"], "Lot": r["lot"],
            "Indent qty": fmt_num(r["indent_qty"]),
            "PO qty": "not entered" if r["po_qty"] is None else fmt_num(r["po_qty"]),
        } for r in bad]), hide_index=True, width="stretch")
        if st.button("Set these quantities to the PO", icon=":material/sync:", key="po_fix_apply",
                     disabled=all(r["po_qty"] is None for r in bad)):
            by = {r["customer_sku_name"]: r["po_qty"] for r in cmp if r["po_qty"] is not None}
            new = [IndentLine(**{**x.to_dict(), "qty": float(by.get(x.customer_sku_name, x.qty))})
                   for x in state.lines()]
            state.set_lines(new, structural=True)
            st.rerun()
        st.caption("Or use **Edit** on each item. If the PO has an item that is not on the indent, "
                   "add it with **Add item**.")


def _totals() -> None:
    lines = state.lines()
    if not lines:
        return
    by_lot: dict[str, float] = {}
    for x in lines:
        by_lot[x.lot or "?"] = by_lot.get(x.lot or "?", 0) + to_number(x.qty)
    total = sum(x.amount for x in lines)
    c = st.columns([1, 1, 3])
    c[0].metric("Items", len(lines))
    c[1].metric("Total amount", f"₹ {total:,.2f}")
    c[2].metric("Qty by lot", "  ·  ".join(f"{fmt_num(q)} {lot}" for lot, q in by_lot.items()))


# ------------------------------------------------------------ dialogs

def _fmt_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%a, %d %b %Y")
    except ValueError:
        return iso


def _lines_frame(lines: list[IndentLine]) -> pd.DataFrame:
    df = pd.DataFrame([{"Parent SKU": x.parent_sku, "Customer SKU Name": x.customer_sku_name,
                        "Variety": x.variety, "Lot": x.lot, "Lot Size": lot_size(x.customer_sku_name),
                        "Qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                        "Price": x.price, "Amount": x.amount} for x in lines])
    if not df.empty and not df["Variety"].astype(bool).any():
        df = df.drop(columns=["Variety"])
    return df


@st.dialog("Remove item?", dismissible=False)
def _confirm_remove() -> None:
    names = st.session_state.get("pending_remove", [])
    st.write("This will remove from the indent:")
    for n in names:
        st.markdown(f"- **{n}**")
    c = st.columns(2)
    if c[0].button("Yes, remove", icon=":material/delete:", type="primary", width="stretch"):
        keep = [x for x in state.lines() if x.customer_sku_name not in set(names)]
        state.set_lines(keep, structural=True)
        st.session_state.pop("pending_remove", None)
        st.rerun()
    if c[1].button("Cancel", width="stretch"):
        st.session_state.pop("pending_remove", None)
        st.rerun()


@st.dialog("Are you sure?", dismissible=False)
def _confirm_action() -> None:
    action = st.session_state.get("pending_action")
    ind = state.get()
    if action == "discard":
        st.write(f"Discard all unsaved changes to **{ind['indent_id']}**? "
                 "The saved version in the sheet is not affected.")
        label = "Yes, discard"
    else:
        st.write("Clear the whole form? All delivery details and items entered so far will be removed.")
        label = "Yes, clear"
    c = st.columns(2)
    if c[0].button(label, type="primary", width="stretch"):
        st.session_state.pop("pending_action", None)
        state.start_new()
        if action == "discard":
            common.flash("info", f"Changes to {ind['indent_id']} discarded.")
        st.rerun()
    if c[1].button("Cancel", width="stretch"):
        st.session_state.pop("pending_action", None)
        st.rerun()


@st.dialog("Review and confirm", width="large", dismissible=False)
def _review(m: Masters, user: User) -> None:
    ind = state.get()
    hdr, lines = state.header(), state.lines()
    edit = ind["mode"] == "edit"
    from pages_src.delivery import fmt_slot
    st.markdown(f"**{'Update ' + ind['indent_id'] if edit else 'New indent'}** — please check before "
                f"{'saving' if edit else 'submitting'}.")
    st.markdown(
        "<div class='mt-strip'>"
        f"<span><b>Delivery</b>{_fmt_date(hdr.delivery_date)}</span>"
        f"<span><b>Time</b>{fmt_slot(hdr.expected_time)}</span>"
        f"<span><b>City</b>{hdr.city}</span><span><b>Customer</b>{hdr.customer}</span>"
        f"<span><b>Store</b>{hdr.store}</span></div>", unsafe_allow_html=True)
    st.dataframe(_lines_frame(lines), hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%d"),
                                "Price": st.column_config.NumberColumn(format="%.2f"),
                                "Amount": st.column_config.NumberColumn(format="%.2f")})
    total = sum(x.amount for x in lines)
    st.markdown(f"**{len(lines)} item(s) · Total ₹ {total:,.2f}**")
    if edit:
        base = state.base_snapshot()
        if base:
            changes = changelog.diff(base[0], base[1], hdr, lines)
            with st.expander(f"Changes compared with version {ind['base_version']} ({len(changes)})",
                             expanded=True):
                for ch in changes:
                    what = ch["customer_sku_name"] or "Delivery details"
                    kind = ch["change_type"].replace("_", " ")
                    detail = (f"{ch['field']}: {ch['old_value']} → {ch['new_value']}" if ch["field"]
                              else (ch["new_value"] or ch["old_value"]))
                    st.markdown(f"- **{what}** — {kind}: {detail}")
    c = st.columns(2)
    go = c[0].button("✓ Confirm update" if edit else "✓ Confirm & submit", type="primary",
                     width="stretch")
    if c[1].button("← Go back and edit", width="stretch"):
        st.session_state.pop("review_open", None)
        st.rerun()
    if go:
        (_update if edit else _submit)(m, user)


# ------------------------------------------------------------ actions

def _fill_fixed_varieties(m: Masters) -> None:
    """Apple SKUs whose name says the variety: set it (older lines may be blank)."""
    lines = state.lines()
    changed = False
    for x in lines:
        fixed = m.variety_from_name(x.parent_sku, x.customer_sku_name)
        if fixed and x.variety != fixed:
            x.variety = fixed
            changed = True
    if changed:
        state.set_lines(lines, structural=False)


def _check(m: Masters) -> list[str]:
    _fill_fixed_varieties(m)
    errors = indents.validate(state.header(), state.lines(), m, check_date=not state.po_fix(),
                              keep_date=state.keep_date(), zero_ok=state.saved_names())
    u = st.session_state.get("user") or {}
    city = state.header().city
    if u.get("role") != "owner" and u.get("cities") and \
            city.casefold() not in {c.casefold() for c in u["cities"]}:
        errors.append(f"You can place indents only in {', '.join(u['cities'])}, not {city}.")
    return errors


def _submit(m: Masters, user: User) -> None:
    hdr, lines = state.header(), state.lines()
    errors = _check(m)
    if errors:
        for e in errors:
            st.error(e)
        return
    with st.spinner("Saving to the Google Sheet…"):
        try:
            indent_id = indents.submit_new(hdr, lines, user.email)
        except SheetError as e:
            state.autosave(force=True)
            st.error(f"Not submitted. {e} Your draft is kept.")
            return
    st.session_state.pop("review_open", None)
    state.clear_after_submit()
    common.flash("success", f"Indent **{indent_id}** submitted (version 1, {len(lines)} items).")
    st.rerun()


def _update(m: Masters, user: User) -> None:
    ind = state.get()
    hdr, lines = state.header(), state.lines()
    errors = _check(m)
    if errors:
        for e in errors:
            st.error(e)
        return
    with st.spinner("Saving the new version…"):
        try:
            new_v, log_ok = indents.submit_update(ind["indent_id"], ind["base_version"], hdr, lines,
                                                  user.email, po_fix=bool(ind.get("po_fix")))
        except SheetError as e:
            state.autosave(force=True)
            st.error(f"Not updated. {e}")
            return
    st.session_state.pop("review_open", None)
    fix = ind.get("po_fix")
    state.clear_after_submit()
    msg = f"Indent **{ind['indent_id']}** updated to version {new_v}."
    if not log_ok:
        msg += " (The change log could not be written; the new version is saved.)"
    if fix:
        # back to the PO upload with what was typed before
        from pages_src import indent_actions
        st.session_state.setdefault("po_prefill", {})[ind["indent_id"]] = fix
        common.flash("success", msg + " Now check the PO again and upload it.")
        st.session_state[indent_actions.KEY] = ("po", ind["indent_id"])
        st.switch_page(common.PAGES["po"])
    common.flash("success", msg)
    st.rerun()


def render(m: Masters, user: User) -> None:
    from pages_src.delivery import fmt_slot

    hdr = state.header()
    ind = state.get()
    s = st.session_state
    st.markdown(f"#### Items for {hdr.store}")
    st.caption(f"{_fmt_date(hdr.delivery_date)} · {hdr.customer} · {hdr.city}"
               + (f" · {fmt_slot(hdr.expected_time)}" if hdr.expected_time else " · choose the delivery time above"))

    if not m.has_sku_mapping(hdr.city, hdr.customer):
        st.info(f"Mapping pending: no SKU names in 'All Cux City' for {hdr.customer} in {hdr.city}.")
    else:
        _add_form(m)

    if state.po_fix():
        _po_fix_banner()
    st.markdown("**Items in this indent**")
    _lines_table(m)
    _totals()

    st.divider()
    if ind["mode"] == "edit":
        saved_date = state.keep_date() or ""
        fix = state.po_fix()
        open_ = indents.can_edit(saved_date) or bool(fix)
        deadline = indents.deadline_text(saved_date)
        changed = state.changed_vs_base()
        c = st.columns([1, 1, 2])
        if c[0].button("Discard changes", width="stretch"):
            s["pending_action"] = "discard"
            st.rerun()
        if c[1].button("Update indent", type="primary", disabled=not (changed and open_),
                       width="stretch"):
            errors = _check(m)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                s["review_open"] = True
                st.rerun()
        if not open_:
            st.error(f"Editing of {ind['indent_id']} closed at {deadline} (2 PM on the delivery day). "
                     "It can no longer be changed.")
        elif fix:
            c[2].caption("Correcting the indent to match the customer's PO. After **Update indent** "
                         "you go back to the PO upload.")
        elif not changed:
            c[2].caption(f"Nothing changed yet. Editable until {deadline}. Saved items cannot be "
                         "removed; set qty to 0 instead.")
        else:
            c[2].caption(f"Editable until {deadline}.")
    else:
        c = st.columns([1, 1, 2])
        if c[0].button("Clear form", width="stretch", disabled=not state.has_work()):
            s["pending_action"] = "clear"
            st.rerun()
        if c[1].button("Submit indent", type="primary", width="stretch",
                       disabled=not state.lines()):
            errors = _check(m)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                s["review_open"] = True
                st.rerun()

    dialogs_only(m, user)


def dialogs_only(m: Masters, user: User) -> None:
    """Open whichever item dialog is pending (only one dialog at a time)."""
    s = st.session_state
    if s.get("pending_edit"):
        _edit_item(m)
    elif s.get("pending_remove"):
        _confirm_remove()
    elif s.get("pending_action"):
        _confirm_action()
    elif s.get("review_open"):
        _review(m, user)
