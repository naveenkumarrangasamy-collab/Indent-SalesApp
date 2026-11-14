"""Production reports: the production sheet and the City / SKU report."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core.auth import User
from core.production_calc import (aggregate, city_sku_report, default_date,
                                  delivery_dates, filter_lines)
from core.sheets import SheetError
from pages_src import common

ALL_DATES = "All dates"


def _fmt_date(d: str) -> str:
    if d == ALL_DATES:
        return d
    try:
        return date.fromisoformat(d).strftime("%a, %d %b %Y")
    except ValueError:
        return d


def _filtered(user: User, prefix: str):
    """Shared filters. Returns (lines, summary, label) or None when there is
    nothing to show (a message has been written)."""
    try:
        df = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return None
    summ = indents.summary(df)
    current = indents.current_rows(df)
    if not user.is_owner:
        mine = set(summ.loc[summ["created_by"].str.lower() == user.email, "indent_id"])
        current = current[current["indent_id"].isin(mine)]
        summ = summ[summ["indent_id"].isin(mine)]
    if current.empty:
        st.info("No submitted indents yet." if user.is_owner
                else "You have not submitted any indents yet.")
        return None

    dates = delivery_dates(current)
    counts = current.groupby("delivery_date")["indent_id"].nunique().to_dict()
    options = dates + [ALL_DATES]
    today = config.now_ist().date().isoformat()
    pick = default_date(dates, today)
    c = st.columns([1.3, 1, 1, 1.6])
    d = c[0].selectbox("Delivery date", options, index=options.index(pick) if pick else len(options) - 1,
                       key=f"{prefix}_date",
                       format_func=lambda x: _fmt_date(x) + (f"  ({counts.get(x, 0)} indents)"
                                                             if x in counts else ""))
    cities = sorted(current["city"].unique())
    city = c[1].selectbox("City", ["All cities"] + cities, key=f"{prefix}_city")
    custs = sorted(current["customer"].unique())
    cust = c[2].selectbox("Customer", ["All customers"] + custs, key=f"{prefix}_cust")
    scope = "all indents" if user.is_owner else "indents you created"
    c[3].caption(f"Current version of every submitted or frozen indent · {scope}. "
                 "Only dates that have indents are listed.")

    lines = filter_lines(current, delivery_date=None if d == ALL_DATES else d,
                         city=None if city == "All cities" else city, allowed_ids=None)
    if cust != "All customers":
        lines = lines[lines["customer"] == cust]
    label = "_".join(x for x in ("all-dates" if d == ALL_DATES else d,
                                 "" if city == "All cities" else city,
                                 "" if cust == "All customers" else cust) if x)
    if lines.empty:
        st.info("No indents for these filters.")
        return None
    k = st.columns(4)
    k[0].metric("Indents", lines["indent_id"].nunique())
    k[1].metric("Stores", lines["store"].nunique())
    k[2].metric("Lines", len(lines))
    k[3].metric("SKUs", lines["customer_sku_name"].nunique())
    return lines, summ, label


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Production sheet")
    st.caption("What to produce: Parent SKU → Variety → Lot → Lot size.")
    res = _filtered(user, "ps")
    if res is None:
        return
    lines, summ, label = res
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        return
    agg = aggregate(lines, m, with_spec=config.show_spec())
    st.dataframe(agg, hide_index=True, width="stretch",
                 column_config={"Total Qty": st.column_config.NumberColumn(format="%g"),
                                "Customer SKU Names": st.column_config.TextColumn(width="large")})
    st.download_button("⬇ Download CSV", agg.to_csv(index=False).encode("utf-8"),
                       file_name=f"production_{label}.csv", mime="text/csv")
    with st.expander("Indents included"):
        inc = summ[summ["indent_id"].isin(set(lines["indent_id"]))]
        st.dataframe(pd.DataFrame({
            "Indent": inc["indent_id"], "Status": inc["status"], "Ver": inc["version"],
            "Delivery": inc["delivery_date"], "City": inc["city"], "Customer": inc["customer"],
            "Store": inc["store"], "Time": inc["expected_time"], "Items": inc["lines"],
            "Created by": inc["created_by"]}), hide_index=True, width="stretch")


def render_city_sku(user: User) -> None:
    common.show_flash()
    st.markdown("### City / SKU report")
    st.caption("Total quantity per city and customer SKU, with lot and lot size.")
    res = _filtered(user, "cs")
    if res is None:
        return
    lines, _, label = res
    rep = city_sku_report(lines)
    for city, part in rep.groupby("City", sort=False):
        by_lot = part.groupby("Lot")["Qty"].sum()
        st.markdown(f"**{city}** · {len(part)} SKUs · "
                    + " · ".join(f"{q:g} {lot}" for lot, q in by_lot.items()))
    show = rep if rep["Variety"].astype(bool).any() else rep.drop(columns=["Variety"])
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                "Customer SKU Name": st.column_config.TextColumn(width="large")})
    st.download_button("⬇ Download CSV", rep.to_csv(index=False).encode("utf-8"),
                       file_name=f"city_sku_{label}.csv", mime="text/csv")
