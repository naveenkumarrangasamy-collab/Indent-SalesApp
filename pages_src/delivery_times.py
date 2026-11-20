"""Delivery times (20 Nov, owners): the usual expected delivery time of every store.
Create indent and Bulk indents start from it; a store without one gets a time typed
once (in Bulk indents) and it is saved here."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import masters, store_settings
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common
from pages_src.delivery import TIME_SLOTS, fmt_slot

NONE = "—"


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Delivery times")
    st.caption("The usual delivery time of each store. New indents start from it; it can still be changed "
               "on an indent.")
    if not user.is_owner:
        st.error("Only owners can change delivery times.")
        return
    try:
        m = masters.load_masters()
        saved = store_settings.times()
    except SheetError as e:
        common.sheet_error(e, "Could not load the stores.")
        return
    cities = m.cities()
    if not cities:
        st.info("No stores in the Customer List yet.")
        return
    city = st.pills("City", cities, default=cities[0], key="dt_city") or cities[0]
    rows = []
    for cust in m.customers(city):
        for store in m.stores_for(city, cust):
            t = saved.get(store_settings._k(city, cust, store), "")
            rows.append({"Customer": cust, "Store": store, "Time": fmt_slot(t) if t else NONE})
    if not rows:
        st.info(f"No stores for {city} yet (Access → Add SKUs → Add a store).")
        return
    df = pd.DataFrame(rows)
    missing = int((df["Time"] == NONE).sum())
    if missing:
        st.warning(f"{missing} store(s) have no delivery time yet.")
    labels = [NONE] + [fmt_slot(t) for t in TIME_SLOTS]
    ed = st.data_editor(df, key=f"dt_ed_{city}", hide_index=True, width="stretch", disabled=["Customer", "Store"],
                        column_config={"Time": st.column_config.SelectboxColumn(options=labels, required=True)})
    back = {fmt_slot(t): t for t in TIME_SLOTS}
    if st.button("Save delivery times", type="primary", icon=":material/save:", key="dt_save"):
        out = [{"City": city, "Customer": r["Customer"], "Store": r["Store"], "Time": back.get(r["Time"], "")}
               for r in ed.to_dict("records")]
        try:
            n = store_settings.save_times(get_backend(), out, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        common.flash("success", f"Delivery times saved ({n} store(s) with a time).")
        st.rerun()
