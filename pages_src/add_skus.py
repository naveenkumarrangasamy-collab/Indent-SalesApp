"""Access → Add SKUs (owners): put new Customer SKU Names into All Cux City and the
New tab without placing an indent. Paste names as they appear in the order
('Kiwi Sungold - 2 PIECE') or in our style ('2PC - Kiwi Sungold'). A preview shows,
per line, the name we will use and whether it already exists (exact name), is new
(added, New-tab spec cells in yellow) or has a new Parent SKU (never added)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import master_add, masters
from core.masters import Masters
from core.sheets import SheetError, get_backend
from pages_src import common


def _exact(s: str) -> str:
    return " ".join(str(s).casefold().split())


def plan(m: Masters, city: str, customer: str, text: str) -> list[dict]:
    names = {}
    for p in m.parents(city, customer):
        for n in m.sku_names(city, customer, p):
            names[_exact(n)] = n
    parents = []
    for c in m.customers(city):
        parents += m.parents(city, c)
    parents = list(dict.fromkeys(parents))
    rows, seen = [], set()
    for raw in text.splitlines():
        raw = raw.strip().strip("\t|,;")
        if not raw:
            continue
        ours = master_add.new_sku_name(raw)
        hit = names.get(_exact(ours)) or names.get(_exact(raw))
        if hit:
            rows.append({"Pasted": raw, "Parent SKU": m.parent_of(city, customer, hit), "Our SKU name": hit,
                         "Result": "✓ already in master"})
            continue
        if _exact(ours) in seen:
            continue
        seen.add(_exact(ours))
        parent = master_add.guess_parent(raw, parents)
        rows.append({"Pasted": raw, "Parent SKU": parent, "Our SKU name": ours,
                     "Result": "🆕 will be added" if parent else "🔴 pick Parent SKU"})
    return rows


def _stores(m: Masters, user) -> None:
    """Add a city / customer / store to the Customer List (a new city starts here)."""
    with st.expander("Add a store (new city or customer)"):
        c = st.columns(3)
        city = c[0].text_input("City", key="as_s_city", placeholder="PTP Hyderabad")
        cust = c[1].text_input("Customer", key="as_s_cust", placeholder="Swiggy")
        store = c[2].text_input("Store", key="as_s_store", placeholder="Swiggy - Hyderabad")
        if st.button("Add store", key="as_s_go", disabled=not (city.strip() and cust.strip() and store.strip())):
            city, cust, store = (" ".join(x.split()) for x in (city, cust, store))
            if store.casefold() in {x.casefold() for x in m.stores_for(city, cust)}:
                st.info("That store is already in the Customer List.")
                return
            from core import bulk_import
            try:
                notes = bulk_import.add_to_master(get_backend(), [],
                                                  [{"City": city, "Customer": cust, "Store Name": store}])
            except SheetError as e:
                st.error(f"Could not add: {e}")
                return
            masters.clear_cache()
            for k in ("as_s_store",):
                st.session_state.pop(k, None)
            common.flash("success", f"Added {city} · {cust} · {store}. " + "; ".join(notes))
            st.rerun()


def render(m: Masters | None, user) -> None:
    if m is None:
        return
    _stores(m, user)
    st.caption("Add new SKU names to All Cux City and the New tab (spec cells in yellow, to fill). "
               "Only exact names count as existing.")
    c = st.columns(2)
    cities = m.cities()
    city = c[0].selectbox("City", cities, key="as_city")
    customers = m.customers(city) if city else []
    customer = c[1].selectbox("Customer", customers, key="as_cust")
    text = st.text_area("SKU names, one per line", key="as_text", height=140,
                        placeholder="Kiwi Sungold - 2 PIECE\n2PC - Snacky Apple")
    if not (city and customer and text.strip()):
        return
    rows = plan(m, city, customer, text)
    if not rows:
        return
    parents = []
    for c in m.customers(city):
        parents += m.parents(city, c)
    parents = sorted(set(p for p in parents if p))
    extra = " ".join(st.text_input("New Parent SKU (only when approved, e.g. Garlic)", key="as_newp").split())
    if extra and extra.casefold() not in {p.casefold() for p in parents}:
        parents.append(extra)
        for r in rows:                          # fill it where the name has that word
            if r["Result"].startswith("🔴") and master_add.guess_parent(r["Pasted"], [extra]):
                r["Parent SKU"], r["Result"] = extra, "🆕 will be added (new parent)"
    df = pd.DataFrame(rows)
    st.caption("🆕 = will be added · 🔴 = pick an existing Parent SKU to add it (a new fruit is never added here)")
    ed = st.data_editor(
        df, hide_index=True, width="stretch", key=f"as_ed_{hash(text)}_{extra}",
        disabled=["Pasted", "Result"],
        column_config={"Parent SKU": st.column_config.SelectboxColumn("Parent SKU", options=parents),
                       "Our SKU name": st.column_config.TextColumn("Our SKU name")})
    new = [r for r in ed.to_dict("records")
           if not r["Result"].startswith("✓") and r.get("Parent SKU") and str(r.get("Our SKU name", "")).strip()]
    if st.button(f"Add {len(new)} to the sheet", type="primary", disabled=not new, key="as_go",
                 icon=":material/add:"):
        items = []
        for r in new:
            parent, sku = r["Parent SKU"], " ".join(str(r["Our SKU name"]).split())
            need = m.needs_variety(parent)
            items.append({"Parent SKU": parent, "Customer SKU Name": sku,
                          "Variety": m.variety_from_name(parent, sku) if need else "",
                          "Lot": master_add.lot_of(sku), "needs_variety": need})
        try:
            with st.spinner("Adding to the sheet…"):
                notes = master_add.add_items(get_backend(), city, customer, items, user.email)
        except SheetError as e:
            st.error(f"Could not add: {e}")
            return
        masters.clear_cache()
        st.session_state.pop("as_text", None)
        common.flash("success", "Added: " + ", ".join(i["Customer SKU Name"] for i in items) + ". " + "; ".join(notes))
        st.rerun()
