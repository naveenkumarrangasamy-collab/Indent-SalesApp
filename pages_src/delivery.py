"""Step 2: delivery details (date, city, customer, store, expected time)."""
from __future__ import annotations

from datetime import date, time

import streamlit as st

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


TIME_SLOTS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def parse_time(text: str) -> str | None:
    """'6:45 pm', '18:45', '6.45PM', '645 pm', '7 am', '0730' -> 'HH:MM'; None if not a time."""
    import re

    t = str(text or "").strip().lower().replace(".", ":")
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t)
    if not m:
        return None
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").replace(".", "")
    if mins > 59:
        return None
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if ampm == "pm" else 0)
    elif h > 23:
        return None
    return f"{h:02d}:{mins:02d}"


def _on_time(key: str) -> None:
    raw = st.session_state.get(key)
    if raw in (None, ""):
        state.set_header_field("expected_time", "")
        return
    parsed = raw if raw in TIME_SLOTS else parse_time(raw)
    if parsed is None:
        common.flash("error", f"'{raw}' is not a time. Type it like 6:45 PM or 18:45, "
                              "or pick a slot from the list.")
    else:
        state.set_header_field("expected_time", parsed)
    _bump()


def fmt_slot(hhmm: str) -> str:
    """'06:30' -> '06:30 AM'."""
    try:
        return time.fromisoformat(hhmm).strftime("%I:%M %p")
    except ValueError:
        return hhmm


def _drop_stale(m: Masters) -> None:
    """A restored draft may hold a city / customer / store / time that is no
    longer in the sheet. For new indents, clear those so the lists match."""
    ind = state.get()
    if ind["mode"] == "edit":
        return
    h = ind["header"]
    dropped = []
    if h.get("city") and h["city"] not in m.cities():
        dropped.append(h["city"])
        h.update(city="", customer="", store="")
    if h.get("customer") and h["customer"] not in m.customers(h.get("city", "")):
        dropped.append(h["customer"])
        h.update(customer="", store="")
    if h.get("store") and h["store"] not in m.stores_for(h.get("city", ""), h.get("customer", "")):
        dropped.append(h["store"])
        h["store"] = ""
    if h.get("expected_time") and parse_time(h["expected_time"]) != h["expected_time"]:
        h["expected_time"] = ""  # not a valid HH:MM (typed custom times are kept)
    if dropped:
        if ind["lines"]:
            state.set_lines([], structural=True)
        state.mark_dirty(force=True)
        _bump()
        st.info("Your saved draft used " + ", ".join(dropped)
                + ", which is no longer in the Google Sheet, so it was cleared. Please choose again.")


def render(m: Masters) -> None:
    common.show_flash()
    _drop_stale(m)
    hdr = state.header()
    st.subheader("Delivery details")

    c1, c2 = st.columns(2)
    k = _k("date")
    min_d = state.min_delivery_date()
    cur_d = date.fromisoformat(hdr.delivery_date) if hdr.delivery_date else None
    if cur_d and cur_d < min_d:  # e.g. an old draft: ask for a new date
        cur_d = None
    c1.date_input("Delivery date", value=cur_d, min_value=min_d, key=k, on_change=_on_simple,
                  args=(k, "delivery_date"), format="DD/MM/YYYY",
                  help=f"From {min_d:%d %b %Y} onwards")

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
    slots = TIME_SLOTS if hdr.expected_time in TIME_SLOTS or not hdr.expected_time \
        else TIME_SLOTS + [hdr.expected_time]
    c5.selectbox("Expected delivery time", slots, index=_index(slots, hdr.expected_time), key=k,
                 format_func=fmt_slot, placeholder="Pick a slot or type e.g. 6:45 PM",
                 accept_new_options=True, on_change=_on_time, args=(k,),
                 help="Pick a 30-minute slot, or type any time (6:45 PM, 18:45) and press Enter")

    if hdr.city and hdr.customer:
        pending = []
        if not m.has_sku_mapping(hdr.city, hdr.customer):
            pending.append("SKU names (All Cux City)")
        if not m.stores_for(hdr.city, hdr.customer):
            pending.append("stores (Customer List)")
        if pending:
            st.info(f"Mapping pending for {hdr.customer} in {hdr.city}: " + " and ".join(pending)
                    + " are not in the sheet yet. Ask the indent owner to add them.")

    missing = hdr.missing()
    if hdr.delivery_date and hdr.delivery_date < min_d.isoformat():
        missing = missing + [f"a delivery date from {min_d:%d %b %Y}"]
    if st.button("Continue →", type="primary", disabled=bool(missing)):
        state.set_step("items")
        st.rerun()
    if missing:
        st.caption("Required: " + ", ".join(missing))
