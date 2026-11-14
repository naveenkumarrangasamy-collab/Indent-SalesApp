"""Step 3: items (parent SKU, customer SKU name, variety, lot, qty, price)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import changelog, config, indents
from core.auth import User
from core.masters import Masters
from core.lots import lot_size
from core.models import IndentLine, clean_str, fmt_num, to_number
from core.sheets import SheetError
from pages_src import common, state


# ------------------------------------------------------------ add-line form

def _arev() -> int:
    return st.session_state.get("a_rev", 0)


def _ak(name: str) -> str:
    return f"a_{name}_{_arev()}"


def _on_parent() -> None:
    s = st.session_state
    for n in ("sku", "variety"):
        s.pop(_ak(n), None)


def _on_sku(m: Masters) -> None:
    s = st.session_state
    hdr = state.header()
    sku = s.get(_ak("sku"))
    parent = s.get(_ak("parent")) or ""
    varieties = m.varieties_for(parent)
    if varieties:
        dv = m.default_variety(hdr.city, hdr.customer, sku or "")
        s[_ak("variety")] = dv if dv in varieties else None


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
    if parent and m.needs_variety(parent) and not variety:
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
                              variety=variety if m.needs_variety(parent) else "",
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
        if varieties:
            c[2].selectbox("Variety", varieties, index=None, key=_ak("variety"), placeholder="Choose")
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

def _lines_table(m: Masters) -> None:
    hdr = state.header()
    lines = state.lines()
    if not lines:
        st.info("No items yet. Add the first item above.")
        return
    any_variety = any(m.needs_variety(x.parent_sku) for x in lines)
    all_varieties = sorted({v for x in lines for v in m.varieties_for(x.parent_sku)})
    rows = []
    for x in lines:
        origin, size = m.spec(hdr.city, hdr.customer, x.customer_sku_name)
        rows.append({"Parent SKU": x.parent_sku, "Customer SKU Name": x.customer_sku_name,
                     "Spec": " · ".join(v for v in (origin, size) if v) or "—",
                     "Variety": x.variety or None, "Lot": x.lot or None,
                     "Lot Size": lot_size(x.customer_sku_name),
                     "Qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                     "Price": float(x.price), "Amount": x.amount,
                     "Remove": False})
    df = pd.DataFrame(rows)
    if not any_variety:
        df = df.drop(columns=["Variety"])
    if not config.show_spec():
        df = df.drop(columns=["Spec"])
    key = f"ed_{st.session_state.get('editor_rev', 0)}"
    edited = st.data_editor(
        df, key=key, hide_index=True, width="stretch", num_rows="fixed",
        disabled=["Parent SKU", "Customer SKU Name", "Spec", "Lot", "Lot Size", "Amount"],
        column_config={
            "Customer SKU Name": st.column_config.TextColumn(width="large"),
            "Variety": st.column_config.SelectboxColumn(options=all_varieties),
            "Lot": st.column_config.TextColumn(help="Fixed by the SKU mapping"),
            "Lot Size": st.column_config.TextColumn(help="Pack size from the customer SKU name"),
            "Qty": st.column_config.NumberColumn(min_value=0, step=1, format="%d",
                                                 help="Whole numbers only"),
            "Price": st.column_config.NumberColumn("Price / lot", min_value=0.0, step=0.01, format="%.2f"),
            "Amount": st.column_config.NumberColumn(format="%.2f"),
            "Remove": st.column_config.CheckboxColumn("🗑", help="Tick to remove this item", width="small"),
        })

    # Sync edits back into the working indent.
    new_lines: list[IndentLine] = []
    to_remove: list[str] = []
    for x, (_, r) in zip(lines, edited.iterrows()):
        if bool(r.get("Remove")):
            to_remove.append(x.customer_sku_name)
        variety = clean_str(r.get("Variety")) if "Variety" in edited.columns else x.variety
        if not m.needs_variety(x.parent_sku):
            variety = ""
        new_lines.append(IndentLine(parent_sku=x.parent_sku, customer_sku_name=x.customer_sku_name,
                                    variety=variety, lot=x.lot,
                                    qty=to_number(r.get("Qty")), price=to_number(r.get("Price"))))
    if to_remove:  # ask first; the tick is undone until confirmed
        st.session_state["pending_remove"] = to_remove
        state.bump_editor()
        st.rerun()
    if [y.to_dict() for y in new_lines] != [y.to_dict() for y in lines]:
        state.set_lines(new_lines, structural=False)
        state.bump_editor()  # redraw so Amount and totals update
        st.rerun()


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
    if c[0].button("Yes, remove", type="primary", width="stretch"):
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

def _check(m: Masters) -> list[str]:
    return indents.validate(state.header(), state.lines(), m, min_date=state.min_delivery_date())


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
                                                  user.email)
        except SheetError as e:
            state.autosave(force=True)
            st.error(f"Not updated. {e}")
            return
    st.session_state.pop("review_open", None)
    state.clear_after_submit()
    msg = f"Indent **{ind['indent_id']}** updated to version {new_v}."
    if not log_ok:
        msg += " (The change log could not be written; the new version is saved.)"
    common.flash("success", msg)
    st.rerun()


def render(m: Masters, user: User) -> None:
    from pages_src.delivery import fmt_slot

    hdr = state.header()
    ind = state.get()
    s = st.session_state

    strip = st.columns([6, 1])
    strip[0].markdown(
        "<div class='mt-strip'>"
        f"<span><b>Date</b>{_fmt_date(hdr.delivery_date)}</span><span><b>City</b>{hdr.city}</span>"
        f"<span><b>Customer</b>{hdr.customer}</span><span><b>Store</b>{hdr.store}</span>"
        f"<span><b>Time</b>{fmt_slot(hdr.expected_time)}</span></div>", unsafe_allow_html=True)
    if strip[1].button("Edit", width="stretch", help="Change delivery details"):
        state.set_step("delivery")
        st.rerun()

    if not m.has_sku_mapping(hdr.city, hdr.customer):
        st.info(f"Mapping pending: no SKU names in 'All Cux City' for {hdr.customer} in {hdr.city}.")
    else:
        _add_form(m)

    st.markdown("**Items in this indent**")
    _lines_table(m)
    _totals()

    st.divider()
    if ind["mode"] == "edit":
        open_ = indents.can_edit(ind.get("created_at") or "")
        deadline = (indents.edit_deadline(ind["created_at"]).strftime("%d %b %Y, %I:%M %p")
                    if ind.get("created_at") else "")
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
            st.error(f"The edit window for {ind['indent_id']} closed at {deadline}. "
                     "It can no longer be changed.")
        elif not changed:
            c[2].caption(f"Nothing changed yet. Editable until {deadline}.")
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

    # Only one dialog at a time.
    if s.get("pending_remove"):
        _confirm_remove()
    elif s.get("pending_action"):
        _confirm_action()
    elif s.get("review_open"):
        _review(m, user)
