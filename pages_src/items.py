"""Step 3: items (parent SKU, customer SKU name, variety, lot, qty, price)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import indents
from core.auth import User
from core.lots import detect_lot
from core.masters import Masters
from core.models import IndentLine, clean_str, fmt_num, to_number
from core.schema import LOTS
from core.sheets import SheetError
from pages_src import common, state


# ------------------------------------------------------------ add-line form

def _arev() -> int:
    return st.session_state.get("a_rev", 0)


def _ak(name: str) -> str:
    return f"a_{name}_{_arev()}"


def _on_parent() -> None:
    s = st.session_state
    for n in ("sku", "variety", "lot"):
        s.pop(_ak(n), None)


def _on_sku(m: Masters) -> None:
    s = st.session_state
    hdr = state.header()
    sku = s.get(_ak("sku"))
    s[_ak("lot")] = detect_lot(sku) if sku else None
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
    lot = s.get(_ak("lot"))
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
        errors.append("Choose a lot (no unit found in the SKU name).")
    if qty <= 0:
        errors.append("Qty must be greater than 0.")
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
        c = st.columns([1.1, 2.4, 1.2, 0.9, 0.9, 1.0])
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
        c[3].selectbox("Lot", LOTS, index=None, key=_ak("lot"), placeholder="Choose")
        c[4].number_input("Qty", min_value=0.0, value=None, step=1.0, key=_ak("qty"), placeholder="0")
        c[5].number_input("Price / lot", min_value=0.0, value=None, step=1.0, key=_ak("price"),
                          placeholder="0.00")

        if sku:
            origin, size = m.spec(hdr.city, hdr.customer, sku)
            spec = " · ".join(x for x in (origin, size) if x) or "no active origin set"
            hint = ""
            lot_now = s.get(_ak("lot"))
            if lot_now and detect_lot(sku) == lot_now:
                hint = f" · lot **{lot_now}** picked from the name (you can change it)"
            elif detect_lot(sku) is None:
                hint = " · no unit in the name, please choose the lot"
            st.caption(f"Spec: {spec}{hint}")

        qty, price = to_number(s.get(_ak("qty"))), to_number(s.get(_ak("price")))
        b1, b2 = st.columns([1, 4])
        b1.button("＋ Add item", on_click=_add_line, args=(m,), type="secondary",
                  width="stretch")
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
                     "Qty": float(x.qty), "Price": float(x.price), "Amount": x.amount,
                     "Remove": False})
    df = pd.DataFrame(rows)
    if not any_variety:
        df = df.drop(columns=["Variety"])
    key = f"ed_{st.session_state.get('editor_rev', 0)}"
    edited = st.data_editor(
        df, key=key, hide_index=True, width="stretch", num_rows="fixed",
        disabled=["Parent SKU", "Customer SKU Name", "Spec", "Amount"],
        column_config={
            "Customer SKU Name": st.column_config.TextColumn(width="large"),
            "Variety": st.column_config.SelectboxColumn(options=all_varieties),
            "Lot": st.column_config.SelectboxColumn(options=LOTS, required=True),
            "Qty": st.column_config.NumberColumn(min_value=0.0, step=0.001, format="%g"),
            "Price": st.column_config.NumberColumn("Price / lot", min_value=0.0, step=0.01, format="%.2f"),
            "Amount": st.column_config.NumberColumn(format="%.2f"),
            "Remove": st.column_config.CheckboxColumn("🗑", help="Tick to remove this item", width="small"),
        })

    # Sync edits back into the working indent.
    new_lines: list[IndentLine] = []
    removed = False
    for x, (_, r) in zip(lines, edited.iterrows()):
        if bool(r.get("Remove")):
            removed = True
            continue
        variety = clean_str(r.get("Variety")) if "Variety" in edited.columns else x.variety
        if not m.needs_variety(x.parent_sku):
            variety = ""
        new_lines.append(IndentLine(parent_sku=x.parent_sku, customer_sku_name=x.customer_sku_name,
                                    variety=variety, lot=clean_str(r.get("Lot")),
                                    qty=to_number(r.get("Qty")), price=to_number(r.get("Price"))))
    if removed:
        state.set_lines(new_lines, structural=True)
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


# ------------------------------------------------------------ actions

def _submit(m: Masters, user: User) -> None:
    hdr, lines = state.header(), state.lines()
    errors = indents.validate(hdr, lines, m)
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
    state.clear_after_submit()
    common.flash("success", f"Indent **{indent_id}** submitted (version 1, {len(lines)} items).")
    st.rerun()


def _update(m: Masters, user: User) -> None:
    ind = state.get()
    hdr, lines = state.header(), state.lines()
    errors = indents.validate(hdr, lines, m)
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
    state.clear_after_submit()
    msg = f"Indent **{ind['indent_id']}** updated to version {new_v}."
    if not log_ok:
        msg += " (The change log could not be written; the new version is saved.)"
    common.flash("success", msg)
    st.rerun()


def render(m: Masters, user: User) -> None:
    hdr = state.header()
    ind = state.get()

    strip = st.columns([6, 1])
    strip[0].markdown(
        "<div class='mt-strip'>"
        f"<span><b>Date</b>{hdr.delivery_date}</span><span><b>City</b>{hdr.city}</span>"
        f"<span><b>Customer</b>{hdr.customer}</span><span><b>Store</b>{hdr.store}</span>"
        f"<span><b>Time</b>{hdr.expected_time}</span></div>", unsafe_allow_html=True)
    if strip[1].button("Edit", width="stretch", help="Change delivery details"):
        state.set_step("delivery")
        st.rerun()

    if not m.has_sku_mapping(hdr.city, hdr.customer):
        st.info(f"Mapping pending: no SKU names in SKU_Map for {hdr.customer} in {hdr.city}.")
    else:
        _add_form(m)

    st.markdown("**Items in this indent**")
    _lines_table(m)
    _totals()

    st.divider()
    if ind["mode"] == "edit":
        changed = state.changed_vs_base()
        c = st.columns([1, 1, 2])
        if c[0].button("Discard changes", width="stretch"):
            state.start_new()
            common.flash("info", f"Changes to {ind['indent_id']} discarded.")
            st.rerun()
        if c[1].button("Update indent", type="primary", disabled=not changed, width="stretch"):
            _update(m, user)
        if not changed:
            c[2].caption("Nothing changed yet. Update is enabled once something changes.")
    else:
        c = st.columns([1, 1, 2])
        if c[0].button("Clear form", width="stretch", disabled=not state.has_work()):
            state.start_new()
            st.rerun()
        if c[1].button("Submit indent", type="primary", width="stretch",
                       disabled=not state.lines()):
            _submit(m, user)
