"""Home: the day's operations at a glance, by delivery date, city and customer.

Status of every store the user can see:
  not placed  -> no indent yet for that delivery day
  placed      -> indent submitted, waiting for the PO   (pending)
  PO done     -> PO uploaded, indent frozen              (completed)
  deleted     -> indent cancelled
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core.auth import User
from core.schema import STATUS_SUBMITTED
from core.sheets import SheetError
from pages_src import common, indent_actions, state

STATUS_LABEL = {"none": "not placed", "open": "placed · PO pending", "done": "PO done", "cnl": "deleted"}


def _fmt_day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%a %d %b}" if word else f"{d:%a %d %b}"


def _open(indent_id: str) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is not None:
        state.open_for_edit(cur, None, created_at=indents.created_at(df, indent_id))
        common.flash("info", f"{indent_id} opened for editing. Change what you need, then press Update indent.")


@st.dialog("Replace the form?", dismissible=False)
def _confirm_open(indent_id: str) -> None:
    st.write(f"You have unsaved entries on the Indent page. Opening **{indent_id}** will replace them.")
    c = st.columns(2)
    if c[0].button("Open " + indent_id, type="primary", width="stretch"):
        st.session_state.pop("home_open", None)
        _open(indent_id)
        st.switch_page(common.PAGES["indent"])
    if c[1].button("Cancel", width="stretch"):
        st.session_state.pop("home_open", None)
        st.rerun()


def _short_id(indent_id: str) -> str:
    """IN-012 stays as is; old IND-yyyymmdd-CITY-0001 numbers show their last part."""
    return indent_id if indent_id.startswith("IN-") else indent_id[-4:]


def _status_of(row) -> str:
    return {"Frozen": "done", "Cancelled": "cnl"}.get(row, "open")


def _scope_stores(m: masters.Masters, user: User, city_filter: str | None) -> pd.DataFrame:
    """Every (city, customer, store) the user may work with."""
    rows = []
    cities = m.cities()
    if not user.is_owner and user.cities:
        cities = [c for c in cities if user.in_my_cities(c)]
    for city in cities:
        if city_filter and city != city_filter:
            continue
        for cust in m.customers(city):
            for store in m.stores_for(city, cust):
                if user.in_my_stores(store):
                    rows.append({"city": city, "customer": cust, "store": store})
    return pd.DataFrame(rows, columns=["city", "customer", "store"])


def _tile(label: str, value, sub: str = "", tone: str = "") -> str:
    return (f"<div class='mt-tile {tone}'><div class='lbl'>{escape(label)}</div>"
            f"<div class='val'>{value}</div><div class='sub'>{escape(sub)}</div></div>")


def _act_card(r, ind) -> None:
    ok = bool(r.can_edit)
    frozen = r.status in ("Frozen", "Cancelled")
    why = ("Deleted" if r.status == "Cancelled" else "Frozen with a PO") if frozen \
        else f"Editing closed at {indents.deadline_text(r.delivery_date)}"
    with st.container(border=True, key=f"mtcard_hm_{r.indent_id}"):
        st.markdown(
            f"<div class='mt-card-head'><b>{escape(r.customer)}</b> · {escape(r.store)} "
            f"{common.badge(r.status)}</div>"
            f"<div class='mt-muted'><span class='mt-id'>{escape(r.indent_id)}</span> · {int(r.lines)} items · "
            f"₹ {r.total_amount:,.0f}</div>", unsafe_allow_html=True)
        c = st.columns(2)
        editing = ind["mode"] == "edit" and ind["indent_id"] == r.indent_id
        if c[0].button("Edit", icon=":material/edit:", key=f"hm_e_{r.indent_id}",
                       disabled=not ok, width="stretch", help=None if ok else why):
            if state.has_unsaved_work() and not editing:
                st.session_state["home_open"] = r.indent_id
                st.rerun()
            if not editing:
                _open(r.indent_id)
            st.switch_page(common.PAGES["indent"])
        if c[1].button("Upload PO" if not frozen else "PO done", icon=":material/upload_file:",
                       key=f"hm_p_{r.indent_id}", disabled=frozen, width="stretch",
                       type="primary" if not frozen else "secondary",
                       help="Upload the customer's PO (PDF) and freeze this indent"):
            indent_actions.ask("po", r.indent_id)


def render(user: User) -> None:
    common.show_flash()
    try:
        df = indents.read_lines()
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "Data could not be loaded.")
        return

    summ = indents.visible_to(indents.summary(df), user)
    today = config.now_ist().date()

    head = st.columns([3, 1.2, 1.2], vertical_alignment="bottom")
    head[0].markdown("### Daily operations")
    head[0].caption("What is placed, what is waiting for a PO and which stores have no indent yet. "
                    f"Showing {indents.scope_text(user)}.")
    if head[1].button("Create indent", icon=":material/add_circle:", type="primary", width="stretch"):
        st.switch_page(common.PAGES["indent"])
    waiting = int((summ["status"] == STATUS_SUBMITTED).sum()) if not summ.empty else 0
    if head[2].button(f"Upload PO · {waiting} waiting" if waiting else "Upload PO",
                      icon=":material/upload_file:", type="primary", width="stretch", key="home_po_btn",
                      help="See every indent and upload the customer's PO"):
        st.switch_page(common.PAGES["po"])

    # ---- filters: delivery day + city
    days = [(today + timedelta(days=k)).isoformat() for k in (0, 1)]
    k = "home_day"
    if k not in st.session_state or st.session_state[k] not in days:
        st.session_state[k] = today.isoformat()
    day = st.segmented_control("Delivery day", days, key=k, format_func=_fmt_day, required=True) \
        or today.isoformat()

    cities = sorted(set(m.cities()))
    if not user.is_owner and user.cities:
        cities = [c for c in cities if user.in_my_cities(c)]
    city = None
    if len(cities) > 1:
        city = st.pills("City", ["All cities"] + cities, default="All cities", key="home_city")
        city = None if city in (None, "All cities") else city

    # ---- data for the day
    day_rows = summ[summ["delivery_date"].astype(str) == day] if not summ.empty else summ
    if city and not day_rows.empty:
        day_rows = day_rows[day_rows["city"] == city]
    scope = _scope_stores(m, user, city)
    norm = lambda v: " ".join(str(v).split()).casefold()  # noqa: E731
    placed = {}
    for r in day_rows.itertuples():
        key = (norm(r.city), norm(r.customer), norm(r.store))
        # keep the live indent over a deleted one for the same store
        if key not in placed or placed[key].status == "Cancelled":
            placed[key] = r
    board = []
    for r in scope.itertuples():
        hit = placed.get((norm(r.city), norm(r.customer), norm(r.store)))
        board.append({"city": r.city, "customer": r.customer, "store": r.store,
                      "state": _status_of(hit.status) if hit is not None else "none",
                      "indent_id": hit.indent_id if hit is not None else "",
                      "lines": int(hit.lines) if hit is not None else 0,
                      "amount": float(hit.total_amount) if hit is not None else 0.0})
    # indents for stores that are not in the store list any more still count
    known = {(norm(b["city"]), norm(b["customer"]), norm(b["store"])) for b in board}
    for key, r in placed.items():
        if key not in known:
            board.append({"city": r.city, "customer": r.customer, "store": r.store,
                          "state": _status_of(r.status), "indent_id": r.indent_id,
                          "lines": int(r.lines), "amount": float(r.total_amount)})
    board = pd.DataFrame(board, columns=["city", "customer", "store", "state", "indent_id", "lines", "amount"])

    live = day_rows[day_rows["status"] != "Cancelled"] if not day_rows.empty else day_rows
    cur = indents.current_rows(df)
    cur = cur[cur["indent_id"].isin(set(live["indent_id"]))] if not live.empty else cur.iloc[0:0]
    n_total = len(board[board["state"] != "cnl"]) if not board.empty else 0
    n = {s: int((board["state"] == s).sum()) if not board.empty else 0 for s in ("none", "open", "done", "cnl")}
    placed_n = n["open"] + n["done"]
    qty = int(cur["qty"].sum()) if not cur.empty else 0

    tiles = [
        _tile("Stores placed", f"{placed_n}/{n_total}" if n_total else placed_n,
              f"{(placed_n / n_total * 100):.0f}% of stores" if n_total else "", "info"),
        _tile("PO received", n["done"], "completed", "good"),
        _tile("Waiting for PO", n["open"], "pending", "warn" if n["open"] else ""),
        _tile("Not placed yet", n["none"], "stores without an indent", "bad" if n["none"] else ""),
        _tile("Qty (lots)", f"{qty:,}", f"{len(cur)} lines"),
    ]
    st.markdown("<div class='mt-tiles'>" + "".join(tiles) + "</div>", unsafe_allow_html=True)

    if n_total:
        seg = [("done", "#2da44e"), ("open", "#e3b341"), ("none", "#d0d7de")]
        bar = "".join(f"<span style='width:{n[s] / n_total * 100:.2f}%;background:{c}'></span>" for s, c in seg)
        st.markdown(f"<div class='mt-bar'>{bar}</div>"
                    f"<div class='mt-muted' style='margin:.3rem 0 1rem'>"
                    f"<span style='color:#2da44e'>■</span> PO done {n['done']} &nbsp; "
                    f"<span style='color:#e3b341'>■</span> waiting for PO {n['open']} &nbsp; "
                    f"<span style='color:#8c959f'>■</span> not placed {n['none']}"
                    + (f" &nbsp; · deleted {n['cnl']}" if n["cnl"] else "") + "</div>",
                    unsafe_allow_html=True)

    if board.empty:
        st.info("No stores or indents for this day and city.")
        return

    t_board, t_table, t_list = st.tabs(["Status board", "City × Customer", "Indents to act on"])

    with t_board:
        order = {"none": 0, "open": 1, "done": 2, "cnl": 3}
        groups = list(board.groupby(["city", "customer"], sort=True))
        cols = []
        for i, ((c_city, cust), part) in enumerate(groups):
            if i % 2 == 0:
                cols = st.columns(2)
            part = part.sort_values(by="state", key=lambda s: s.map(order))
            done = int((part["state"] == "done").sum())
            open_ = int((part["state"] == "open").sum())
            total = int((part["state"] != "cnl").sum())
            chips = "".join(
                f"<span class='mt-chip {r.state}' title='{escape(STATUS_LABEL[r.state])}'>"
                f"{escape(r.store)}{' · ' + escape(_short_id(r.indent_id)) if r.indent_id else ''}</span>"
                for r in part.itertuples())
            cols[i % 2].markdown(
                f"<div class='mt-cust'><h4>{escape(cust)} <span class='mt-muted'>· {escape(c_city)}</span></h4>"
                f"<div class='mt-muted' style='margin-bottom:.35rem'>{open_ + done}/{total} placed · "
                f"{done} PO done · {open_} waiting · {total - open_ - done} not placed</div>{chips}</div>",
                unsafe_allow_html=True)
        st.markdown("<span class='mt-chip none'>not placed</span><span class='mt-chip open'>placed · PO pending"
                    "</span><span class='mt-chip done'>PO done</span><span class='mt-chip cnl'>deleted</span>",
                    unsafe_allow_html=True)

    with t_table:
        g = (board.assign(placed=board["state"].isin(["open", "done"]),
                          done=board["state"] == "done", open=board["state"] == "open",
                          none=board["state"] == "none", active=board["state"] != "cnl")
                  .groupby(["city", "customer"])
                  .agg(Stores=("active", "sum"), Placed=("placed", "sum"), PO_done=("done", "sum"),
                       Waiting_PO=("open", "sum"), Not_placed=("none", "sum"),
                       Items=("lines", "sum"), Amount=("amount", "sum"))
                  .reset_index().rename(columns={"city": "City", "customer": "Customer",
                                                 "PO_done": "PO done", "Waiting_PO": "Waiting for PO",
                                                 "Not_placed": "Not placed"}))
        if not cur.empty:
            q = cur.groupby(["city", "customer"])["qty"].sum().rename("Qty").reset_index() \
                   .rename(columns={"city": "City", "customer": "Customer"})
            g = g.merge(q, on=["City", "Customer"], how="left")
        else:
            g["Qty"] = 0
        g["Qty"] = g["Qty"].fillna(0).astype(int)
        g["Done %"] = (g["PO done"] / g["Stores"].where(g["Stores"] > 0) * 100).fillna(0).round(0)
        st.dataframe(g[["City", "Customer", "Stores", "Placed", "PO done", "Waiting for PO", "Not placed",
                        "Items", "Qty", "Amount", "Done %"]],
                     hide_index=True, width="stretch",
                     column_config={"Amount": st.column_config.NumberColumn(format="₹ %.0f"),
                                    "Done %": st.column_config.ProgressColumn(min_value=0, max_value=100,
                                                                              format="%d%%")})

    with t_list:
        rows = indents.open_first(day_rows, then=["customer", "store"], ascending=[True, True]) \
            if not day_rows.empty else day_rows
        if rows is None or rows.empty:
            st.caption("No indents for this day yet.")
        else:
            ind = state.get()
            recs = list(rows.itertuples())
            for i in range(0, len(recs), 2):
                pair = st.columns(2)
                for col, r in zip(pair, recs[i:i + 2]):
                    with col:
                        _act_card(r, ind)

    if st.session_state.get("home_open"):
        _confirm_open(st.session_state["home_open"])
    else:
        indent_actions.show_dialog(user)
