"""Hourly indent tracker: how each customer's and store's indent changed hour
by hour from 8 AM to 2 PM on the delivery day (the same hours as the hourly
e-mail). Rebuilt from the saved versions in Indent_Lines, so nothing extra
has to be recorded. Click a customer or a store to see what changed."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape

import pandas as pd
import streamlit as st

from core import config, hourly, indents, reports
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
    """(label, moment) for every hour 8 AM-2 PM of the delivery day; None = still to come.
    Plus 'Now' while the day is still open."""
    first, last = hourly.hours()
    d = date.fromisoformat(day)
    now = config.now_ist()
    out = []
    for h in range(first, last + 1):
        t = datetime.combine(d, time(h, 0), tzinfo=config.IST)
        out.append((_hour_label(h), t if t <= now else None))
    last_t = datetime.combine(d, time(last, 0), tzinfo=config.IST)
    if now < last_t:
        out.append(("Now", now))
    return out


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


def _with_change(p: pd.DataFrame, hours: list[str]) -> pd.DataFrame:
    vals = p[hours].apply(pd.to_numeric, errors="coerce")
    first = vals.bfill(axis=1).iloc[:, 0] if len(hours) else 0
    last = vals.ffill(axis=1).iloc[:, -1] if len(hours) else 0
    p = p.copy()
    p["Change"] = (last - first).fillna(0)
    return p


def _style(p: pd.DataFrame, hours: list[str]):
    """Green where the qty went up since the previous hour, red where it went down,
    blue where the indent first appears. Hours without an indent show '–'."""
    num = p.copy()
    for c in hours + ["Change"]:
        if c in num.columns:
            num[c] = pd.to_numeric(num[c], errors="coerce")
    css = pd.DataFrame("", index=p.index, columns=p.columns)
    for i in p.index:
        prev = None
        for c in hours:
            v = num.at[i, c]
            if pd.notna(v) and prev is not None and pd.notna(prev) and v != prev:
                css.at[i, c] = ("background-color:#dafbe1;color:#116329;font-weight:600" if v > prev
                                else "background-color:#ffebe9;color:#a40e26;font-weight:600")
            elif pd.notna(v) and (prev is None or pd.isna(prev)) and c != hours[0]:
                css.at[i, c] = "background-color:#ddf4ff;color:#0a3069;font-weight:600"
            prev = v
        if "Change" in p.columns and pd.notna(num.at[i, "Change"]) and num.at[i, "Change"]:
            css.at[i, "Change"] = ("color:#116329;font-weight:700" if num.at[i, "Change"] > 0
                                   else "color:#a40e26;font-weight:700")
    shown = p.copy()
    for c in hours:
        shown[c] = num[c].map(lambda v: "–" if pd.isna(v) else f"{v:,.0f}")
    if "Change" in shown.columns:
        shown["Change"] = num["Change"].map(lambda v: "" if pd.isna(v) or not v else f"{v:+,.0f}")
    for c in hours + ["Change"]:
        if c in css.columns:
            css[c] = css[c].map(lambda x: (x + ";" if x else "") + "text-align:right")
    return shown.style.apply(lambda _: css, axis=None)


def render(user: User) -> None:
    common.show_flash()
    try:
        lines = indents.read_lines()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    allowed = set(indents.visible_to(indents.summary(lines), user)["indent_id"]) if not lines.empty else set()
    lines = lines[lines["indent_id"].isin(allowed)] if not lines.empty else lines

    st.markdown("### Hourly indent tracker")
    first, last = hourly.hours()
    st.caption(f"Each store's indent qty at every hour from {_hour_label(first)} to {_hour_label(last)} "
               "on the delivery day (the hours of the indent e-mail). "
               "🟩 went up · 🟥 went down · 🟦 indent placed. Click a customer or store to see what changed.")

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
