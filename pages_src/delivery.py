"""Delivery choices at the top of the Indent page: day, city, customer, store, time."""
from __future__ import annotations

from html import escape

from datetime import date, time

import streamlit as st

from core import config, indents
from core.masters import Masters
from core.sheets import SheetError
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


def _index(options: list[str], value: str) -> int | None:
    return options.index(value) if value in options else None


def _slots() -> list[str]:
    start, end = config.delivery_window()
    out = []
    for h in range(24):
        for mm in (0, 30):
            t = f"{h:02d}:{mm:02d}"
            if start <= t <= end:
                out.append(t)
    return out


TIME_SLOTS = _slots()  # 10:00 AM ... 8:00 PM in 30-minute steps


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
    start, end = config.delivery_window()
    if parsed is None:
        common.flash("error", f"'{raw}' is not a time. Type it like 6:45 PM or 18:45, "
                              "or pick a slot from the list.")
    elif not start <= parsed <= end:
        common.flash("error", f"{fmt_slot(parsed)} is outside delivery hours "
                              f"({fmt_slot(start)} to {fmt_slot(end)}).")
    else:
        state.set_header_field("expected_time", parsed)
    _bump()


def fmt_slot(hhmm: str) -> str:
    """'06:30' -> '06:30 AM'."""
    try:
        return time.fromisoformat(hhmm).strftime("%I:%M %p")
    except ValueError:
        return hhmm


def _my_cities(m: Masters) -> list[str]:
    """Cities this user may place indents in (sales users with cities set)."""
    u = st.session_state.get("user") or {}
    cities = m.cities()
    allowed = {c.casefold() for c in (u.get("cities") or [])}
    if u.get("role") not in ("owner", "owner_full") and allowed:
        cities = [c for c in cities if c.casefold() in allowed]
    return cities


def _drop_stale(m: Masters) -> None:
    """A restored draft may hold a city / customer / store / time that is no
    longer in the sheet. For new indents, clear those so the lists match."""
    ind = state.get()
    if ind["mode"] == "edit":
        return
    h = ind["header"]
    dropped = []
    if h.get("city") and h["city"] not in _my_cities(m):
        dropped.append(h["city"])
        h.update(city="", customer="", store="")
    if h.get("customer") and h["customer"] not in _my_customers(m, h.get("city", "")):
        dropped.append(h["customer"])
        h.update(customer="", store="")
    if h.get("store") and h["store"] not in _my_stores(m, h.get("city", ""), h.get("customer", "")):
        dropped.append(h["store"])
        h["store"] = ""
    start, end = config.delivery_window()
    t = h.get("expected_time")
    if t and (parse_time(t) != t or not start <= t <= end):
        h["expected_time"] = ""  # invalid or outside delivery hours (typed in-range times are kept)
    if dropped:
        if ind["lines"]:
            state.set_lines([], structural=True)
        state.mark_dirty(force=True)
        _bump()
        st.info("Your saved draft used " + ", ".join(dropped)
                + ", which is no longer in the Google Sheet, so it was cleared. Please choose again.")


def _open_existing(indent_id: str) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is None:
        return
    state.open_for_edit(cur, None, created_at=indents.created_at(df, indent_id))
    common.flash("info", f"{indent_id} opened for editing. Change what you need, then press Update indent.")


def _duplicate_notice(hdr) -> bool:
    """Warn (and return True) when this store already has an indent that day."""
    if not (hdr.delivery_date and hdr.store):
        return False
    try:
        df = indents.read_lines()
    except SheetError:
        return False
    ind = state.get()
    dup = indents.find_duplicate(df, hdr, exclude_id=ind["indent_id"] if ind["mode"] == "edit" else "")
    if not dup:
        return False
    cur = indents.snapshot(df, dup)
    st.warning(indents.duplicate_message(dup, hdr))
    if cur is not None and cur.status == "Submitted" and indents.can_edit(cur.header.delivery_date,
                                                                          customer=cur.header.customer):
        st.button(f"Edit {dup}", icon=":material/edit:", on_click=_open_existing, args=(dup,),
                  type="primary",
                  help="Opens the existing indent; anything entered here for a new indent is replaced.")
    else:
        st.caption(f"{dup} can no longer be edited (locked, frozen with a PO or past its cutoff).")
    return True


def _my_stores(m: Masters, city: str, customer: str) -> list[str]:
    """Stores of this city + customer the user may use (store-limited sales users)."""
    stores = m.stores_for(city, customer) if city and customer else []
    u = st.session_state.get("user") or {}
    allowed = {x.casefold() for x in (u.get("stores") or [])}
    if u.get("role") not in ("owner", "owner_full") and allowed:
        stores = [x for x in stores if " ".join(x.split()).casefold() in allowed]
    new = new_party()
    if new and _same(new["city"], city) and _same(new["customer"], customer) and \
            not any(_same(x, new["store"]) for x in stores):
        stores = stores + [new["store"]]
    return stores


