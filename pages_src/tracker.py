"""Hourly indent tracker: how each customer's and store's indent changed every
30 minutes (19 Nov; was hourly) from 8 AM to 2 PM on the delivery day (the same hours as the hourly
e-mail). Rebuilt from the saved versions in Indent_Lines, so nothing extra
has to be recorded. Click a customer or a store to see what changed."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape

import pandas as pd
import streamlit as st

from core import config, hourly, indents, reports, tracking
from core.auth import User
from core.sheets import SheetError
from pages_src import common

ALL_C = "All cities"
ALL_K = "All customers"


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%a %d %b}" if word else f"{d:%a %d %b}"


def _hour_label(h: int) -> str:
    return f"{(h - 1) % 12 + 1} {'AM' if h < 12 else 'PM'}"


def _points(day: str) -> list[tuple[str, datetime | None]]:
    """Every 30 min from 8 AM to 2 PM of the delivery day (+ Now)."""
    return tracking.points(day)


def _states(lines: pd.DataFrame, day: str, points) -> dict[str, pd.DataFrame | None]:
    out = {}
    for label, t in points:
        if t is None:
            out[label] = None
            continue
        st_ = reports.state_at(lines, t)
        out[label] = st_[st_["delivery_date"].astype(str) == day] if st_ is not None and not st_.empty else st_
    return out


def _pivot(states: dict, keys: list[str]) -> pd.DataFrame:
    """Rows = keys (e.g. customer, store), columns = hours, values = total qty."""
    frames = []
    for label, df in states.items():
        if df is None or df.empty:
            continue
        g = df.groupby(keys)["qty"].sum().rename(label)
        frames.append(g)
    if not frames:
        return pd.DataFrame(columns=keys + list(states))
    p = pd.concat(frames, axis=1)
    for label in states:
        if label not in p.columns:
            p[label] = pd.NA
    p = p[list(states)].reset_index()
    return p.sort_values(keys, key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)


CHANGED = "background-color:#fff1c2;color:#7d4e00;font-weight:700"
SAME = "background-color:#dafbe1;color:#116329"


def _with_change(p: pd.DataFrame, hours: list[str]) -> pd.DataFrame:
    """Adds Status (changed / no change since the first hour it appeared) and
    Change (last qty minus first qty)."""
    vals = p[hours].apply(pd.to_numeric, errors="coerce") if len(hours) else pd.DataFrame(index=p.index)
    status, change = [], []
    for i in p.index:
        seq = [v for v in vals.loc[i].tolist()] if len(hours) else []
        n, prev, first, last = 0, None, None, None
        for v in seq:
            if pd.notna(v):
                if first is None:
                    first = v
                elif prev is None or pd.isna(prev) or v != prev:
                    n += 1
                last = v
            elif prev is not None and pd.notna(prev):
                n += 1                       # indent went away
            prev = v
        status.append("No change" if n == 0 else f"Changed ×{n}" if n > 1 else "Changed")
        change.append(0 if first is None or last is None else last - first)
    p = p.copy()
    at = list(p.columns).index(hours[0]) if hours and hours[0] in p.columns else len(p.columns)
    p.insert(at, "Status", status)        # right after the customer / store names
    p["Change"] = change
    return p


def _style(p: pd.DataFrame, hours: list[str]):
    """Amber with ▲/▼ where the qty changed since the previous hour, green
    where it stayed the same. Hours without an indent show '–'."""
    num = p.copy()
    for c in hours + ["Change"]:
        if c in num.columns:
            num[c] = pd.to_numeric(num[c], errors="coerce")
    css = pd.DataFrame("", index=p.index, columns=p.columns)
    shown = p.copy()
    for c in hours:
        shown[c] = shown[c].astype(object)
    for i in p.index:
        prev, seen = None, False
        for c in hours:
            v = num.at[i, c]
            if pd.isna(v):
                shown.at[i, c] = "–"
            else:
                txt = f"{v:,.0f}"
                if not seen:
                    css.at[i, c] = SAME
                elif prev is None or pd.isna(prev) or v != prev:
                    arrow = "▲" if prev is None or pd.isna(prev) or v > prev else "▼"
                    css.at[i, c] = CHANGED
                    was = "0" if prev is None or pd.isna(prev) else f"{prev:,.0f}"
                    txt = f"{was} → {txt} {arrow}"
                else:
                    css.at[i, c] = SAME
                shown.at[i, c] = txt
                seen = True
            prev = v
        if "Status" in p.columns:
            css.at[i, "Status"] = (SAME if p.at[i, "Status"] == "No change" else CHANGED) + ";font-weight:600"
        if "Change" in p.columns:
            ch = num.at[i, "Change"]
            css.at[i, "Change"] = "" if pd.isna(ch) or not ch else (
                "color:#116329;font-weight:700" if ch > 0 else "color:#a40e26;font-weight:700")
    if "Change" in shown.columns:
        shown["Change"] = num["Change"].map(lambda v: "" if pd.isna(v) or not v else f"{v:+,.0f}")
    for c in hours + ["Change"]:
        if c in css.columns:
            css[c] = css[c].map(lambda x: (x + ";" if x else "") + "text-align:right")
    return shown.style.apply(lambda _: css, axis=None)


def render(user: User) -> None:
    common.show_flash()
    if not (user.is_owner or getattr(user, "is_warehouse", False)):
        st.error("The hourly tracker is for the owner and the warehouse team.")
        return
    try:
        lines = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    allowed = set(indents.visible_to(indents.summary(lines), user)["indent_id"]) if not lines.empty else set()
    lines = lines[lines["indent_id"].isin(allowed)] if not lines.empty else lines

    st.markdown("### Hourly indent tracker")
    first, last = hourly.hours()
    st.caption(f"Each store's indent qty every 30 minutes from {_hour_label(first)} to {_hour_label(last)} "
               "on the delivery day. 🟨 previous → new qty where it changed · 🟩 no change. "
               "**Indent vs PO** compares each item with its PO(s).")

    # ---- the three filters
    today = config.now_ist().date()
    days = [(today + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    if not lines.empty:
        recent = {d for d in lines["delivery_date"].astype(str)
                  if d and (today - date.fromisoformat(d)).days <= 7}
        days = sorted(set(days) | recent)
    if st.session_state.get("tk_day") not in days:
        st.session_state["tk_day"] = today.isoformat()
    day = st.segmented_control("Delivery date", days, key="tk_day", format_func=_fmt_day,
                               required=True) or today.isoformat()
    on_day = lines[lines["delivery_date"].astype(str) == day] if not lines.empty else lines
    cities = sorted(set(on_day["city"].astype(str))) if not on_day.empty else []
    c = st.columns(2)
    city = c[0].pills("City", [ALL_C] + cities, default=ALL_C, key="tk_city") if len(cities) > 1 else None
    if city and city != ALL_C:
        on_day = on_day[on_day["city"] == city]
    custs = sorted(set(on_day["customer"].astype(str))) if not on_day.empty else []
    cust = (c[1] if len(cities) > 1 else c[0]).pills("Customer", [ALL_K] + custs, default=ALL_K, key="tk_cust")
    if cust and cust != ALL_K:
        on_day = on_day[on_day["customer"] == cust]

    if on_day.empty:
        st.info("No indents for this delivery date with these filters.")
        return
    ids = set(on_day["indent_id"])
    scoped = lines[lines["indent_id"].isin(ids)]
    points = _points(day)
    hours = [lbl for lbl, _ in points]
    states = _states(scoped, day, points)
    if all(v is None for v in states.values()):
        st.info(f"The 8 AM snapshot for {_fmt_day(day)} is not there yet: tracking starts at "
                f"{_hour_label(first)} on the delivery day.")

    t1, t2 = st.tabs(["Indent changes", "Indent vs PO"])
    with t2:
        _po_tracker(lines, ids)
    with t1:
        _changes(scoped, day, points, hours, states, city, cust)


def _changes(scoped, day, points, hours, states, city, cust) -> None:
    # ---- only the items that changed (19 Nov: easiest to read)
    st.markdown("**Item changes** (only SKUs whose qty changed)")
    pi = _with_change(_pivot(states, ["customer", "store", "customer_sku_name"]), hours).rename(
        columns={"customer": "Customer", "store": "Store", "customer_sku_name": "Customer SKU Name"})
    pi = pi[pi["Status"] != "No change"].reset_index(drop=True) if not pi.empty else pi
    if pi.empty:
        st.caption("No item changed in these half hours.")
    else:
        st.dataframe(_style(pi, hours), hide_index=True, width="stretch")
    # ---- by customer
    st.markdown("**By customer**")
    pc = _with_change(_pivot(states, ["customer"]), hours).rename(columns={"customer": "Customer"})
    rev = st.session_state.get("tk_rev", 0)   # bumped when the detail closes, to clear the selection
    sel_c = st.dataframe(_style(pc, hours), hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"tk_tc_{day}_{city}_{cust}_{rev}")
    # ---- by store
    st.markdown("**By store**")
    ps = _with_change(_pivot(states, ["customer", "store"]), hours).rename(
        columns={"customer": "Customer", "store": "Store"})
    sel_s = st.dataframe(_style(ps, hours), hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"tk_ts_{day}_{city}_{cust}_{rev}")
    st.caption("Tip: tap a row to open its hour-by-hour detail.")

    rc = sel_c.selection.rows if sel_c and sel_c.selection else []
    rs = sel_s.selection.rows if sel_s and sel_s.selection else []
    if rs:
        r = ps.iloc[rs[0]]
        _detail(scoped, day, points, r["Customer"], r["Store"])
    elif rc:
        _detail(scoped, day, points, pc.iloc[rc[0]]["Customer"], None)


DIFF = "background-color:#ffe0e0;color:#a40e26;font-weight:700"
PENDING = "background-color:#f1f3f5;color:#555"


def _po_tracker(lines: pd.DataFrame, ids: set) -> None:
    """Indent vs PO per store and item: the indent qty, the PO qty (all POs of
    the indent together) and the difference."""
    try:
        po = indents.read_po_freeze()
    except SheetError as e:
        common.sheet_error(e)
        return
    df = tracking.po_rows(lines, po, ids)
    if df.empty:
        st.info("No indents with these filters.")
        return
    bad = df["Status"].isin(["Differs", "Not on PO", "Not on indent"])
    n_st = df[bad][["Customer", "Store"]].drop_duplicates().shape[0]
    show_all = st.toggle("Show matching items too", key="tk_po_all")
    st.caption(f"**{int(bad.sum())}** item(s) differ in **{n_st}** store(s) · "
               f"{int((df['Status'] == 'No PO yet').sum())} item(s) still without a PO. "
               "Multi-PO customers are compared after End of POs.")
    view = df if show_all else df[bad | ~df["Status"].isin(["Match"])]
    if view.empty:
        st.success("Every PO matches its indent.")
        return

    def _row(r):
        css = DIFF if r["Status"] in ("Differs", "Not on PO", "Not on indent") else (
            SAME if r["Status"] == "Match" else PENDING)
        return [css if c in ("Difference", "Status", "PO qty") else "" for c in r.index]
    st.dataframe(view.style.apply(_row, axis=1), hide_index=True, width="stretch")


def _closed() -> None:
    st.session_state["tk_rev"] = st.session_state.get("tk_rev", 0) + 1


@st.dialog("What changed", width="large", on_dismiss=_closed)
def _detail(lines: pd.DataFrame, day: str, points, customer: str, store: str | None) -> None:
    part = lines[lines["customer"] == customer]
    if store is not None:
        part = part[part["store"] == store]
    st.markdown(f"#### {escape(customer)}{' · ' + escape(store) if store else ' · all stores'}")
    st.caption(f"Delivery {_fmt_day(day)}")
    avail = [lbl for lbl, t in points if t is not None]
    if not avail:
        st.info("Tracking starts at 8 AM on the delivery day.")
        upto, upto_t = "Now", config.now_ist()
    else:
        upto = st.segmented_control("Changes from 8 AM up to", avail, default=avail[-1],
                                    key=f"tk_upto_{customer}_{store}", required=True) or avail[-1]
        upto_t = dict(points)[upto]
    shown = [(lbl, t) for lbl, t in points if t is not None and t <= upto_t] or [("Now", upto_t)]
    hours = [lbl for lbl, _ in shown]
    states = _states(part, day, shown)
    keys = ["customer_sku_name"] if store else ["store", "customer_sku_name"]
    p = _with_change(_pivot(states, keys), hours).rename(
        columns={"customer_sku_name": "Customer SKU Name", "store": "Store"})
    st.markdown("**Qty per item at each hour**")
    if p.empty:
        st.caption("No indent yet at these hours.")
    else:
        st.dataframe(_style(p, hours), hide_index=True, width="stretch")

    # the edits behind it, from Indent_Lines versions (who, when, what)
    day8 = pd.Timestamp(datetime.combine(date.fromisoformat(day), time(hourly.hours()[0]), tzinfo=config.IST))
    ts = pd.to_datetime(part["submitted_at"], errors="coerce", utc=True)
    window = part[(ts <= pd.Timestamp(upto_t).tz_convert("UTC"))]
    events = (window.groupby(["indent_id", "version"])
                    .agg(at=("submitted_at", "first"), by=("submitted_by", "first"),
                         status=("status", "first"), note=("change_note", "first"),
                         store=("store", "first"), qty=("qty", "sum"))
                    .reset_index()) if not window.empty else pd.DataFrame()
    st.markdown(f"**Saves up to {upto}**")
    if events.empty:
        st.caption("Nothing saved yet.")
        return
    events["when"] = pd.to_datetime(events["at"], errors="coerce", utc=True).dt.tz_convert(config.IST)
    events = events.sort_values("when", ascending=False)
    rows = []
    for e in events.itertuples():
        before_8 = e.when < day8
        rows.append({"When": e.when.strftime("%d %b %I:%M %p"), "Store": e.store, "Indent": e.indent_id,
                     "Version": int(e.version), "By": e.by, "Total qty": int(e.qty) if float(e.qty).is_integer() else e.qty,
                     "What": (e.note or e.status) + (" (before 8 AM)" if before_8 else "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"What": st.column_config.TextColumn(width="large")})
