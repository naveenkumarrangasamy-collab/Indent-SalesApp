"""Step 2: delivery details (date, city, customer, store, expected time)."""
from __future__ import annotations

from datetime import date, time

import streamlit as st

from core import config
from core.masters import Masters
from pages_src import common, state


def _rev() -> int:
    return st.session_state.get("w_rev", 0)


def _bump() -> None:
    st.session_state["w_rev"] = _rev() + 1


def _k(name: str) -> str:
    return f"w_{name}_{_rev()}"


def _clear_items(reason: str) -> None:
    if state.get()["lines"]:
        state.set_lines([], structural=True)
        common.flash("warning", f"{reason} changed, so the items added so far were cleared. "
                                "SKU names are mapped per city and customer.")


def _on_city(key: str) -> None:
    new = st.session_state.get(key) or ""
    hdr = state.header()
    if new == hdr.city:
        return
    state.set_header_field("city", new)
    state.set_header_field("store", "")
    _clear_items("City")
    _bump()


def _on_customer(key: str) -> None:
    new = st.session_state.get(key) or ""
    if new == state.header().customer:
        return
    state.set_header_field("customer", new)
    state.set_header_field("store", "")
    _clear_items("Customer")
    _bump()


def _on_simple(key: str, field: str) -> None:
    v = st.session_state.get(key)
    if isinstance(v, date):
        v = v.isoformat()
    elif isinstance(v, time):
        v = v.strftime("%H:%M")
    state.set_header_field(field, v or "")


def _index(options: list[str], value: str) -> int | None:
    return options.index(value) if value in options else None


def render(m: Masters) -> None:
    hdr = state.header()
    st.subheader("Delivery details")

    c1, c2 = st.columns(2)
    k = _k("date")
    c1.date_input("Delivery date", value=date.fromisoformat(hdr.delivery_date) if hdr.delivery_date else None,
                  key=k, on_change=_on_simple, args=(k, "delivery_date"), format="DD/MM/YYYY")

    cities = m.cities()
    if hdr.city and hdr.city not in cities:
        cities = cities + [hdr.city]
    k = _k("city")
    c2.selectbox("City", cities, index=_index(cities, hdr.city), key=k, placeholder="Choose city",
                 on_change=_on_city, args=(k,))

    c3, c4 = st.columns(2)
    customers = m.customers(hdr.city) if hdr.city else []
    if hdr.customer and hdr.customer not in customers:
        customers = customers + [hdr.customer]
    k = _k("customer")
    c3.selectbox("Customer", customers, index=_index(customers, hdr.customer), key=k,
                 placeholder="Choose customer" if hdr.city else "Choose a city first",
                 disabled=not hdr.city, on_change=_on_customer, args=(k,))

    stores = m.stores_for(hdr.city, hdr.customer) if hdr.city and hdr.customer else []
    if hdr.store and hdr.store not in stores:
        stores = stores + [hdr.store]
    k = _k("store")
    c4.selectbox("Store name", stores, index=_index(stores, hdr.store), key=k,
                 placeholder="Choose store" if stores else "No stores mapped",
                 disabled=not (hdr.city and hdr.customer), on_change=_on_simple, args=(k, "store"))

    c5, _ = st.columns(2)
    k = _k("time")
    c5.time_input("Expected delivery time",
                  value=time.fromisoformat(hdr.expected_time) if hdr.expected_time else None,
                  key=k, step=1800, on_change=_on_simple, args=(k, "expected_time"))

    if hdr.city and hdr.customer:
        pending = []
        if not m.has_sku_mapping(hdr.city, hdr.customer):
            pending.append("SKU names (All Cux City)")
        if not m.stores_for(hdr.city, hdr.customer):
            pending.append("stores (Customer List)")
        if pending:
            st.info(f"Mapping pending for {hdr.customer} in {hdr.city}: " + " and ".join(pending)
                    + " are not in the sheet yet. Ask the indent owner to add them.")

    if hdr.delivery_date and hdr.delivery_date < config.now_ist().date().isoformat():
        st.caption("⚠️ The delivery date is in the past.")

    missing = hdr.missing()
    if st.button("Continue →", type="primary", disabled=bool(missing)):
        state.set_step("items")
        st.rerun()
    if missing:
        st.caption("Required: " + ", ".join(missing))
