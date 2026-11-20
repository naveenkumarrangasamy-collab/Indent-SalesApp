"""Bulk indents (20 Nov, user-approved): one Excel per city, one tab per store.

Tab name = the store ('Swiggy WH1', 'Swiggy Cold Room', 'Zepto - Yalachanayakanapura').
In each tab: Customer SKU name | UOM | Qty. Per tab: a new indent, an update of that
store's indent for the day (only when a qty changed or an item is new; saved items not
in the tab stay), or 'same, skipped'. New customers / stores / SKUs are created; a new
store needs its delivery time once (then it is kept on the Delivery times page). A tab
name is matched to its store once and remembered (Store_Aliases)."""
from __future__ import annotations

import io
from datetime import timedelta

import pandas as pd
import streamlit as st

from core import bulk_import, bulk_tabs, config, indents, master_add, masters, order_reader, store_settings
from core.auth import User
from core.bulk_import import ImportFileError
from core.models import IndentHeader, IndentLine, fmt_num
from core.sheets import SheetError, get_backend
from pages_src import common
from pages_src.delivery import TIME_SLOTS, fmt_slot

K = "bk_"
NO_TIME = "— pick"


def _template() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for tab, rows in (("Swiggy WH1", [["Imported Avocado", "1 PC", 120], ["Kiwi Sungold", "2 PC", 40]]),
                          ("Swiggy WH2", [["Imported Avocado", "1 PC", 80]]),
                          ("Zepto YLK", [["Kiwi Sungold", "1 Pack", 39]])):
            pd.DataFrame(rows, columns=["Customer SKU name", "UOM", "Qty"]).to_excel(w, sheet_name=tab, index=False)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=10)
def _read(data: bytes):
    return order_reader.read_tabs(data)


