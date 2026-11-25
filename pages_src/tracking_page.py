"""Production Tracking page (25 Nov, trial): Pre-Production Actual + Processed in one table with the
BLR_ProdTracking columns. Same rows as the Production_Tracking tab of the Google Sheet."""
from __future__ import annotations

import streamlit as st

from core import config, masters
from core import prod_actual as pa
from core import processed as pr
from core import tracking_sheet as ts
from core.auth import User
from core.sheets import SheetError
from pages_src import common


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Production Tracking")
    try:
        m = masters.load_masters()
        lots = pa.read()
        done = pr.read()
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return
    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="tr_day", format="DD/MM/YYYY")
    all_days = top[1].toggle("All dates", key="tr_all")
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[2]:
            city = st.pills("City", cities, default=cities[0], key="tr_city") or cities[0]
    if city and not lots.empty and "city" in lots.columns:
        lots = lots[lots["city"].astype(str) == city]
    df = ts.frame(ts.build(lots, done), None if all_days else day.isoformat())
    if df.empty:
        st.info("Nothing on the tables for this date yet. Start on **Pre-Production Actual**.")
        return

    pending = int((df["Cux Lot"] == "").sum())
    used = df["Actual NW used for Production Kgs (J = H - I)"].map(pr._f).sum()
    mt = df["MT Ready in Kgs (K = D1*C + D2)"].map(pr._f).sum()
    c = st.columns(4)
    c[0].metric("Rows", len(df))
    c[1].metric("Not processed", pending)
    c[2].metric("Used kg", f"{used:,.1f}")
    c[3].metric("Efficiency", f"{round(mt / used * 100)}%" if used else "–")

    eff = ts.HEADERS[ts.EFF_COL]

    def _colour(val):
        rgb = ts.eff_rgb(val)
        return "" if rgb is None else "background-color:rgb({},{},{})".format(*[int(x * 255) for x in rgb])
    shown = df.map(lambda v: f"{v:g}" if isinstance(v, float) else v)
    st.dataframe(shown.style.map(_colour, subset=[eff]), hide_index=True, width="stretch")
    st.caption("Same columns as BLR_ProdTracking · also in the **Production_Tracking** tab of the Google Sheet "
               "(rewritten after every save).")
    b = st.columns([1, 2, 4])
    label = "all" if all_days else day.isoformat()
    b[0].download_button("CSV", data=lambda: df.to_csv(index=False).encode(),
                         file_name=f"production_tracking_{label}.csv", mime="text/csv", key="tr_csv",
                         on_click="ignore", icon=":material/download:")
    if b[1].button("Update sheet tab", icon=":material/sync:", key="tr_pub"):
        n = ts.publish()
        st.toast("Production_Tracking tab updated" if n >= 0 else "Could not update the sheet tab")
