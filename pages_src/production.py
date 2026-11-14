"""Production sheet: what to produce from submitted indents (spec 5.8)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core.auth import User
from core.production_calc import aggregate, filter_lines
from core.sheets import SheetError
from pages_src import common


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Production sheet")
    try:
        df = indents.read_lines()
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "Data could not be loaded.")
        return

    summ = indents.summary(df)
    allowed = None
    if not user.is_owner:
        allowed = set(summ.loc[summ["created_by"].str.lower() == user.email, "indent_id"])
    current = indents.current_rows(df)

    today = config.now_ist().date()
    c = st.columns([1, 1, 2])
    d = c[0].date_input("Delivery date", value=today + timedelta(days=1), format="DD/MM/YYYY")
    cities = sorted(current["city"].unique()) if not current.empty else []
    city = c[1].selectbox("City", ["All cities"] + cities)
    scope = "all indents" if user.is_owner else "indents you created"
    c[2].caption(f"Current version of every submitted or frozen indent · {scope}.")

    lines = filter_lines(current, delivery_date=d.isoformat() if isinstance(d, date) else None,
                         city=None if city == "All cities" else city, allowed_ids=allowed)
    if lines.empty:
        st.info("No submitted indents for this date and city.")
        return

    agg = aggregate(lines, m)
    k = st.columns(4)
    k[0].metric("Indents", lines["indent_id"].nunique())
    k[1].metric("Stores", lines["store"].nunique())
    k[2].metric("Lines", len(lines))
    k[3].metric("Production groups", len(agg))

    st.dataframe(agg, hide_index=True, width="stretch",
                 column_config={"Total Qty": st.column_config.NumberColumn(format="%g"),
                                "Customer SKU Names": st.column_config.TextColumn(width="large")})
    fname = f"production_{d.isoformat()}_{'all' if city == 'All cities' else city}.csv"
    st.download_button("⬇ Download CSV", agg.to_csv(index=False).encode("utf-8"),
                       file_name=fname, mime="text/csv")

    with st.expander("Indents included"):
        inc = summ[summ["indent_id"].isin(set(lines["indent_id"]))]
        st.dataframe(pd.DataFrame({
            "Indent": inc["indent_id"], "Status": inc["status"], "Ver": inc["version"],
            "Customer": inc["customer"], "Store": inc["store"], "Time": inc["expected_time"],
            "Items": inc["lines"], "Created by": inc["created_by"]}),
            hide_index=True, width="stretch")
