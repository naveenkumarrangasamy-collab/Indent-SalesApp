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
DIFF = "rd_diff"          # [{"In the file", "Qty", "Our SKU name", "Change"}] what the reader did
DONE = "rd_done"          # hash of the file already read
SAME = "rd_same"          # [{"text", "new", "sku"}] new names that look like one of our SKUs (19 Nov)
FLAG_LABEL = {"check": "🟡 check", "new": "🆕 new"}


def flags() -> dict:
    return st.session_state.get(FLAGS, {})


def pending() -> list:
    return st.session_state.get(PENDING, [])


def _all_parents(m: Masters, city: str) -> list[str]:
    """Parent SKUs of this city first, then of every city (a new customer or city
    has none of its own yet, 19 Nov)."""
    out = []
    for cty in [city] + [c for c in m.cities() if c != city]:
        for c in m.customers(cty):
            out += m.parents(cty, c)
    return list(dict.fromkeys(p for p in out if p))


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


def _exact(name: str) -> str:
    return " ".join(name.casefold().split())


def _apply(m: Masters, read: order_reader.OrderRead, price: float) -> None:
    """Exact names only (18 Nov): a line maps to our SKU only when its name, in our
    style ('Kiwi Sungold - 2 PIECE' -> '2PC - Kiwi Sungold'), is exactly in the
    master (case/spaces ignored). Anything else becomes a new item (added to All Cux
    City + New tab on Submit), or red when its Parent SKU is new."""
    s = st.session_state
    hdr = state.header()
    names = {_exact(n): n for n in _all_names(m, hdr.city, hdr.customer)}
    from pages_src.indent_actions import _item_map
    saved = {_exact(k): v for k, v in _item_map(hdr.customer).items()}
    lines = read.lines
    current = {x.customer_sku_name.casefold(): x for x in state.lines()}
    order = [x.customer_sku_name for x in state.lines()]
    fl, new, red = dict(flags()), dict(s.get(NEW, {})), list(pending())
    same = list(s.get(SAME, []))
    parents = _all_parents(m, hdr.city)
    base = state.base_snapshot()
    saved_q = {x.customer_sku_name.strip().casefold(): float(x.qty) for x in base[1]} if base else None
    n_ok = n_check = n_new = 0
    taken: dict[str, str] = {}
    diff: list[dict] = []
    for x in lines:
        if x.qty <= 0:
            continue
        ours = master_add.new_sku_name(x.name)
        mapped = saved.get(_exact(x.name))         # this exact file name was mapped before (Add SKUs / PO)
        hit = (names.get(_exact(mapped)) if mapped else None) or names.get(_exact(ours)) or names.get(_exact(x.name))
        if hit:
            parent = m.parent_of(hdr.city, hdr.customer, hit)
            sku, lot = hit, m.lot_for(hdr.city, hdr.customer, hit)
            variety = m.default_variety(hdr.city, hdr.customer, sku) if m.needs_variety(parent) else ""
            flag = "check" if x.unsure else ""
        else:
            parent = master_add.guess_parent(x.name, parents)
            if not parent or x.unsure:
                why = "not readable" if x.unsure else "new Parent SKU: add it to the master first"
                red.append({"text": x.name, "qty": x.qty, "why": why})
                diff.append({"In the file": x.name, "Our SKU name": "", "Saved": None, "File": x.qty,
                             "Change": "🔴 " + why})
                continue
            sku = ours
            lot = master_add.lot_of(sku)
            variety = m.variety_from_name(parent, sku) if m.needs_variety(parent) else ""
            flag = "new"
            sug = po_reader.suggest(x.name, list(names.values())) or \
                po_reader.suggest(ours, list(names.values()))
            if sug and sug.casefold() not in {n.casefold() for n in taken} and \
                    sug.casefold() not in current:
                same.append({"text": x.name, "new": sku, "sku": sug})
            new[sku] = {"Parent SKU": parent, "Customer SKU Name": sku, "Variety": variety, "Lot": lot,
                        "needs_variety": m.needs_variety(parent)}
        if sku.casefold() in taken:              # 20 Nov: the same SKU twice in one file -> add the qty up
            prev = current[sku.casefold()]
            current[sku.casefold()] = IndentLine(**{**prev.to_dict(), "qty": float(prev.qty) + float(x.qty)})
            d = next((d for d in diff if d.get("Our SKU name", "").casefold() == sku.casefold()
                      and not d["Change"].startswith("🔴")), None)
            if d is not None:
                parts = d.setdefault("_parts", [d["File"]])
                parts.append(x.qty)
                d["File"] = sum(parts)
                d["In the file"] = f"{d['In the file']} + {x.name}" if x.name != d["In the file"] else x.name
                was = saved_q.get(sku.strip().casefold()) if saved_q is not None else None
                d["Change"] = _change(flag, was, float(d["File"]), saved_q is not None) + \
                    f" · ➕ combined {' + '.join(fmt_num(q) for q in parts)}"
            continue
        was = saved_q.get(sku.strip().casefold()) if saved_q is not None else None
        diff.append({"In the file": x.name, "Our SKU name": sku, "Saved": was, "File": x.qty,
                     "Change": _change(flag, was, float(x.qty), saved_q is not None)})
        taken[sku.casefold()] = x.name
        old = current.get(sku.casefold())
        if old is not None:                      # already on the indent: take the qty from the file
            current[sku.casefold()] = IndentLine(**{**old.to_dict(), "qty": float(x.qty)})
        else:
            current[sku.casefold()] = IndentLine(parent_sku=parent, customer_sku_name=sku, variety=variety,
                                                 lot=lot, qty=float(x.qty), price=float(price))
            order.append(sku)
        if flag:
            fl[sku] = {"flag": flag, "text": x.name, "code": x.code}
        n_ok += not flag
        n_check += flag == "check"
        n_new += flag == "new"
    state.set_lines([current[n.casefold()] for n in order if n.casefold() in current], structural=True)
    s[FLAGS], s[NEW], s[PENDING], s[SAME] = fl, new, red, same
    s[DIFF] = diff
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
    missing = [n for n in order if n.casefold() not in taken and n.strip().casefold() in state.saved_names()]
    for n in missing:
        was = (saved_q or {}).get(n.strip().casefold())
        if was:                                  # a saved item already at 0 needs nothing
            diff.append({"In the file": "", "Our SKU name": n, "Saved": was, "File": None,
                         "Change": "🔴 not in file"})
    if saved_q is not None and diff and all(d["Change"] == "✓ same" for d in diff):
        s[SUMMARY] = (f"Same as the saved indent ({len(diff)} lines, {fmt_num(sum(d['File'] for d in diff))} qty). "
                      "Nothing to update.", False)
        s["rd_same_all"] = True
        return
    s["rd_same_all"] = False
    if saved_q is not None:
        ch = sum(d["Change"][:1] in ("🟡", "🔻") and "check" not in d["Change"] for d in diff)
        gone = sum(d["Change"] == "🔴 not in file" for d in diff)
        bits = ([f"{ch} changed"] if ch else []) + ([f"{gone} saved item(s) not in the file"] if gone else [])
        if bits:
            msg += " Vs the saved indent: " + ", ".join(bits) + "."
    if read.kind == "picture":
        msg += " Pictures can miss lines: compare with the picture."
        if read.note:
            msg += f" ({read.note}.)"
    s[SUMMARY] = (msg, bool(n_check or bad or (read.total and abs(read.total - read.read_total) >= 0.5)))


