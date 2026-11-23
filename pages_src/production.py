"""Production reports (owner and warehouse; not sales):
1. Production sheet - total to produce and grade, all customers together.
2. Batching sheet   - the same stock split per delivery point for dispatch."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import config, indents, masters, reports
from core.auth import User
from core.pdf_report import sections_pdf, table_pdf
from core.production_calc import (batching, default_date, delivery_dates, filter_lines, make_ready,
                                  make_ready_by_customer, next_day_mask, not_in_base, production,
                                  unmapped)
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
    if not user.sees_all_cities:
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
    if not user.sees_all_cities and len(user.cities) == 1:
        city = user.cities[0]               # mapped to one city: no city filter
        c[1].markdown(f"<span class='mt-muted'>City</span><br><b>{city}</b>", unsafe_allow_html=True)
    else:
        city = c[1].selectbox("City", ["All cities"] + cities, key=f"{prefix}_city")
    scope = indents.scope_text(user)
    c[2].caption(f"All customers together · current version of every submitted or PO-frozen indent · "
                 f"{scope}. Only dates that have indents are listed.")

    lines = filter_lines(current, delivery_date=None if d == ALL_DATES else d,
                         city=None if city == "All cities" else city, allowed_ids=None)
    st.session_state[f"{prefix}_ctx"] = (current, d, None if city == "All cities" else city)
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


def _count_tiles(lines: pd.DataFrame) -> None:
    tiles = [("Indents", lines["indent_id"].nunique()), ("Delivery points", lines["store"].nunique()),
             ("Customers", lines["customer"].nunique())]
    st.markdown("<div class='mt-tiles'>" + "".join(
        f"<div class='mt-tile'><div class='lbl'>{lbl}</div><div class='val'>{val}</div><div class='sub'></div></div>"
        for lbl, val in tiles) + "</div>", unsafe_allow_html=True)


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
    st.caption("Step 1 · what to produce, **all customers together**. Variety, repacking and spec size "
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
    all_lines = lines
    d1 = next_day_mask(lines)
    if d1.any() and st.session_state.get("ps_ctx", (None, ALL_DATES))[1] != ALL_DATES:
        lines = lines[~d1]            # D+1 customers (Zepto Bangalore) get their own section below
    if lines.empty:
        st.info("Only D+1 customer orders for this date: see their section below.")
        _next_day(m)
        return
    prod = production(lines, m)
    _count_tiles(lines)
    if d1.any():
        st.caption(f"{' / '.join(config.next_day_customers())} orders are not in these tables: "
                   "see their own section at the bottom.")
    names = ["By spec size", "Make-ready list", "By customer"]
    if user.is_owner:
        names += ["Estimate (new sheet)", "Estimate (consolidated)"]
    v1, v2, v3, *v4 = st.tabs(names)
    with v1:
        show = common.numbered(prod if prod["Variety"].astype(bool).any() else prod.drop(columns=["Variety"]))
        st.dataframe(show, hide_index=True, width="stretch",
                     column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                    "Total": st.column_config.TextColumn(
                                        help="All customers clubbed for the same parent SKU, repacking, spec "
                                             "size and lot size: Kg packs in kilos, else in repacking units")})
        st.caption("**Total** = all customers clubbed per parent SKU + repacking + spec size + lot size: Kg packs "
                   "in **kilos** (700 × 1 Kg = 700 Kg), others in repacking units (10 + 20 two-piece packs = "
                   "30 Punnet). **Boxes @ count**: for piece packs, the boxes needed at each count of the spec "
                   "size (pieces ÷ count, rounded up; e.g. 440 pcs → 22C: 20, 24C: 19).")
        _downloads("Production sheet", show, f"production_{label}", "ps", lines)
    with v2:
        mr = make_ready(lines, m)
        if len(mr["City"].unique()) <= 1:
            mr = mr.drop(columns=["City"])
        mr = common.numbered(mr)
        st.dataframe(mr, hide_index=True, width="stretch")
        st.caption("For the ground team: **all customers and all sizes together**. Punnets / packs are counted as "
                   "packs; fruit going **loose** into a tray or box shows as pieces or kg (7 pcs loose, not "
                   "7 trays); a box pack counts boxes. **Fruit needed**: pieces for piece packs, kg for kg packs. "
                   "**Spec Size**: pieces at each count of the spec (New tab), e.g. 20C : 100PC | 22C : 100PC; otherwise the spec.")
        st.session_state["mr_desc"] = st.session_state.get("ps_desc", "")
        _downloads("Make-ready list", mr, f"make_ready_{label}", "mr", lines)
    with v3:
        _by_customer(all_lines, m, label)
    if v4:
        with v4[0]:
            _estimate_new(all_lines, m, label)
        with v4[1]:
            _estimate_consolidated(all_lines, m, label)
    _next_day(m)
    gaps = not_in_base(all_lines, m)
    if not gaps.empty:
        with st.expander(f"⚠️ {len(gaps)} SKU name(s) have an indent but no mapping yet (not in the New "
                         "tab, or their spec is still empty): they show as \"not in New tab\" / \"mapping not "
                         "done\" and are kept on separate lines", expanded=True):
            st.caption("Add them to the New tab (City, Customer, Parent SKU, Customer SKU Name, variety, "
                       "Spec-Repacking, Spec-Size, Spec-Origin). The app re-reads it every few minutes.")
            st.dataframe(gaps, hide_index=True, width="stretch")
    if user.is_owner:
        _publish("Production sheet", PRODUCTION_TAB, show, lines, user, "ps")


def _estimate_new(lines: pd.DataFrame, m, label: str) -> None:
    """Owners' trial (23 Nov): the estimate from the New Mapping sheet (Combination 1). Need in pcs / kg
    (firm) and a rough box range over the counts each country may be used at (customer spec ∩
    country spec). Exact boxes come on Pre-production actual once a country is picked."""
    from core import mapping_sheet, preprod
    from pages_src.preprod_actual import _opts
    if st.session_state.get("ps_ctx", (None, ALL_DATES))[1] == ALL_DATES:
        st.info("Pick one delivery date.")
        return
    try:
        data = preprod.read_all()
        data["_mapping"] = mapping_sheet.load()
    except SheetError as e:
        common.sheet_error(e)
        return
    dem = preprod.demand(lines, by_variety=True)
    if dem.empty:
        st.info("No items with a quantity for this date.")
        return
    blocks = [(h, common.numbered(df)) for h, df in preprod.estimate_rows(dem, lambda r: _opts(m, data, r))]
    st.caption("Trial, owners only. **Need** is firm (from the indents). **≈ Boxes** is a rough range over "
               "the countries and counts allowed (customer spec ∩ country spec); the exact boxes come on "
               "**Pre-production actual** once the country is picked.")
    st.download_button("Excel", lambda: reports.xlsx({f"{i + 1} {h.split(' · ')[0]}"[:31]: df
                                                      for i, (h, df) in enumerate(blocks)}),
                       file_name=f"estimate_new_{label}.xlsx", mime=reports.XLSX, icon=":material/download:",
                       key="est_xlsx", on_click="ignore")
    for head, df in blocks:
        st.markdown(f"**{head}**")
        st.dataframe(df, hide_index=True, width="stretch")


def _estimate_consolidated(lines: pd.DataFrame, m, label: str) -> None:
    """Owners' trial (24 Nov): every customer clubbed, no names. Per fruit -> variety · country · box:
    the boxes to take out of primary at each count and in total."""
    from core import mapping_sheet, preprod
    from pages_src.preprod_actual import _opts
    if st.session_state.get("ps_ctx", (None, ALL_DATES))[1] == ALL_DATES:
        st.info("Pick one delivery date.")
        return
    try:
        data = preprod.read_all()
        data["_mapping"] = mapping_sheet.load()
    except SheetError as e:
        common.sheet_error(e)
        return
    dem = preprod.demand(lines, by_variety=True)
    if dem.empty:
        st.info("No items with a quantity for this date.")
        return
    blocks = preprod.consolidated(dem, lambda r: _opts(m, data, r), m.needs_variety)
    total = sum(int(df["_n"].sum()) for _, df in blocks)
    rows = sum(len(df) for _, df in blocks)
    missing = sum(int((df["Variety · country"] == preprod.NO_VARIETY).sum()) for _, df in blocks)
    c = st.columns(3)
    c[0].metric("Boxes / trays from primary", f"≈ {total}")
    c[1].metric("Fruits · rows", f"{len(blocks)} · {rows}")
    c[2].metric("Variety not chosen", missing)
    st.caption("Trial, owners only. All customers together, no names. Each SKU uses its first country "
               "(Combination 1) and its allowed counts; its pieces are shared evenly over those counts and "
               "boxes are rounded up per count after clubbing. Exact boxes are entered on "
               "**Pre-production actual**.")
    show = [(h, common.numbered(df.drop(columns=["_n"]))) for h, df in blocks]
    st.download_button("Excel", lambda: reports.xlsx({f"{i + 1} {h.split(' · ')[0]}"[:31]: df
                                                      for i, (h, df) in enumerate(show)}),
                       file_name=f"estimate_consolidated_{label}.xlsx", mime=reports.XLSX,
                       icon=":material/download:", key="estc_xlsx", on_click="ignore")
    for head, df in show:
        st.markdown(f"**{head}**")
        st.dataframe(df, hide_index=True, width="stretch")


def _by_customer(lines: pd.DataFrame, m, label: str) -> None:
    """Production per customer (stores clubbed, cold rooms apart; all customers of the
    date, Zepto too): one row per Customer SKU Name with its own spec, a qty column
    per store and a total; PDF = one customer per page, Excel = one sheet per customer."""
    blocks = [(h, sub, common.numbered(df)) for h, sub, df in make_ready_by_customer(lines, m)]
    if not blocks:
        st.info("No indents for these filters.")
        return
    desc = st.session_state.get("ps_desc", "")
    c = st.columns([1, 1, 4])
    c[0].download_button(
        "PDF", lambda: sections_pdf("Production by customer", [desc], blocks,
                                    footer="MT Indent - production by customer", page_each=True),
        file_name=f"production_by_customer_{label}.pdf", mime="application/pdf",
        icon=":material/picture_as_pdf:", width="stretch", key="mrc_pdf", on_click="ignore")
    c[1].download_button(
        "Excel", lambda: reports.xlsx({f"{i + 1} {h.split(' · ')[0]}"[:31]: df for i, (h, _, df) in enumerate(blocks)}),
        file_name=f"production_by_customer_{label}.xlsx", mime=reports.XLSX,
        icon=":material/download:", width="stretch", key="mrc_xlsx", on_click="ignore")
    c[2].caption("PDF: one customer per page. Excel: one sheet per customer.")
    for head, sub, df in blocks:
        st.markdown(f"**{head}** <span class='mt-muted'>· {sub}</span>", unsafe_allow_html=True)
        st.dataframe(df, hide_index=True, width="stretch")


def _next_day(m) -> None:
    """D+1 customers (Zepto in Bangalore): processed the day before delivery, so
    they are kept out of the tables above and shown here: today's order first,
    then the next day's order (processed today)."""
    current, d, city = st.session_state.get("ps_ctx", (None, ALL_DATES, None))
    rules = config.next_day_customers()
    if current is None or d == ALL_DATES or not rules:
        return
    names = " / ".join(rules)
    nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    st.divider()
    st.markdown(f"### {names} orders")
    for day, title, key in ((d, "Today's order", "d0"), (nxt, "Next-day order (process today)", "d1")):
        rows = filter_lines(current, delivery_date=day, city=city, allowed_ids=None)
        rows = rows[next_day_mask(rows)] if not rows.empty else rows
        st.markdown(f"#### {names} · {title} · delivery {_fmt_date(day)}")
        if rows.empty:
            st.caption(f"No {names} indents for {_fmt_date(day)}.")
            continue
        st.caption(f"{rows['indent_id'].nunique()} indent(s) · {rows['store'].nunique()} delivery point(s).")
        t1, t2 = st.tabs(["Make-ready list", "By spec size"])
        with t1:
            mr = make_ready(rows, m)
            if len(mr["City"].unique()) <= 1:
                mr = mr.drop(columns=["City"])
            mr = common.numbered(mr)
            st.dataframe(mr, hide_index=True, width="stretch")
            _downloads(f"{names} {title} make-ready", mr, f"{key}_make_ready_{day}", f"{key}mr", rows)
        with t2:
            p = production(rows, m)
            p = common.numbered(p if p["Variety"].astype(bool).any() else p.drop(columns=["Variety"]))
            st.dataframe(p, hide_index=True, width="stretch",
                         column_config={"Qty": st.column_config.NumberColumn(format="%g")})
            _downloads(f"{names} {title} production", p, f"{key}_production_{day}", f"{key}ps", rows)


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
    bat = common.numbered(batching(lines, m))
    _qty_strip(bat, "Qty", lines)
    has_var = bat["Variety"].astype(bool).any()
    cols = ["Parent SKU", "Customer SKU Name"] + (["Variety"] if has_var else []) + ["Lot", "Lot Size", "Spec", "Qty"]
    points = list(bat.groupby(["City", "Customer", "Delivery point"], sort=False))
    st.dataframe(bat if has_var else bat.drop(columns=["Variety"]), hide_index=True, width="stretch",
                 column_config={"Qty": st.column_config.NumberColumn(format="%g"),
                                "Spec": st.column_config.TextColumn(width="medium")})
    if m.has_prod_base:
        gaps = not_in_base(lines, m)
        if not gaps.empty:
            with st.expander(f"⚠️ {len(gaps)} SKU name(s) are not in the New tab: their spec shows as "
                             "\"not in New tab\"", expanded=False):
                st.dataframe(gaps, hide_index=True, width="stretch")
    else:
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
    c[0].download_button("PDF", lambda: sections_pdf("Batching sheet", sub, sections,
                                                     footer="MT Indent - Batching sheet"), on_click="ignore",
                         file_name=f"batching_{label}.pdf", mime="application/pdf",
                         icon=":material/picture_as_pdf:", width="stretch")
    c[1].download_button("Excel", lambda: xlsx({"Batching": bat}), on_click="ignore", file_name=f"batching_{label}.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         icon=":material/download:", width="stretch")
    c[2].download_button("CSV", lambda: bat.to_csv(index=False).encode("utf-8"), on_click="ignore",
                         file_name=f"batching_{label}.csv",
                         mime="text/csv", icon=":material/download:", width="stretch")
    if user.is_owner:
        _publish("Batching sheet", BATCHING_TAB, bat, lines, user, "bs")


def _downloads(title: str, table: pd.DataFrame, fname: str, prefix: str, lines: pd.DataFrame) -> None:
    """CSV and PDF of the report on screen, built only when clicked."""
    now = config.now_ist().strftime("%d %b %Y, %I:%M %p")
    sub = [st.session_state.get(f"{prefix}_desc", ""),
           f"{lines['indent_id'].nunique()} indents, {lines['store'].nunique()} stores, "
           f"{len(lines)} lines.   Generated {now} IST."]
    c = st.columns([1, 1, 4])
    c[0].download_button("CSV", lambda: table.to_csv(index=False).encode("utf-8"), file_name=f"{fname}.csv",
                         mime="text/csv", icon=":material/download:", width="stretch", key=f"{prefix}_csv",
                         on_click="ignore")
    c[1].download_button("PDF", lambda: table_pdf(title, sub, table, footer=f"MT Indent - {title}"),
                         file_name=f"{fname}.pdf", mime="application/pdf", icon=":material/picture_as_pdf:",
                         width="stretch", key=f"{prefix}_pdf", on_click="ignore")


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