def render(user: User) -> None:
    common.show_flash()
    head = st.columns([3, 1], vertical_alignment="bottom")
    head[0].markdown("### Bulk indents")
    head[0].caption("One Excel per city · one tab per store (tab name = the store) · columns Customer SKU name, "
                    "UOM, Qty. Upload again any time before the cutoff: only changed tabs are updated.")
    head[1].download_button("Template", _template, file_name="Bulk_indents_template.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            icon=":material/download:", on_click="ignore", width="stretch")
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "The master could not be loaded.")
        return
    cities = [x for x in m.cities() if user.is_owner or not user.cities or user.in_my_cities(x)]
    if not cities:
        st.info("No cities for you yet.")
        return
    today = config.now_ist().date()
    days = [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    c = st.columns([1, 1.4])
    city = c[0].selectbox("City", cities, key=K + "city")
    day = c[1].radio("Delivery day", days, index=1, horizontal=True, key=K + "day",
                     format_func=lambda d: ("Today" if d == days[0] else "Tomorrow") + f" · {d[8:]}/{d[5:7]}")
    up = st.file_uploader("Bulk indent Excel", type=["xlsx", "xls"], key=K + "file")
    if up is None:
        return
    try:
        tabs = _read(up.getvalue())
    except ImportFileError as e:
        st.error(str(e))
        return

    customers = m.customers(city)
    city_stores = [(cu, s) for cu in customers for s in m.stores_for(city, cu)]
    aliases = store_settings.aliases(None, city)
    times = store_settings.times()
    labels = [NO_TIME] + [fmt_slot(t) for t in TIME_SLOTS]
    back = {fmt_slot(t): t for t in TIME_SLOTS}

    # 1. which store each tab is
    st.markdown(f"**{len(tabs)} tab(s) → stores** · type a new customer or store to create it")
    rows = []
    for name, _ in tabs:
        cu, s, how = bulk_tabs.resolve_tab(name, city_stores, aliases, customers)
        t = times.get(store_settings._k(city, cu, s or name), "") if cu else ""
        rows.append({"Tab": name, "Customer": cu, "Store": s or name, "Time": fmt_slot(t) if t else NO_TIME,
                     "Matched": {"saved": "✓ remembered", "store": "✓ store name", "customer": "✓ customer",
                                 "close": "🟡 check"}.get(how, "🆕 new store?")})
    ed = st.data_editor(pd.DataFrame(rows), key=f"{K}tabs_{up.file_id}", hide_index=True, width="stretch",
                        disabled=["Tab", "Matched"],
                        column_config={"Time": st.column_config.SelectboxColumn("Delivery time", options=labels,
                                                                                required=True)})
    lines_df = indents.read_lines()
    links_all = _links()
    parents = bulk_tabs.all_parents(m)
    plan, blocked = [], 0
    for (name, read), r in zip(tabs, ed.to_dict("records")):
        cu, s = " ".join(str(r["Customer"] or "").split()), " ".join(str(r["Store"] or "").split())
        known_c = next((x for x in customers if bulk_tabs.key(x) == bulk_tabs.key(cu)), cu)
        known_s = next((x for c2, x in city_stores if bulk_tabs.key(c2) == bulk_tabs.key(cu)
                        and bulk_tabs.key(x) == bulk_tabs.key(s)), "")
        new_store = bool(cu and s and not known_s)
        names = bulk_tabs.names_for(m, city, known_c)
        lines = bulk_tabs.lines_for(read, names, links_all.get(bulk_tabs.key(known_c), {}), parents)
        hdr = IndentHeader(day, city, known_c, known_s or s, back.get(r["Time"], ""))
        iid = indents.find_duplicate(lines_df, hdr) if (known_s and not lines_df.empty) else None
        cur = indents.snapshot(lines_df, iid) if iid else None
        problems = []
        if not cu or not s:
            problems.append("type the customer and store")
        if not hdr.expected_time:
            problems.append("pick the delivery time")
        red = [ln.sku for ln in lines if ln.status == "red"]
        if red:
            problems.append("new fruit, not added by itself: " + ", ".join(red))
        if cur is not None and cur.status not in ("Submitted",):
            problems.append(f"{iid} is {cur.status.lower()} (PO done or locked): not changed")
        changed, added = ([], [])
        if cur is not None:
            saved = {bulk_tabs.key(x.customer_sku_name): float(x.qty) for x in cur.lines}
            changed, added = bulk_tabs.compare(saved, lines)
        action = ("blocked" if problems else "new" if cur is None else
                  "update" if (changed or added) else "same")
        blocked += action == "blocked"
        plan.append({"tab": name, "hdr": hdr, "new_store": new_store, "lines": lines, "iid": iid, "cur": cur,
                     "action": action, "problems": problems, "changed": changed, "added": added,
                     "time_changed": back.get(r["Time"], "") != times.get(store_settings._k(city, cu, s), "")})

    # 2. per tab: what will happen + its items
    for p in plan:
        h = p["hdr"]
        n_qty = sum(ln.qty for ln in p["lines"])
        title = {"new": f"🆕 new indent{' + new store' if p['new_store'] else ''}",
                 "update": f"🟡 update {p['iid']}", "same": f"✓ {p['iid']} same, skipped",
                 "blocked": "🔴 needs you"}[p["action"]]
        with st.expander(f"{p['tab']} → {h.customer} · {h.store} · {len(p['lines'])} item(s) · qty {fmt_num(n_qty)}"
                         f" · {title}", expanded=p["action"] in ("blocked", "update")):
            for msg in p["problems"]:
                st.error(msg)
            if p["changed"]:
                st.warning("Changed: " + "; ".join(p["changed"]))
            if p["added"]:
                st.info("Added: " + ", ".join(p["added"]))
            st.dataframe(pd.DataFrame([{
                "In the file": " + ".join(ln.texts), "Our SKU name": ln.sku, "Qty": fmt_num(ln.qty),
                "Status": ({"ok": "✓ ours", "new": "🆕 new SKU (added on save)", "red": "🔴 new fruit"}[ln.status]
                           + (f" · ➕ combined {' + '.join(fmt_num(q) for q in ln.qtys)}" if ln.combined else ""))}
                for ln in p["lines"]]), hide_index=True, width="stretch")

    todo = [p for p in plan if p["action"] in ("new", "update")]
    st.markdown(f"**{sum(p['action'] == 'new' for p in plan)} new · {sum(p['action'] == 'update' for p in plan)} "
                f"update · {sum(p['action'] == 'same' for p in plan)} same · {blocked} need you**")
    if not todo:
        if plan and not blocked:
            st.success("Nothing changed: every tab is the same as its saved indent.")
        return
    if st.button(f"Create / update {len(todo)} indent(s)", type="primary", icon=":material/save:", key=K + "go"):
        _save(m, user, city, plan, todo)


def _links() -> dict[str, dict[str, str]]:
    """PO_Item_Map per customer: {customer: {file name: our SKU}}."""
    return {c: {bulk_tabs.key(k): v for k, v in d.items()} for c, d in indents.po_item_links().items()}


def _save(m, user: User, city: str, plan: list[dict], todo: list[dict]) -> None:
    backend = get_backend()
    parents = bulk_tabs.all_parents(m)
    done, problems = [], []
    try:
        with st.spinner("Saving…"):
            # stores, SKUs, name links, delivery times, tab names
            stores = []
            for p in todo:
                h = p["hdr"]
                if p["new_store"] and not any(bulk_tabs.key(s["Store Name"]) == bulk_tabs.key(h.store) for s in stores):
                    stores.append({"City": city, "Customer": h.customer, "Store Name": h.store})
            if stores:
                bulk_import.add_to_master(backend, [], stores)
            by_cust: dict[str, dict] = {}
            links = []
            for p in todo:
                cu = p["hdr"].customer
                names = bulk_tabs.names_for(m, city, cu)
                for ln in p["lines"]:
                    if ln.status == "new" and bulk_tabs.key(ln.sku) not in names:
                        parent = master_add.guess_parent(ln.sku, parents) or master_add.guess_parent(ln.texts[0],
                                                                                                    parents)
                        needs = m.needs_variety(parent)
                        by_cust.setdefault(cu, {})[bulk_tabs.key(ln.sku)] = {
                            "Parent SKU": parent, "Customer SKU Name": ln.sku,
                            "Variety": m.variety_from_name(parent, ln.sku) if needs else "",
                            "Lot": master_add.lot_of(ln.sku), "needs_variety": needs}
                    for t in ln.texts:
                        if bulk_tabs.key(t) != bulk_tabs.key(ln.sku):
                            links.append({"Customer": cu, "PO Item Code": ln.code, "PO Item Name": t,
                                          "Customer SKU Name": ln.sku, "Updated_At": config.now_iso()})
            for cu, items in by_cust.items():
                master_add.add_items(backend, city, cu, list(items.values()), user.email)
            from pages_src.indent_actions import _learn
            _learn(links)
            store_settings.save_times(backend, [{"City": city, "Customer": p["hdr"].customer, "Store": p["hdr"].store,
                                                 "Time": p["hdr"].expected_time} for p in plan
                                                if p["time_changed"] and p["hdr"].expected_time], user.email)
            store_settings.save_aliases(backend, city, [(p["tab"], p["hdr"].customer, p["hdr"].store) for p in todo
                                                        if bulk_tabs.key(p["tab"]) != bulk_tabs.key(p["hdr"].store)],
                                        user.email)
            if stores or by_cust:
                masters.clear_cache()
                m = masters.load_masters()
            df = indents.read_lines(fresh=True)
            for p in todo:
                h = p["hdr"]
                new_lines = []
                for ln in p["lines"]:
                    parent = m.parent_of(city, h.customer, ln.sku)
                    var = (m.default_variety(city, h.customer, ln.sku) or m.variety_from_name(parent, ln.sku)) \
                        if m.needs_variety(parent) else ""
                    new_lines.append(IndentLine(parent_sku=parent, customer_sku_name=ln.sku, variety=var,
                                                lot=m.lot_for(city, h.customer, ln.sku) or master_add.lot_of(ln.sku),
                                                qty=float(ln.qty), price=1.0))
                try:
                    if p["action"] == "update":
                        cur = indents.snapshot(df, p["iid"])
                        got = {bulk_tabs.key(x.customer_sku_name): x for x in new_lines}
                        merged = [IndentLine(**{**x.to_dict(), "qty": got.pop(bulk_tabs.key(x.customer_sku_name)).qty})
                                  if bulk_tabs.key(x.customer_sku_name) in got else x for x in cur.lines]
                        merged += list(got.values())
                        errs = indents.validate(cur.header, merged, m,
                                                zero_ok={x.customer_sku_name.casefold() for x in cur.lines})
                        if errs:
                            problems.append(f"{p['tab']}: " + " ".join(errs))
                            continue
                        v, _ = indents.submit_update(p["iid"], cur.version, cur.header, merged, user.email)
                        done.append(f"{p['tab']}: {p['iid']} updated (v{v})")
                    else:
                        errs = indents.validate(h, new_lines, m, check_date=True)
                        if errs:
                            problems.append(f"{p['tab']}: " + " ".join(errs))
                            continue
                        done.append(f"{p['tab']}: {indents.submit_new(h, new_lines, user.email)} created")
                except indents.NothingChangedError:
                    done.append(f"{p['tab']}: same, nothing to update")
                except SheetError as e:
                    problems.append(f"{p['tab']}: {e}")
    except SheetError as e:
        st.error(f"Not saved. {e}")
        return
    if done:
        common.flash("success", " · ".join(done))
    if problems:
        common.flash("error", " · ".join(problems))
    st.rerun()