NEW_PARTY = "mt_new_party"


def _same(a, b) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def new_party() -> dict | None:
    """A customer / store typed on Create indent (20 Nov), not in the sheet yet: it is
    added to the Customer List when the indent is submitted."""
    return st.session_state.get(NEW_PARTY)


def _my_customers(m: Masters, city: str) -> list[str]:
    """Customers that have at least one store this user may use (all, if unrestricted)."""
    customers = m.customers(city) if city else []
    u = st.session_state.get("user") or {}
    if u.get("role") not in ("owner", "owner_full") and u.get("stores"):
        customers = [c for c in customers if _my_stores(m, city, c)]
    new = new_party()
    if new and _same(new["city"], city) and not any(_same(c, new["customer"]) for c in customers):
        customers = customers + [new["customer"]]
    return customers


def _new_party_box(hdr) -> None:
    """＋ New customer / store: typed names; the store is added to the Customer List on Submit."""
    with st.popover("＋ New customer / store"):
        cust = st.text_input("Customer", value=hdr.customer or "", key=_k("new_cust"))
        store = st.text_input("Store", key=_k("new_store"), placeholder="e.g. Bigbasket - PTP Hyderabad")
        if st.button("Use", type="primary", key=_k("new_use"), disabled=not (cust.strip() and store.strip())):
            st.session_state[NEW_PARTY] = {"city": hdr.city, "customer": " ".join(cust.split()),
                                           "store": " ".join(store.split())}
            state.set_header_field("customer", " ".join(cust.split()))
            state.set_header_field("store", " ".join(store.split()))
            _bump()
            st.rerun()


def _date_options() -> list[str]:
    """Delivery days offered: today (until its 11 PM cutoff) and tomorrow; a
    correction keeps its own date in the list."""
    lo, hi = indents.delivery_bounds()
    days = []
    d = lo
    while d <= hi:
        if indents.can_edit(d.isoformat()):
            days.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 1)
    keep = state.keep_date()
    if keep and keep not in days:
        days = [keep] + days
    return days


def _fmt_day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    today = config.now_ist().date()
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get((d - today).days, d.strftime("%a"))
    return f"{word} · {d:%a %d %b}"


def _on_pick(key: str, field: str) -> None:
    """Pill / segmented control changed."""
    new = st.session_state.get(key) or ""
    hdr = state.header()
    old = getattr(hdr, field)
    if new == old:
        return
    state.set_header_field(field, new)
    if field == "city":
        state.set_header_field("customer", "")
        state.set_header_field("store", "")
        _clear_items("City")
    elif field == "customer":
        state.set_header_field("store", "")
        _clear_items("Customer")
    _bump()


def _placed_map(day: str, city: str, customer: str) -> dict[str, tuple[str, str]]:
    """store -> (indent_id, status) for indents already placed that day."""
    if not (day and city and customer):
        return {}
    try:
        cur = indents.current_rows(indents.read_lines())
    except SheetError:
        return {}
    if cur.empty:
        return {}
    norm = lambda v: " ".join(str(v).split()).casefold()  # noqa: E731
    sub = cur[(cur["delivery_date"].astype(str) == day) & (cur["city"].map(norm) == norm(city))
              & (cur["customer"].map(norm) == norm(customer))]
    out = {}
    for r in sub.drop_duplicates("indent_id").itertuples():
        out[norm(r.store)] = (r.indent_id, r.status)
    return out