def _change(flag: str, was: float | None, now: float, editing: bool) -> str:
    """The Change cell: vs the saved indent when editing, else how the name matched."""
    if flag == "new":
        return "🆕 new item"
    if editing:
        if was is None:
            return "🆕 added" + (" · 🟡 check" if flag == "check" else "")
        d = now - was
        tag = "✓ same" if not d else (f"🟡 +{fmt_num(d)}" if d > 0 else f"🔻 −{fmt_num(-d)}")
        return tag + (" · 🟡 check" if flag == "check" else "")
    return "🟡 check" if flag else "✓ exact name"


def render(m: Masters, user=None) -> None:
    s = st.session_state
    with st.container(border=True, key="mt_attach"):
        c = st.columns([3, 1])
        up = c[0].file_uploader("Attach the order: Excel, PDF or photo" if config.read_pictures()
                                else "Attach the order: Excel or PDF",
                                type=["xlsx", "xls", "pdf"] + (list(order_reader.PICTURE_TYPES)
                                                               if config.read_pictures() else []),
                                key=f"rd_file_{s.get('rd_rev', 0)}",
                                help="The items are read and added to the list below for you to check. "
                                     "Nothing is saved until you submit.")
        price = c[1].number_input("Price for read items", min_value=0.01, value=1.0, step=1.0, key="rd_price")
        if up is not None:
            data = up.getvalue()
            h = hashlib.md5(data).hexdigest()
            err = s.get("rd_err") or (None, "")
            if s.get(DONE) != h and err[0] == h:     # failed before: wait for "Read again", no re-call each rerun
                st.error(err[1])
                if not st.button("Read again", icon=":material/refresh:", key="rd_retry"):
                    return
            if s.get(DONE) != h:
                try:
                    with st.spinner("Reading the order…"):
                        read = order_reader.read(up.name, data, state.header().store)
                except ImportFileError as e:
                    s["rd_err"] = (h, str(e))
                    st.rerun()
                s.pop("rd_err", None)
                s[DONE] = h
                other = order_reader.wrong_customer(
                    state.header().customer,
                    order_reader.whose(read.text, config.customer_aliases(), read.customer_hint, up.name))
                if other:
                    s[SUMMARY] = (f"🔴 This file looks like a **{other}** order, not **{state.header().customer}**. "
                                  f"Nothing was added. Attach the {state.header().customer} order, or change the "
                                  "customer.", True)
                    s[DIFF] = []
                    st.rerun()
                if not read.lines:
                    s[SUMMARY] = ("Nothing could be read from this file. Add the items with Add item.", True)
                else:
                    _apply(m, read, float(price))
                st.rerun()
        if s.get(SUMMARY):
            msg, warn = s[SUMMARY]
            (st.warning if warn else st.success)(msg)
        _diff_box()
    _same_box(m, user)
    _pending_box(m)


