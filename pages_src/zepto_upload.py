"""Zepto Excel upload (Bangalore): Zepto's indent file -> one indent per Zepto
warehouse column. Products are matched to our Zepto SKU names; any product
that cannot be matched must be picked (or skipped) before indents are created."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import bulk_import, config, indents, masters, po_reader, zepto_import
from core.auth import User
from core.models import fmt_num
from core.sheets import SheetError
from pages_src import common
from pages_src.delivery import TIME_SLOTS, fmt_slot
from pages_src.indent_actions import HOW, _item_map, _learn

CUSTOMER = "Zepto"
SKIP = "— skip this product"
NO_STORE = "— not used"


def _city(m) -> str:
    cities = m.cities()
    return next((c for c in cities if "bangalore" in c.casefold() or "bengaluru" in c.casefold()),
                cities[0] if cities else "")


def _days() -> list[str]:
    lo, hi = indents.delivery_bounds()
    out, d = [], lo
    while d <= hi:
        if indents.can_edit(d.isoformat(), customer=CUSTOMER):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Zepto Excel upload · Bangalore")
    st.caption("Upload Zepto's indent Excel (Product Name, UOM, EAN, … one qty column per warehouse). "
               "Each warehouse column with qty becomes one indent. Check the SKU matches, then create.")
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        return
    city = _city(m)
    stores = m.stores_for(city, CUSTOMER)
    if not stores:
        st.error(f"No Zepto stores for {city} in the Customer List tab.")
        return
    rev = st.session_state.get("zx_rev", 0)
    up = st.file_uploader("Zepto indent Excel", type=["xlsx", "xls"], key=f"zx_file_{rev}")
    if up is None:
        return
    try:
        zf = zepto_import.read(up.getvalue())
    except bulk_import.ImportFileError as e:
        st.error(str(e))
        return
    cols = [c for c, q in zf.qty.items() if sum(q) > 0]
    if not cols:
        st.warning("No quantities in the file.")
        return

    # 1. delivery, time, price
    days = _days()
    if not days:
        st.error("No delivery date is open for Zepto right now (cutoff 1 AM on the delivery day).")
        return
    c = st.columns([1.2, 1, 1])
    pick = zf.pack_date if zf.pack_date in days else days[-1]
    day = c[0].selectbox("Delivery date", days, index=days.index(pick), key="zx_day",
                         format_func=lambda d: date.fromisoformat(d).strftime("%a %d %b"))
    if zf.pack_date and zf.pack_date != day:
        c[0].caption(f"Pack date in the file: {zf.pack_date}"
                     + ("" if zf.pack_date in days else " (closed for Zepto)"))
    slot = c[1].selectbox("Expected delivery time", TIME_SLOTS, format_func=fmt_slot, key="zx_time")
    price = c[2].number_input("Price for every line", min_value=0.01, value=1.0, step=1.0, key="zx_price")

    # 2. warehouse column -> store
    st.markdown("**Warehouse → store**")
    sc = st.columns(len(cols))
    col_store = {}
    for i, col in enumerate(cols):
        guess = zepto_import.guess_store(col, stores)
        opts = stores + [NO_STORE]
        col_store[col] = sc[i].selectbox(f"{col} · {fmt_num(sum(zf.qty[col]))}", opts,
                                         index=opts.index(guess) if guess in opts else len(opts) - 1,
                                         key=f"zx_store_{col}")
    used = [s for s in col_store.values() if s != NO_STORE]
    if len(used) != len(set(used)):
        st.warning("Two warehouse columns go to the same store: their quantities are added together.")

    # 3. products -> our SKU
    names = []
    for p in m.parents(city, CUSTOMER):
        names += m.sku_names(city, CUSTOMER, p)
    names = list(dict.fromkeys(names))
    prods = po_reader.match(zf.products, names, _item_map(CUSTOMER))
    base = pd.DataFrame([{"Zepto product": x.name, "EAN": x.code, "Qty": fmt_num(x.qty),
                          "Our SKU": x.sku or None, "Match": HOW.get(x.how, "")} for x in prods])
    ed = st.data_editor(base, key=f"zx_map_{rev}", hide_index=True, width="stretch",
                        disabled=["Zepto product", "EAN", "Qty", "Match"],
                        column_config={"Our SKU": st.column_config.SelectboxColumn(
                            options=names + [SKIP], width="large")})
    picks = [p if isinstance(p, str) and p.strip() else None for p in ed["Our SKU"]]
    missing = [x.name for x, p in zip(prods, picks) if p is None and x.qty > 0]
    if missing:
        st.error(f"**{len(missing)} product(s) not mapped:** " + "; ".join(missing)
                 + ". Pick **Our SKU** for each (or skip it). If the SKU is not in the list, add it to the "
                 "**All Cux City** tab (Zepto) first, then press **Refresh master**.")
    if st.button("Refresh master", icon=":material/refresh:", key="zx_refresh"):
        masters.clear_cache()
        st.rerun()

    # 4. the indents
    rows, n = [], 0
    for col, store in col_store.items():
        if store == NO_STORE:
            continue
        for x, p, q in zip(prods, picks, zf.qty[col]):
            if q > 0 and p and p != SKIP:
                n += 1
                rows.append({"row": n, "sheet": "zepto", "delivery_date": day, "city": city,
                             "customer": CUSTOMER, "store": store, "parent": "", "item": p, "qty": q,
                             "price": None})
    if not rows:
        return
    groups = bulk_import.plan(pd.DataFrame(rows), m, city=city, price=price, expected_time=slot)
    try:
        df = indents.read_lines(fresh=True)
    except SheetError as e:
        common.sheet_error(e)
        return
    table = []
    for g in groups:
        g.dup = indents.find_duplicate(df, g.header) or ""
        if g.new_skus:
            g.errors.append("not in the master: " + ", ".join(s["Customer SKU Name"] for s in g.new_skus))
        table.append({"Store": g.header.store, "Delivery": g.header.delivery_date, "Items": len(g.lines),
                      "Qty": fmt_num(sum(float(x.qty) for x in g.lines)),
                      "Status": (f"Already placed ({g.dup}): edit that indent instead" if g.dup
                                 else "; ".join(g.errors) or "Ready")})
    st.markdown(f"**{len(groups)} indent(s) to create**")
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    ready = [g for g in groups if not g.errors and not g.dup]
    if st.button(f"Create {len(ready)} Zepto indent(s)", type="primary", icon=":material/add_task:",
                 disabled=bool(missing) or not ready, key="zx_go"):
        stamp = config.now_iso()
        _learn([{"Customer": CUSTOMER, "PO Item Code": x.code, "PO Item Name": x.name,
                 "Customer SKU Name": p, "Updated_At": stamp}
                for x, p in zip(prods, picks) if p and p != SKIP and (x.how in ("close", "") or p != x.sku)])
        made, failed = [], []
        with st.spinner("Creating indents…"):
            for g in ready:
                try:
                    made.append(f"{indents.submit_new(g.header, g.lines, user.email)} · {g.header.store}")
                except SheetError as e:
                    failed.append(f"{g.label}: {e}")
        if made:
            common.flash("success", f"Created {len(made)} Zepto indent(s): " + "; ".join(made))
        if failed:
            st.error("Not created: " + "; ".join(failed))
        else:
            st.session_state["zx_rev"] = rev + 1
            st.rerun()