def render(m: Masters) -> bool:
    """Delivery choices at the top of the Indent page, as pill buttons.
    Returns True when date, city, customer and store are chosen and the store
    has no other indent that day (then the items section is shown)."""
    _drop_stale(m)
    hdr = state.header()
    ind = state.get()

    with st.container(border=True, key="mt_delivery_card"):
        if ind["mode"] == "edit":
            # a saved indent keeps its day, city, customer and store; only the time can change
            st.markdown(
                "<div class='mt-strip'>"
                f"<span><b>Delivery</b>{escape(_fmt_day(hdr.delivery_date))}</span>"
                f"<span><b>City</b>{escape(hdr.city)}</span>"
                f"<span><b>Customer</b>{escape(hdr.customer)}</span>"
                f"<span><b>Store</b>{escape(hdr.store)}</span></div>", unsafe_allow_html=True)
            st.caption("🔒 Delivery day, city, customer and store of a saved indent cannot be changed.")
        else:
            # 1. Delivery day
            days = _date_options()
            if hdr.delivery_date and hdr.delivery_date not in days:
                state.set_header_field("delivery_date", "")
                hdr = state.header()
            if not hdr.delivery_date and days and ind["mode"] != "edit":
                state.set_header_field("delivery_date", days[0])   # first open day, ready to use
                hdr = state.header()
            k = _k("day")
            st.segmented_control("Delivery day", days, default=hdr.delivery_date or None, key=k,
                                 format_func=_fmt_day, on_change=_on_pick, args=(k, "delivery_date"))
            today = config.now_ist().date()
            if today.isoformat() not in days:
                st.caption(f"Orders for today closed at {indents.deadline_text(today.isoformat())[-8:]}. "
                           "Next delivery day is shown.")

            # 2. City (only asked when the user has more than one)
            cities = _my_cities(m)
            if hdr.city and hdr.city not in cities and ind["mode"] == "edit":
                cities = cities + [hdr.city]
            if not cities:
                st.warning("No city is available to you yet. Ask the indent owner to check your access.")
                return False
            if len(cities) == 1 and hdr.city != cities[0]:
                _on_pick_value("city", cities[0])
                hdr = state.header()
            if len(cities) > 1:
                k = _k("city")
                st.pills("City", cities, default=hdr.city or None, key=k, on_change=_on_pick,
                         args=(k, "city"))
            else:
                st.markdown(f"<span class='mt-muted'>City</span>&nbsp; <b>{cities[0]}</b>",
                            unsafe_allow_html=True)

            # 3. Customer
            customers = _my_customers(m, hdr.city)
            if hdr.customer and hdr.customer not in customers and ind["mode"] == "edit":
                customers = customers + [hdr.customer]
            k = _k("customer")
            st.pills("Customer", customers, default=hdr.customer or None, key=k, on_change=_on_pick,
                     args=(k, "customer"), disabled=not hdr.city)
            if hdr.city and ind["mode"] != "edit":
                _new_party_box(hdr)

            # 4. Store (shows which ones already have an indent that day)
            if hdr.customer:
                stores = _my_stores(m, hdr.city, hdr.customer)
                if hdr.store and hdr.store not in stores and ind["mode"] == "edit":
                    stores = stores + [hdr.store]
                placed = _placed_map(hdr.delivery_date, hdr.city, hdr.customer)
                mine = ind["indent_id"] if ind["mode"] == "edit" else ""

                def store_label(x: str) -> str:
                    info = placed.get(" ".join(x.split()).casefold())
                    if not info or info[0] == mine:
                        return x
                    return f"{x}  ✓ {'PO done' if info[1] == 'Frozen' else 'placed'}"

                if stores:
                    k = _k("store")
                    st.pills("Store", stores, default=hdr.store or None, key=k, format_func=store_label,
                             on_change=_on_pick, args=(k, "store"))
                else:
                    st.info(f"No stores for {hdr.customer} in {hdr.city} yet: use ＋ New customer / store.")

        # 5. Expected delivery time: the store's usual time (Delivery times page) when none is set yet
        if hdr.store and not hdr.expected_time and ind["mode"] != "edit":
            from core import store_settings
            usual = store_settings.time_for(None, hdr.city, hdr.customer, hdr.store)
            if usual:
                state.set_header_field("expected_time", usual)
                hdr = state.header()
        c5, c6 = st.columns([1, 2])
        k = _k("time")
        slots = TIME_SLOTS if hdr.expected_time in TIME_SLOTS or not hdr.expected_time \
            else TIME_SLOTS + [hdr.expected_time]
        c5.selectbox("Expected delivery time", slots, index=_index(slots, hdr.expected_time), key=k,
                     format_func=fmt_slot, placeholder="Pick a slot or type e.g. 6:45 PM",
                     accept_new_options=True, on_change=_on_time, args=(k,),
                     help="Between 10:00 AM and 8:00 PM. Pick a 30-minute slot, or type a time "
                          "(6:45 PM, 18:45) and press Enter")
        if ind["mode"] == "edit" and ind.get("po_fix"):
            c6.caption("Correcting this indent to match the customer's PO (allowed after the cutoff).")
        elif hdr.delivery_date:
            c6.caption(f"Edits allowed until **{indents.deadline_text(hdr.delivery_date, hdr.customer)}**.")

    hdr = state.header()
    if not (hdr.delivery_date and hdr.city and hdr.customer and hdr.store):
        return False
    if _duplicate_notice(hdr):
        return False
    return True


def _on_pick_value(field: str, value: str) -> None:
    if getattr(state.header(), field) != value:
        state.set_header_field(field, value)
        _bump()
