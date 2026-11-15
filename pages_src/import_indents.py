"""Access → Import indents (owner): many indents at once from an Excel sheet."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import bulk_import, indents, masters
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common
from pages_src.delivery import TIME_SLOTS, fmt_slot

_AS_FILE = "City as in the file"


def render(m: masters.Masters | None, me: User) -> None:
    st.markdown(
        "Upload an Excel with one row per item: **Delivery date, City, Customer, Store, Parent SKU, "
        "Item** (the customer SKU name, e.g. *Item (pack size - name)*) and **Qty**. Each customer + "
        "store + date becomes one indent, numbered like any other (IN-…).")
    if m is None:
        st.info("Master data could not be loaded.")
        return
    rev = st.session_state.get("imp_rev", 0)
    up = st.file_uploader("Indent Excel", type=["xlsx", "xls"], key=f"imp_file_{rev}")
    pasted = st.text_area("…or paste the rows copied from Excel (header row first)", height=100,
                          key=f"imp_paste_{rev}")
    if up is None and not pasted.strip():
        return
    try:
        rows = (bulk_import.read_rows(up.getvalue()) if up is not None
                else bulk_import.read_pasted(pasted))
    except bulk_import.ImportFileError as e:
        st.error(str(e))
        return
    if rows.empty:
        st.warning("The file has no item rows.")
        return

    cities = m.cities()
    c1, c2, c3 = st.columns(3)
    city = c1.selectbox("City for every indent", cities + [_AS_FILE], index=0 if cities else 0,
                        key="imp_city")
    file_price = c2.toggle("Use the price in the file", value=False, key="imp_fprice")
    price = None if file_price else c2.number_input("Price for every line", min_value=0.01, value=1.0,
                                                    step=1.0, key="imp_price")
    slot = c3.selectbox("Expected delivery time", TIME_SLOTS, index=0, format_func=fmt_slot,
                        key="imp_time")

    groups = bulk_import.plan(rows, m, city="" if city == _AS_FILE else city, price=price,
                              expected_time=slot)
    try:
        df = indents.read_lines(fresh=True)
    except SheetError as e:
        common.sheet_error(e)
        return
    table = []
    for g in groups:
        dup = indents.find_duplicate(df, g.header)
        if g.header.delivery_date and not indents.date_allowed(g.header.delivery_date):
            g.errors.append(f"Delivery date must be {indents.date_rule_text()}.")
        g.dup = dup or ""
        table.append({"Customer": g.header.customer, "Store": g.header.store,
                      "City": g.header.city, "Delivery": g.header.delivery_date,
                      "Items": len(g.lines), "Qty": sum(float(x.qty) for x in g.lines),
                      "New in master": (("store, " if g.new_store else "")
                                        + (f"{len(g.new_skus)} items" if g.new_skus else "")).strip(", "),
                      "Status": (f"Already placed ({dup})" if dup else
                                 ("; ".join(g.errors) if g.errors else "Ready"))})
    st.markdown(f"**{len(rows)} item rows → {len(groups)} indents**")
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

    with st.expander("All lines"):
        st.dataframe(pd.DataFrame([{"Customer": g.header.customer, "Store": g.header.store,
                                    **{"Parent SKU": x.parent_sku, "Customer SKU name": x.customer_sku_name,
                                       "Variety": x.variety, "Lot": x.lot, "Qty": x.qty,
                                       "Price": x.price}}
                                   for g in groups for x in g.lines]),
                     hide_index=True, width="stretch")

    skus, stores = bulk_import.master_additions(groups)
    if skus or stores:
        st.warning(f"Not in the master yet: **{len(skus)} SKU names** and **{len(stores)} stores**. "
                   "Add them first so these indents can be opened and edited like any other.")
        with st.expander("What will be added"):
            if skus:
                st.dataframe(pd.DataFrame(skus), hide_index=True, width="stretch")
            if stores:
                st.dataframe(pd.DataFrame(stores), hide_index=True, width="stretch")
        if st.button(f"Add {len(skus)} SKU names and {len(stores)} stores to the master",
                     icon=":material/playlist_add:", key="imp_master"):
            try:
                with st.spinner("Adding to the master…"):
                    notes = bulk_import.add_to_master(get_backend(), skus, stores)
            except SheetError as e:
                common.sheet_error(e, "Not added.")
                return
            masters.clear_cache()
            common.flash("success", "; ".join(notes) + ".")
            st.rerun()

    ready = [g for g in groups if not g.errors and not g.dup]
    blocked = bool(skus or stores)
    if st.button(f"Create {len(ready)} indents", type="primary", icon=":material/add_task:",
                 disabled=blocked or not ready, key="imp_go"):
        made, failed = [], []
        with st.spinner("Creating indents…"):
            for g in ready:
                try:
                    made.append(f"{indents.submit_new(g.header, g.lines, me.email)} {g.header.customer} · "
                                f"{g.header.store}")
                except SheetError as e:
                    failed.append(f"{g.label}: {e}")
        if made:
            common.flash("success", f"Created {len(made)} indents: " + "; ".join(made))
        if failed:
            st.error("Not created: " + "; ".join(failed))
        else:
            st.session_state["imp_rev"] = st.session_state.get("imp_rev", 0) + 1
            st.rerun()
