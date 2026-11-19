"""Read order picture (19 Nov night, user-approved): one picture / screenshot of a
customer's order -> a table (items x one qty column per store) -> check and correct
-> create or update one indent per store (e.g. Swiggy WH1 and WH2 from one picture).

Free readers only (core.picture_table: Gemini free key, OCR.space free key, Tesseract).
Item names: the saved link (PO_Item_Map) first, then the exact name in our style, else a
new SKU (added to All Cux City + New tab, link saved, like Attach the order); a new
fruit (Parent SKU) is never added. Updating a saved indent: picture qty replaces the
saved qty; saved items not in the picture stay unless "set to 0" is ticked."""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pandas as pd
import streamlit as st

from core import config, indents, master_add, masters, order_reader, picture_table
from core.auth import User
from core.models import IndentHeader, IndentLine, fmt_num
from core.sheets import SheetError
from pages_src import common
from pages_src.delivery import TIME_SLOTS, fmt_slot

SKIP = "— skip this column"
PICK = "— pick our SKU"
K = "rp_"


def _exact(s: str) -> str:
    return " ".join(str(s or "").casefold().split())


@st.cache_data(show_spinner=False, max_entries=30, ttl=3600)
def _read(data: bytes, name: str) -> picture_table.TableRead:
    return picture_table.read(data, name)


def _all_parents(m: masters.Masters) -> list[str]:
    out = []
    for cty in m.cities():
        for c in m.customers(cty):
            out += m.parents(cty, c)
    return list(dict.fromkeys(p for p in out if p))


def _names(m: masters.Masters, city: str, customer: str) -> dict[str, str]:
    out = {}
    for p in m.parents(city, customer):
        for n in m.sku_names(city, customer, p):
            out[_exact(n)] = n
    return out


def _match(m, city: str, customer: str, name: str, links: dict) -> tuple[str, str, str]:
    """(our SKU name, Parent SKU, status) for one picture line."""
    names = _names(m, city, customer)
    linked = links.get(_exact(name))
    ours = master_add.new_sku_name(name)
    hit = (names.get(_exact(linked)) if linked else None) or names.get(_exact(ours)) or names.get(_exact(name))
    if hit:
        return hit, m.parent_of(city, customer, hit), "✓ ours"
    parent = master_add.guess_parent(name, _all_parents(m))
    if not parent:
        return "", "", "🔴 new fruit: pick our SKU"
    return ours, parent, "🆕 new SKU (added on save)"