ORDER = {"🔴": 0, "🔻": 1, "🟡": 2, "🆕": 3, "✓": 9}


def _diff_box() -> None:
    """What was in the file vs what we put in the item list. Editing a saved indent:
    Saved vs File per item (19 Nov), changed lines first; saved items missing from
    the file can be set to 0 or kept right here."""
    rows = st.session_state.get(DIFF) or []
    if not rows:
        return
    import pandas as pd
    editing = state.base_snapshot() is not None
    n_new = sum(r["Change"].startswith("🆕") for r in rows)
    n_red = sum(r["Change"].startswith("🔴") for r in rows)
    n_ch = sum(r["Change"][:1] in ("🟡", "🔻") for r in rows)
    label = (f"File vs {'saved indent' if editing else 'item list'} · {len(rows)} line(s)"
             + (f" · {n_ch} changed" if n_ch else "") + (f" · 🆕 {n_new} new" if n_new else "")
             + (f" · 🔴 {n_red} need you" if n_red else ""))
    with st.expander(label, expanded=bool(n_new or n_red or n_ch)):
        only = editing and st.toggle("Only changed lines", key="rd_only_changed")
        show = sorted(rows, key=lambda r: ORDER.get(r["Change"][:1], 5))
        if only:
            show = [r for r in show if not r["Change"].startswith("✓")]
        cols = ["In the file", "Our SKU name"] + (["Saved", "File"] if editing else ["File"]) + ["Change"]
        df = pd.DataFrame(show, columns=cols).rename(columns={} if editing else {"File": "Qty"})

        def color(r):
            c = r["Change"]
            bg = "#fde2e1" if c[:1] in ("🔴", "🔻") else "#e0ecff" if c.startswith("🆕") else \
                "#fff4c2" if c.startswith("🟡") else ""
            return [f"background-color:{bg}" if bg else ""] * len(r)
        fmt = {c: (lambda v: "—" if v is None or pd.isna(v) else f"{v:,.0f}") for c in ("Saved", "File", "Qty")
               if c in df.columns}
        st.dataframe(df.style.apply(color, axis=1).format(fmt), hide_index=True, width="stretch")
        for k, r in enumerate([r for r in rows if r["Change"] == "🔴 not in file"]):
            c = st.columns([4, 1, 1], vertical_alignment="center")
            c[0].markdown(f"<span style='color:#b42318'>{r['Our SKU name']}</span> · saved "
                          f"{fmt_num(r['Saved'])}, not in the file", unsafe_allow_html=True)
            if c[1].button("Set 0", key=f"rd_zero_{k}", width="stretch"):
                state.set_lines([IndentLine(**{**x.to_dict(), "qty": 0.0})
                                 if x.customer_sku_name.casefold() == r["Our SKU name"].casefold() else x
                                 for x in state.lines()], structural=True)
                r["File"], r["Change"] = 0.0, f"🔻 −{fmt_num(r['Saved'])} (set 0)"
                st.rerun()
            if c[2].button("Keep", key=f"rd_keep_{k}", width="stretch"):
                r["File"], r["Change"] = r["Saved"], "✓ same (kept)"
                st.rerun()


