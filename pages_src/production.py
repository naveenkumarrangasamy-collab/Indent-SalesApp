"""Production reports (owner and warehouse; not sales):
1. Production sheet - total to produce and grade, all customers together.
2. Batching sheet   - the same stock split per delivery point for dispatch."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core.auth import User
from core.pdf_report import sections_pdf, table_pdf
from core.production_calc import (batching, default_date, delivery_dates,
                                  filter_lines, not_in_base, production, spec_mapping_list, unmapped)
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
        summ = indents.visible_to(summ, user)
        current = current[current["indent_id"].isin(set(summ["indent_id"]))]
    if current.empty:
        st.info("No submitted indents yet." if user.is_owner or user.city_scoped
                else "You have not submitted any indents yet.")
        return None

    dates = delivery_dates(current)
    counts = current.groupby("delivery_date")["indent_id"].nunique().to_dict()
    options = dates + [ALL_DATES]
    today = config.now_ist().date().isoformat()
    pick = default_date(dates, today)
    c = st.columns([1.3, 1, 2])
    d = c[0].selectbox("Delivery date", options, index=options.index(pick) if pick else len(options) - 1,
                       key=f"{prefix}_date",
                       format_func=lambda x: _fmt_date(x) + (f"  ({counts.get(x, 0)} indents)"
                                                             if x in counts else ""))
    cities = sorted(current["city"].unique())
    if not user.is_owner and len(user.cities) == 1:
        city = user.cities[0]               # mapped to one city: no city filter
        c[1].markdown(f"<span class='mt-muted'>City</span><br><b>{city}</b>", unsafe_allow_html=True)
    else:
        city = c[1].selectbox("City", ["All cities"] + cities, key=f"{prefix}_city")
    scope = indents.scope_text(user)
    c[2].caption(f"All customers together · current version of every submitted or PO-frozen indent · "
                 f"{scope}. Only dates that have indents are listed.")

    lines = filter_lines(current, delivery_date=None if d == ALL_DATES else d,
                         city=None if city == "All cities" else city, allowed_ids=None)
    label = "_".join(x for x in ("all-dates" if d == ALL_DATES else d,
                                 "" if city == "All cities" else city) if x)
    st.session_state[f"{prefix}_desc"] = f"Delivery: {_fmt_date(d)}   City: {city}   All customers   Scope: {scope}"
    if lines.empty:
        st.info("No indents for these filters.")
        return None
    return lines, summ, label


def _guard(user: User) -> bool:
    if not user.sees_production:
        st.error("The production and batching sheets are for the warehouse team and the owner.")
        return False
    return True


def _qty_strip(df: pd.DataFrame, qty: str, lines: pd.DataFrame, unit: str = "Lot") -> None:
    by_lot = df.groupby(unit)[qty].sum() if not df.empty else pd.Series(dtype=float)
    tiles = [("Indents", lines["indent_id"].nunique(), ""), ("Delivery points", lines["store"].nunique(), ""),
             ("Customers", lines["customer"].nunique(), "")]
    tiles += [(f"Total {lot or '(no repacking)'}", f"{q:,.0f}", "to prepare") for lot, q in by_lot.items()]
    st.markdown("<div class='mt-tiles'>" + "".join(
        f"<div class='mt-tile{' good' if sub else ''}'><div class='lbl'>{lbl}</div><div class='val'>{val}</div>"
        f"<div class='sub'>{sub}</div></div>" for lbl, val, sub in tiles) + "</div>", unsafe_allow_html=True)


def _unmapped_warning(lines: pd.DataFrame, m) -> None:
    gaps = unmapped(lines, m)
    if gaps.empty:
        return
    with st.expander(f"⚠️ {len(gaps)} SKU name(s) have no spec yet: they are kept on separate lines "
                     "(\"spec not mapped\") so they are never clubbed with another product", expanded=False):
        st.caption("Add their Spec-Size (and Grade) in the Mapping Whole tab; production then clubs them.")
        st.dataframe(gaps, hide_index=True, width="stretch")


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Production sheet")
    st.caption("Step 1 · what to produce, **all customers together**. Variety, repacking, spec size and origin "
               "come from the **New** tab of the Google Sheet. Customers and delivery points are on the "
               "**Batching sheet**.")
    if not _guard(user):
        return
    res = _filtered(user, "ps")
    if res is None:
        return
    lines, summ, label = res
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        return
    prod = production(lines, m)
    _qty_strip(prod, "Qty", lines, unit="Repacking")
    show = prod if prod["Variety"].astype(bool).any() else prod.drop(columns=["Variety"])
    if len(prod["City"].unique()) == 1:
        show = show.drop(columns=["City"])
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                "Total": st.column_config.TextColumn(
                                    help="All customers clubbed for the same parent SKU, repacking, spec size "
                                         "and lot size, in repacking units (10 + 20 packs of 2 pcs = 30 Punnet)")})
    st.caption("**Total** = all customers clubbed per parent SKU + repacking + spec size + lot size "
               "(e.g. 10 + 20 two-piece packs in punnets = 30 Punnet).")
    gaps = not_in_base(lines, m)
    if not gaps.empty:
        with st.expander(f"⚠️ {len(gaps)} SKU name(s) are not in the New tab: they show as "
                         "\"not in New tab\" and are kept on separate lines", expanded=False):
            st.caption("Add them to the New tab (City, Customer, Parent SKU, Customer SKU Name, variety, "
                       "Spec-Repacking, Spec-Size, Spec-Origin). The app re-reads it every few minutes.")
            st.dataframe(gaps, hide_index=True, width="stretch")
    _downloads("Production sheet", show, f"production_{label}", "ps", lines)
    if user.is_owner:
        _publish("Production sheet", PRODUCTION_TAB, show, lines, user, "ps")
        with st.expander("Spec mapping list (what production uses for every SKU name, and what is missing)"):
            lst = spec_mapping_list(m)
            if lst.empty:
                st.caption("No SKU mapping found.")
            else:
                todo = int((lst["To fill in"] != "complete").sum())
                st.caption(f"{len(lst)} SKU names · {todo} still need Spec-Size and/or Grade in **Mapping Whole** "
                           "(add a **Grade** column there, e.g. 'Regular imported', 'Mini TRM').")
                st.dataframe(lst, hide_index=True, width="stretch")
                from core.reports import xlsx
                st.download_button("Spec mapping list (Excel)", xlsx({"Spec mapping": lst}),
                                   file_name="spec_mapping_list.xlsx", icon=":material/download:",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_batching(user: User) -> None:
    common.show_flash()
    st.markdown("### Batching sheet")
    st.caption("Step 2 · after production and grading: how the ready stock is split per **delivery point** "
               "(city › customer › store), to batch and dispatch each location's order.")
    if not _guard(user):
        return
    res = _filtered(user, "bs")
    if res is None:
        return
    lines, _, label = res
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        return
    bat = batching(lines, m)
    _qty_strip(bat, "Qty", lines)
    has_var = bat["Variety"].astype(bool).any()
    cols = ["Parent SKU", "Customer SKU Name"] + (["Variety"] if has_var else []) + ["Lot", "Lot Size", "Spec", "Qty"]
    points = list(bat.groupby(["City", "Customer", "Delivery point"], sort=False))
    st.dataframe(bat if has_var else bat.drop(columns=["Variety"]), hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                "Spec": st.column_config.TextColumn(width="medium")})
    _unmapped_warning(lines, m)

    # downloads: PDF one section per delivery point, Excel, CSV
    now = config.now_ist().strftime("%d %b %Y, %I:%M %p")
    sub = [st.session_state.get("bs_desc", ""), f"{len(points)} delivery points. Generated {now} IST."]
    sections = [(f"{i}) {city} / {cust} / {store}",
                 "Indent " + ", ".join(sorted(set(", ".join(part["Indent"]).split(", ")))),
                 part[cols].reset_index(drop=True))
                for i, ((city, cust, store), part) in enumerate(points, start=1)]
    from core.reports import xlsx
    c = st.columns([1, 1, 1, 3])
    c[0].download_button("PDF", sections_pdf("Batching sheet", sub, sections, footer="MT Indent - Batching sheet"),
                         file_name=f"batching_{label}.pdf", mime="application/pdf",
                         icon=":material/picture_as_pdf:", width="stretch")
    c[1].download_button("Excel", xlsx({"Batching": bat}), file_name=f"batching_{label}.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         icon=":material/download:", width="stretch")
    c[2].download_button("CSV", bat.to_csv(index=False).encode("utf-8"), file_name=f"batching_{label}.csv",
                         mime="text/csv", icon=":material/download:", width="stretch")
    if user.is_owner:
        _publish("Batching sheet", BATCHING_TAB, bat, lines, user, "bs")


def _downloads(title: str, table: pd.DataFrame, fname: str, prefix: str, lines: pd.DataFrame) -> None:
    """CSV and PDF of the report on screen."""
    now = config.now_ist().strftime("%d %b %Y, %I:%M %p")
    sub = [st.session_state.get(f"{prefix}_desc", ""),
           f"{lines['indent_id'].nunique()} indents, {lines['store'].nunique()} stores, "
           f"{len(lines)} lines.   Generated {now} IST."]
    c = st.columns([1, 1, 4])
    c[0].download_button("CSV", table.to_csv(index=False).encode("utf-8"), file_name=f"{fname}.csv",
                         mime="text/csv", icon=":material/download:", width="stretch")
    try:
        pdf = table_pdf(title, sub, table, footer=f"MT Indent - {title}")
    except Exception as e:  # never block the CSV because of the PDF
        c[2].caption(f"PDF could not be made: {e}")
        return
    c[1].download_button("PDF", pdf, file_name=f"{fname}.pdf", mime="application/pdf",
                         icon=":material/picture_as_pdf:", width="stretch")


PRODUCTION_TAB = "Production_Sheet"
BATCHING_TAB = "Batching_Sheet"


def _publish(title: str, tab: str, table: pd.DataFrame, lines: pd.DataFrame, user: User, prefix: str) -> None:
    """Owner: overwrite a report tab in the Google Sheet with the table on
    screen (filters + time in the first rows)."""
    from core.sheets import get_backend

    c = st.columns([1.6, 4])
    if c[0].button("Write to Google Sheet", icon=":material/table_view:", width="stretch", key=f"{prefix}_pub",
                   help=f"Replaces the '{tab}' tab with this {title.lower()}"):
        now = config.now_ist().strftime("%d %b %Y, %I:%M %p")
        values = [[title],
                  [st.session_state.get(f"{prefix}_desc", "")],
                  [f"{lines['indent_id'].nunique()} indents · {len(lines)} lines · generated {now} IST "
                   f"by {user.email}"],
                  [],
                  list(table.columns)] + table.astype(object).where(table.notna(), "").values.tolist()
        try:
            with st.spinner("Writing to the Google Sheet…"):
                get_backend().replace_tab(tab, values)
        except SheetError as e:
            c[1].error(f"Not written. {e}")
            return
        c[1].success(f"'{tab}' tab updated ({len(table)} rows).")