def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Read order picture")
    st.caption("One picture of a customer's order → every store's indent. Free readers: "
               + (", ".join({"gemini": "Gemini", "ocrspace": "OCR.space", "tesseract": "built-in"}[r]
                            for r in picture_table.readers()) or "none set up"))
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "The master could not be loaded.")
        return

    # 1. where the order goes
    today = config.now_ist().date()
    days = [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    c = st.columns([1.2, 1.2, 1.4, 1])
    day = c[0].radio("Delivery day", days, index=1, horizontal=True, key=K + "day",
                     format_func=lambda d: ("Today" if d == days[0] else "Tomorrow") + f" · {d[8:]}/{d[5:7]}")
    cities = [x for x in m.cities() if user.is_owner or not user.cities or user.in_my_cities(x)]
    if not cities:
        st.info("No cities for you yet.")
        return
    city = c[1].selectbox("City", cities, key=K + "city")
    customers = m.customers(city)
    if not customers:
        st.info(f"No customers in {city} yet (Access → Add SKUs → Add a store).")
        return
    customer = c[2].selectbox("Customer", customers, key=K + "cust")
    slot = c[3].selectbox("Delivery time", TIME_SLOTS, index=0, key=K + "time", format_func=fmt_slot)
    stores = m.stores_for(city, customer)
    if not stores:
        st.info(f"{customer} has no store in {city} yet (Access → Add SKUs → Add a store).")
        return

    # 2. the picture
    up = st.file_uploader("Order picture or screenshot", type=list(order_reader.PICTURE_TYPES), key=K + "file")
    if up is None:
        st.caption("Each qty column of the picture becomes one store's indent (e.g. WH1 and WH2).")
        return
    data = up.getvalue()
    h = hashlib.md5(data).hexdigest()
    left, right = st.columns([1, 2])
    left.image(data, width="stretch")
    if not picture_table.readers():
        right.error("No picture reader is set up: add ocrspace_api_key or gemini_api_key in Secrets.")
        return
    try:
        with right, st.spinner("Reading the picture…"):
            t = _read(data, up.name)
    except picture_table.TableReadError as e:
        right.error(str(e))
        if right.button("Read again", icon=":material/refresh:", key=K + "again"):
            _read.clear()
            st.rerun()
        return
    other = order_reader.wrong_customer(customer, order_reader.whose(t.text, config.customer_aliases()))
    if other:
        right.error(f"This picture looks like a **{other}** order, not **{customer}**. Change the customer or "
                    "the picture.")
        return
    right.success(f"Read by **{t.source}**: {len(t.rows)} item(s) · {len(t.stores)} qty column(s)."
                  + (f" {t.notes}" if t.notes else ""))

    # 3. which store each qty column is
    right.markdown("**Qty columns → stores**")
    col_store = []
    cc = right.columns(max(1, len(t.stores)))
    for i, head in enumerate(t.stores):
        guess = picture_table.guess_store(head, stores) or (stores[i] if len(t.stores) == len(stores) == 1 else "")
        opts = stores + [SKIP]
        pick = cc[i].selectbox(f"Column {i + 1}: {head or 'no header'}", opts,
                               index=opts.index(guess) if guess in opts else None,
                               placeholder="Pick the store", key=f"{K}col_{h}_{i}")
        col_store.append(pick)

    # 4. the table to check
    from pages_src.indent_actions import _item_map
    links = {_exact(k): v for k, v in _item_map(customer).items()}
    base = []
    for r in t.rows:
        ours, parent, status = _match(m, city, customer, r.name, links)
        row = {"In the picture": r.name, "Code": r.code, "Our SKU": ours or None, "Status":
               status + (" · 🟡 hard to read" if r.unsure else "")}
        for i, q in enumerate(r.qtys):
            row[f"Q{i + 1}"] = int(q) if float(q).is_integer() else q
        base.append(row)
    df = pd.DataFrame(base)
    options = sorted(set(_names(m, city, customer).values()) | {b["Our SKU"] for b in base if b["Our SKU"]})
    labels = [col_store[i] if col_store[i] and col_store[i] != SKIP else f"Column {i + 1}"
              for i in range(len(t.stores))]
    qcols = {f"Q{i + 1}": st.column_config.NumberColumn(labels[i], min_value=0, step=1, format="%d")
             for i in range(len(t.stores))}
    ed = st.data_editor(df, key=f"{K}ed_{h}", hide_index=True, width="stretch", num_rows="dynamic",
                        disabled=["Status", "Code"],
                        column_config={"Our SKU": st.column_config.SelectboxColumn(options=options, width="large"),
                                       "In the picture": st.column_config.TextColumn(width="large"), **qcols})
    totals = []
    for i in range(len(t.stores)):
        got = pd.to_numeric(ed[f"Q{i + 1}"], errors="coerce").fillna(0).sum()
        want = t.totals[i] if i < len(t.totals) else None
        totals.append(f"{labels[i]}: **{fmt_num(got)}**"
                      + ("" if want is None else (" ✓" if abs(want - got) < 0.5 else f" (picture says {fmt_num(want)})")))
    st.caption(" · ".join(totals))

    # 5. what will happen per store
    lines_df = indents.read_lines()
    plan = []
    for i, store in enumerate(col_store):
        if not store or store == SKIP:
            continue
        hdr = IndentHeader(day, city, customer, store, slot)
        iid = indents.find_duplicate(lines_df, hdr) if not lines_df.empty else None
        items = [(r["Our SKU"], r[f"Q{i + 1}"], r["In the picture"], r.get("Code", ""))
                 for r in ed.to_dict("records") if r.get("Our SKU") and pd.notna(r.get(f"Q{i + 1}"))
                 and float(r[f"Q{i + 1}"] or 0) > 0]
        plan.append((store, hdr, iid, items))
    if any(not col_store[i] for i in range(len(t.stores))):
        st.warning("Pick the store for every qty column (or skip it).")
        return
    missing = [r["In the picture"] for r in ed.to_dict("records") if not r.get("Our SKU")
               and any(float(r.get(f"Q{i + 1}") or 0) > 0 for i in range(len(t.stores)))]
    if missing:
        st.error("Pick **Our SKU** for: " + ", ".join(missing) + " (a new fruit is never added by itself).")
        return
    zero = st.checkbox("Set saved items that are not in the picture to 0", value=False, key=K + "zero")
    for store, hdr, iid, items in plan:
        extra = ""
        if iid:
            cur = indents.snapshot(lines_df, iid)
            saved = {_exact(x.customer_sku_name): float(x.qty) for x in cur.lines} if cur else {}
            ch = [f"{sku} {fmt_num(saved[_exact(sku)])}→{fmt_num(q)}" for sku, q, _, _ in items
                  if _exact(sku) in saved and abs(saved[_exact(sku)] - float(q)) > 1e-9]
            add = [sku for sku, _, _, _ in items if _exact(sku) not in saved]
            extra = (f" · 🟡 {len(ch)} changed ({'; '.join(ch[:4])}{' …' if len(ch) > 4 else ''})" if ch else "") + \
                (f" · 🆕 {len(add)} added" if add else "") + ("" if ch or add else " · ✓ same as saved")
        st.markdown(f"- **{store}**: " + (f"update **{iid}**" if iid else "new indent") +
                    f" · {len(items)} item(s) · qty {fmt_num(sum(float(q) for _, q, _, _ in items))}" + extra)
    if not plan:
        return
    if st.button("Create / update indents", type="primary", icon=":material/save:", key=K + "go"):
        _save(m, user, plan, zero)


def _save(m, user: User, plan, zero: bool) -> None:
    city, customer = plan[0][1].city, plan[0][1].customer
    names = _names(m, city, customer)
    parents = _all_parents(m)
    new, links = {}, []
    for _, _, _, items in plan:
        for sku, _, text, code in items:
            if _exact(sku) not in names and _exact(sku) not in new:
                parent = master_add.guess_parent(sku, parents) or master_add.guess_parent(text, parents)
                if not parent:
                    st.error(f"'{sku}': its fruit (Parent SKU) is not in the master. Pick an existing SKU.")
                    return
                needs = m.needs_variety(parent)
                new[_exact(sku)] = {"Parent SKU": parent, "Customer SKU Name": sku,
                                    "Variety": m.variety_from_name(parent, sku) if needs else "",
                                    "Lot": master_add.lot_of(sku), "needs_variety": needs}
            if _exact(text) != _exact(sku):
                links.append({"Customer": customer, "PO Item Code": code or "", "PO Item Name": text,
                              "Customer SKU Name": sku, "Updated_At": config.now_iso()})
    from core.sheets import get_backend
    from pages_src.indent_actions import _learn
    try:
        with st.spinner("Saving…"):
            if new:
                master_add.add_items(get_backend(), city, customer, list(new.values()), user.email)
                masters.clear_cache()
                m = masters.load_masters()
            _learn(links)
            done, problems = [], []
            df = indents.read_lines(fresh=True)
            for store, hdr, iid, items in plan:
                lines = []
                for sku, q, _, _ in items:
                    parent = m.parent_of(city, customer, sku) or new.get(_exact(sku), {}).get("Parent SKU", "")
                    var = (m.default_variety(city, customer, sku) or m.variety_from_name(parent, sku)) \
                        if m.needs_variety(parent) else ""
                    lines.append(IndentLine(parent_sku=parent, customer_sku_name=sku, variety=var,
                                            lot=m.lot_for(city, customer, sku) or master_add.lot_of(sku),
                                            qty=float(q), price=1.0))
                try:
                    if iid:
                        cur = indents.snapshot(df, iid)
                        got = {_exact(x.customer_sku_name): x for x in lines}
                        merged = []
                        for x in cur.lines:
                            y = got.pop(_exact(x.customer_sku_name), None)
                            merged.append(IndentLine(**{**x.to_dict(), "qty": y.qty}) if y else
                                          (IndentLine(**{**x.to_dict(), "qty": 0.0}) if zero else x))
                        merged += list(got.values())
                        errs = indents.validate(cur.header, merged, m, zero_ok={x.customer_sku_name.casefold()
                                                                              for x in cur.lines})
                        if errs:
                            problems.append(f"{store}: " + " ".join(errs))
                            continue
                        v, _ = indents.submit_update(iid, cur.version, cur.header, merged, user.email)
                        done.append(f"{store}: {iid} updated (version {v})")
                    else:
                        errs = indents.validate(hdr, lines, m, check_date=True)
                        if errs:
                            problems.append(f"{store}: " + " ".join(errs))
                            continue
                        done.append(f"{store}: {indents.submit_new(hdr, lines, user.email)} created")
                except indents.NothingChangedError:
                    done.append(f"{store}: {iid} already the same, nothing to update")
                except SheetError as e:
                    problems.append(f"{store}: {e}")
    except SheetError as e:
        st.error(f"Not saved. {e}")
        return
    if new:
        common.flash("info", f"{len(new)} new SKU(s) added to All Cux City and the New tab (spec to fill, yellow).")
    if done:
        common.flash("success", " · ".join(done))
    if problems:
        common.flash("error", " · ".join(problems))
    st.rerun()
