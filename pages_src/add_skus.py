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
                     "Result": "🆕 will be added" if parent else "🔴 new Parent SKU: add by hand"})
    return rows


def render(m: Masters | None, user) -> None:
    if m is None:
        return
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

    def color(r):
        bg = "#e0ecff" if r["Result"].startswith("🆕") else "#fde2e1" if r["Result"].startswith("🔴") else ""
        return [f"background-color:{bg}" if bg else ""] * len(r)
    st.dataframe(pd.DataFrame(rows).style.apply(color, axis=1), hide_index=True, width="stretch")
    new = [r for r in rows if r["Result"].startswith("🆕")]
    if st.button(f"Add {len(new)} to the sheet", type="primary", disabled=not new, key="as_go",
                 icon=":material/add:"):
        items = []
        for r in new:
            parent, sku = r["Parent SKU"], r["Our SKU name"]
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
        common.flash("success", "Added: " + ", ".join(r["Our SKU name"] for r in new) + ". " + "; ".join(notes))
        st.rerun()