def _same_box(m: Masters, user) -> None:
    """New names that look like one of our SKUs ('Avocada Jumbo (PCS) - FK - Grade A'
    -> '1Pc - Avocado Jumbo - FK'). Owner: Approve = use our SKU and remember the link
    (PO_Item_Map), so both names work from now on. Others: use our SKU for this order
    only. Keep as new = add it as a new SKU (as before)."""
    rows = st.session_state.get(SAME) or []
    if not rows:
        return
    owner = bool(getattr(user, "is_owner", False))
    hdr = state.header()
    with st.container(border=True, key="mt_same"):
        st.info(f"**{len(rows)} new name(s) look like items we have.** "
                + ("Approve = same item (the name is remembered)." if owner else
                   "Use ours for this order, or keep as new. An Owner approves name links."))
        for i, r in enumerate(list(rows)):
            c = st.columns([2.4, 2.4, 1, 1], vertical_alignment="center")
            c[0].markdown(f"<span style='color:#1d4ed8'>{r['text']}</span>", unsafe_allow_html=True)
            c[1].markdown(f"Same as **{r['sku']}**?")
            if c[2].button("Approve" if owner else "Use ours", key=f"rd_same_ok_{i}", type="primary",
                           width="stretch"):
                _use_ours(m, r)
                if owner:
                    from pages_src.indent_actions import _learn
                    _learn([{"Customer": hdr.customer, "PO Item Code": "", "PO Item Name": r["text"],
                             "Customer SKU Name": r["sku"], "Updated_At": config.now_iso()}])
                rows.pop(i)
                st.session_state[SAME] = rows
                st.rerun()
            if c[3].button("Keep as new", key=f"rd_same_no_{i}", width="stretch"):
                rows.pop(i)
                st.session_state[SAME] = rows
                st.rerun()


def _use_ours(m: Masters, r: dict) -> None:
    """Put our SKU in place of the new name on the item list (same qty and price)."""
    hdr = state.header()
    sku, gone = r["sku"], r["new"].casefold()
    parent = m.parent_of(hdr.city, hdr.customer, sku)
    out = []
    for x in state.lines():
        if x.customer_sku_name.casefold() == gone:
            x = IndentLine(**{**x.to_dict(), "customer_sku_name": sku, "parent_sku": parent,
                              "lot": m.lot_for(hdr.city, hdr.customer, sku),
                              "variety": m.default_variety(hdr.city, hdr.customer, sku)
                              if m.needs_variety(parent) else ""})
        out.append(x)
    state.set_lines(out, structural=True)
    s = st.session_state
    s[NEW] = {k: v for k, v in s.get(NEW, {}).items() if k.casefold() != gone}
    s[FLAGS] = {k: v for k, v in s.get(FLAGS, {}).items() if k.casefold() != gone}
    for d in s.get(DIFF) or []:
        if d.get("In the file") == r["text"]:
            d["Our SKU name"], d["Change"] = sku, "✓ same as ours (approved)"


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
    fl = flags()
    for sku, r in st.session_state.get(NEW, {}).items():
        x = on.get(sku.casefold())
        if x is not None:
            out.append({**r, "Variety": x.variety or r.get("Variety", ""),
                        "From file": (fl.get(sku) or {}).get("text", ""),
                        "Code": (fl.get(sku) or {}).get("code", "")})
    return out


def links_to_save(customer: str, items: list[dict]) -> list[dict]:
    """New items whose name in the file differs from ours: remember the pair in
    PO_Item_Map, so the next order / PO from this customer matches by itself."""
    stamp = config.now_iso()
    return [{"Customer": customer, "PO Item Code": r.get("Code", ""), "PO Item Name": r["From file"],
             "Customer SKU Name": r["Customer SKU Name"], "Updated_At": stamp}
            for r in items if r.get("From file") and _exact(r["From file"]) != _exact(r["Customer SKU Name"])]
