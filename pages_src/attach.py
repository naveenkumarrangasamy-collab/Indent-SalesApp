"""Create / edit indent: attach the customer's order (picture, Excel or PDF).

The file is read (core.order_reader), every line is matched to our SKU names and
put into the indent's item list for checking:
- yellow ("check"): a best guess, or text read from a picture with low confidence;
- blue ("new"): not in the master yet but its Parent SKU exists -> added to All
  Cux City and the New tab (specs to fill, yellow in the sheet) on Submit;
- red: not readable, or a new Parent SKU (needs real attention): kept apart until
  someone picks the SKU and qty, or removes it. Submit waits for these.
Nothing is saved before Submit."""
from __future__ import annotations

import hashlib

import streamlit as st

from core import config, master_add, order_reader, po_reader
from core.bulk_import import ImportFileError
from core.masters import Masters
from core.models import IndentLine, fmt_num
from pages_src import state

FLAGS = "rd_flags"        # {sku name: {"flag": "check"|"new", "text": read text}}
NEW = "rd_new"            # {sku name: {"Parent SKU", "Customer SKU Name", "Variety", "Lot", "needs_variety"}}
PENDING = "rd_pending"    # [{"text", "qty", "why"}] red lines
SUMMARY = "rd_summary"    # text of the last read
DONE = "rd_done"          # hash of the file already read
FLAG_LABEL = {"check": "🟡 check", "new": "🆕 new"}


def flags() -> dict:
    return st.session_state.get(FLAGS, {})


def pending() -> list:
    return st.session_state.get(PENDING, [])


def _all_parents(m: Masters, city: str) -> list[str]:
    out = []
    for c in m.customers(city):
        out += m.parents(city, c)
    return list(dict.fromkeys(out))


def _all_names(m: Masters, city: str, customer: str) -> list[str]:
    names = []
    for p in m.parents(city, customer):
        names += m.sku_names(city, customer, p)
    return list(dict.fromkeys(names))


COMMON = {"imported", "import", "fresh", "regular", "premium", "pack", "packs", "piece", "pieces", "pcs",
          "gram", "grams", "kgs", "with", "and", "the", "from"}


def _new_word(read_name: str, sku: str) -> bool:
    """The read name has a real word that the guessed SKU lacks ('Apple Fuji' vs
    'Apple Royal Gala'): it is a different product, not a spelling of ours."""
    import re
    read = re.split(r"\s+-\s+(?=\d)", read_name.casefold(), maxsplit=1)[0]
    ours = set(re.findall(r"[a-z]+", sku.casefold()))
    return any(len(w) >= 4 and w not in COMMON and w not in ours for w in re.findall(r"[a-z]+", read))


def _apply(m: Masters, read: order_reader.OrderRead, price: float) -> None:
    from pages_src.indent_actions import _item_map
    s = st.session_state
    hdr = state.header()
    names = _all_names(m, hdr.city, hdr.customer)
    lines = po_reader.match(read.lines, names, _item_map(hdr.customer),
                            prefer=[x.customer_sku_name for x in state.lines()])
    current = {x.customer_sku_name.casefold(): x for x in state.lines()}
    order = [x.customer_sku_name for x in state.lines()]
    fl, new, red = dict(flags()), dict(s.get(NEW, {})), list(pending())
    parents = _all_parents(m, hdr.city)
    n_ok = n_check = n_new = 0
    taken: dict[str, str] = {}
    for x in lines:
        if x.qty <= 0:
            continue
        if x.sku and x.how == "guess" and not x.unsure and _new_word(x.name, x.sku):
            x.sku = ""                              # a different product -> new item
        if x.sku:
            parent = m.parent_of(hdr.city, hdr.customer, x.sku)
            sku, lot = x.sku, m.lot_for(hdr.city, hdr.customer, x.sku)
            variety = m.default_variety(hdr.city, hdr.customer, sku) if m.needs_variety(parent) else ""
            flag = "check" if (x.how == "guess" or x.unsure) else ""
        else:
            parent = master_add.guess_parent(x.name, parents)
            if not parent:
                red.append({"text": x.name, "qty": x.qty,
                            "why": "not readable / new Parent SKU" if x.unsure else "new Parent SKU or not in master"})
                continue
            sku = master_add.new_sku_name(x.name)
            lot = master_add.lot_of(sku)
            variety = m.variety_from_name(parent, sku) if m.needs_variety(parent) else ""
            flag = "new"
            new[sku] = {"Parent SKU": parent, "Customer SKU Name": sku, "Variety": variety, "Lot": lot,
                        "needs_variety": m.needs_variety(parent)}
        if sku.casefold() in taken:              # two lines of the file on one SKU: never overwrite
            red.append({"text": x.name, "qty": x.qty,
                        "why": f"same SKU as '{taken[sku.casefold()]}' ({sku}): pick the right one"})
            continue
        taken[sku.casefold()] = x.name
        old = current.get(sku.casefold())
        if old is not None:                      # already on the indent: take the qty from the file
            current[sku.casefold()] = IndentLine(**{**old.to_dict(), "qty": float(x.qty)})
        else:
            current[sku.casefold()] = IndentLine(parent_sku=parent, customer_sku_name=sku, variety=variety,
                                                 lot=lot, qty=float(x.qty), price=float(price))
            order.append(sku)
        if flag:
            fl[sku] = {"flag": flag, "text": x.name}
        n_ok += not flag
        n_check += flag == "check"
        n_new += flag == "new"
    state.set_lines([current[n.casefold()] for n in order if n.casefold() in current], structural=True)
    s[FLAGS], s[NEW], s[PENDING] = fl, new, red
    parts = [f"Read {len(lines)} line(s) from the {read.kind}: {n_ok} clear"]
    if n_check:
        parts.append(f"{n_check} to check (yellow)")
    if n_new:
        parts.append(f"{n_new} new item(s) (added to the sheet on submit)")
    bad = sum(1 for r in red)
    if bad:
        parts.append(f"{bad} not readable / new parent (red)")
    msg = ", ".join(parts) + "."
    if read.total:
        msg += (f" File total {fmt_num(read.total)}; read {fmt_num(read.read_total)}"
                + (" ✓" if abs(read.total - read.read_total) < 0.5 else " — a qty may be off or missing") + ".")
    if read.kind == "picture":
        msg += " Pictures can miss lines: compare with the picture."
    s[SUMMARY] = (msg, bool(n_check or bad or (read.total and abs(read.total - read.read_total) >= 0.5)))


def render(m: Masters) -> None:
    s = st.session_state
    with st.container(border=True, key="mt_attach"):
        c = st.columns([3, 1])
        up = c[0].file_uploader("Attach the order: Excel or PDF",
                                type=["xlsx", "xls", "pdf"] + (list(order_reader.PICTURE_TYPES)
                                                               if config.read_pictures() else []),
                                key=f"rd_file_{s.get('rd_rev', 0)}",
                                help="The items are read and added to the list below for you to check. "
                                     "Nothing is saved until you submit.")
        price = c[1].number_input("Price for read items", min_value=0.01, value=1.0, step=1.0, key="rd_price")
        if up is not None:
            data = up.getvalue()
            h = hashlib.md5(data).hexdigest()
            if s.get(DONE) != h:
                try:
                    with st.spinner("Reading the order…"):
                        read = order_reader.read(up.name, data, state.header().store)
                except ImportFileError as e:
                    st.error(str(e))
                    return
                s[DONE] = h
                if not read.lines:
                    s[SUMMARY] = ("Nothing could be read from this file. Add the items with Add item.", True)
                else:
                    _apply(m, read, float(price))
                st.rerun()
        if s.get(SUMMARY):
            msg, warn = s[SUMMARY]
            (st.warning if warn else st.success)(msg)
    _pending_box(m)


def _pending_box(m: Masters) -> None:
    red = pending()
    if not red:
        return
    hdr = state.header()
    names = _all_names(m, hdr.city, hdr.customer)
    with st.container(border=True, key="mt_pending"):
        st.error(f"**{len(red)} line(s) need you:** pick our SKU and qty, or remove the line. "
                 "A new Parent SKU is never added automatically: add it to the master by hand first.")
        for i, r in enumerate(list(red)):
            c = st.columns([2.2, 2.6, 0.8, 0.7, 0.7], vertical_alignment="bottom")
            c[0].markdown(f"<span style='color:#b42318'>{r['text']}</span><br>"
                          f"<span class='mt-muted'>{r['why']}</span>", unsafe_allow_html=True)
            sku = c[1].selectbox("Our SKU", names, index=None, key=f"rd_p_sku_{i}_{r['text']}",
                                 placeholder="Pick SKU", label_visibility="collapsed")
            qty = c[2].number_input("Qty", min_value=0, value=int(r["qty"]), step=1,
                                    key=f"rd_p_qty_{i}_{r['text']}", label_visibility="collapsed")
            if c[3].button("Add", key=f"rd_p_add_{i}", disabled=not sku or qty <= 0, width="stretch"):
                parent = m.parent_of(hdr.city, hdr.customer, sku)
                lines = [x for x in state.lines() if x.customer_sku_name.casefold() != sku.casefold()]
                lines.append(IndentLine(parent_sku=parent, customer_sku_name=sku,
                                        variety=m.default_variety(hdr.city, hdr.customer, sku)
                                        if m.needs_variety(parent) else "",
                                        lot=m.lot_for(hdr.city, hdr.customer, sku), qty=float(qty),
                                        price=float(st.session_state.get("rd_price", 1.0))))
                state.set_lines(lines, structural=True)
                red.pop(i)
                st.session_state[PENDING] = red
                st.rerun()
            if c[4].button("Remove", key=f"rd_p_rm_{i}", width="stretch"):
                red.pop(i)
                st.session_state[PENDING] = red
                st.rerun()


def new_items_to_add() -> list[dict]:
    """New-item rows still on the indent (to write to the master on submit)."""
    on = {x.customer_sku_name.casefold(): x for x in state.lines()}
    out = []
    for sku, r in st.session_state.get(NEW, {}).items():
        x = on.get(sku.casefold())
        if x is not None:
            out.append({**r, "Variety": x.variety or r.get("Variety", "")})
    return out
