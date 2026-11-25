"""Pre-production actual, city level (24 Nov evening; owners only, trial) and the Creator-only
"Estimate actual" tab of the Production sheet. Logic: core/preprod_city.py."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, masters, preprod
from core import preprod_city as pc
from core.auth import User
from core.models import fmt_num
from core.sheets import SheetError, get_backend
from pages_src import common



def _ask_variety(parent: str) -> bool:
    return parent.casefold() in {p.casefold() for p in config.ask_variety_parents()}


def _unit(u: str) -> str:
    return {"pcs": "pcs", "kg": "kg", "punnets": "punnets"}.get(u, "packs")


def city_rows(lines: pd.DataFrame, day: str, m) -> list[dict]:
    """Lines of ONE date + city -> clubbed rows (need from the PO when there is one)."""
    from core.production_calc import batching, with_po
    from pages_src.production import _po_quantities
    po_qty, po_ids, extras = _po_quantities(lines)
    view = with_po(batching(lines, m), po_qty, po_ids, [e for e in extras if e["day"] == day])
    return pc.demand(view, _ask_variety)


def _load(user: User, prefix: str):
    from core import mapping_sheet
    from pages_src import production
    res = production._filtered(user, prefix)
    if res is None:
        return None
    lines = res[0]
    day = st.session_state.get(f"{prefix}_ctx", (None, production.ALL_DATES))[1]
    if day == production.ALL_DATES:
        st.info("Pick one delivery date.")
        return None
    try:
        m = masters.load_masters()
        data = preprod.read_all()
        parent_df = mapping_sheet.load()[1]
    except SheetError as e:
        common.sheet_error(e)
        return None
    return day, lines, m, data, parent_df


def _pick_city(lines: pd.DataFrame, key: str) -> str:
    cities = sorted(lines["city"].unique(), key=lambda c: (0 if "bangalore" in c.casefold() else 1, c))
    if len(cities) == 1:
        return cities[0]
    return st.pills("Pre-production for", cities, default=cities[0], key=key) or cities[0]


# ------------------------------------------------------------------ the page

def render(user: User) -> None:
    common.show_flash()
    st.markdown("### Pre-production actual")
    st.caption("Owners only (trial). Every customer of the city clubbed: one row per fruit (Apple per variety). "
               "Need = the PO qty, or the indent qty while there is no PO. Pick **country · grade · count · box** "
               "and type the boxes taken; save as often as needed, then **Freeze** the city.")
    if not user.is_owner:
        st.error("This page is for owners only for now.")
        return
    ctx = _load(user, "pc")
    if ctx is None:
        return
    day, lines, m, data, parent_df = ctx
    city = _pick_city(lines, f"pc_city_{day}")
    rows = city_rows(lines[lines["city"] == city], day, m)
    if not rows:
        st.info("No items with a quantity for this date and city.")
        return
    _body(user, day, city, rows, data, parent_df)


PC_CSS = """<style>
[class*="st-key-pcnum"] [data-testid="stNumberInputContainer"]{border:1px solid #EF9F27 !important;background:#FFFCF5 !important;border-radius:8px}
[class*="st-key-pcnum"] [data-testid="stNumberInputContainer"] *{background-color:transparent !important}
[class*="st-key-pcnum"] [data-testid="stNumberInputStepUp"],[class*="st-key-pcnum"] [data-testid="stNumberInputStepDown"]{display:none}
[class*="st-key-pcnum"] input{text-align:right}
.pc-top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.pc-ttl{font-size:1rem;font-weight:600}.pc-need{font-size:.85rem;color:#6B6F7B}
.pc-chip{font-size:.75rem;padding:.1rem .6rem;border-radius:10px}
.pc-short{background:#FAEEDA;color:#633806}.pc-ok{background:#EAF3DE;color:#27500A}.pc-no{background:#FCEBEB;color:#791F1F}
.pc-taken{background:#EEF0F4;color:#444}
.pc-info{font-size:.8rem;color:#6B6F7B;margin:.2rem 0 .5rem;line-height:1.6}.pc-sug{color:#0C447C}
.pc-note{font-size:.78rem;color:#7A4F00}
.pc-need-note{font-size:.8rem;color:#3C3489;background:#EEEDFE;border-radius:6px;padding:.1rem .5rem;display:inline-block;margin:0 .3rem .3rem 0}
.pc-done{font-size:.8rem;color:#27500A;margin:.1rem 0}
.pc-eq{font-size:.82rem;color:#6B6F7B;padding-top:.55rem}
.pc-bar{height:5px;border-radius:3px;background:#EEF0F4;overflow:hidden;margin:.35rem 0 .2rem}
.pc-fill{height:5px}
.pc-foot{display:flex;justify-content:space-between;font-size:.8rem;color:#6B6F7B}
</style>"""
CHIP = {"Enough": "pc-ok", "Short": "pc-short", "Not started": "pc-no", "Taken": "pc-taken"}


@st.fragment
def _body(user: User, day: str, city: str, rows: list[dict], data, parent_df) -> None:
    frozen, f_at, f_by = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, pc.CITY_GROUP)
    took = pc.taken(data[preprod.PREPROD_ACTUAL], day, city)
    hist = preprod.rounds(data[preprod.PREPROD_ACTUAL], day, city, pc.CITY_GROUP)
    nonce = st.session_state.get("pc_nonce", 0)
    base = f"pc_{nonce}_{day}_{city}"
    st.markdown(PC_CSS, unsafe_allow_html=True)
    if frozen:
        st.success(f"🔒 {city} frozen by {f_by} at {f_at[11:16] or f_at}. No more take-outs.")
    entries, n_ok, n_bad = [], 0, 0
    last_parent = None
    needs = pc.customer_notes(rows, preprod._read(pc.CUSTOMER_NOTES), city)
    for i, r in enumerate(rows):
        opts = pc.options(parent_df, r["parent"], r["variety"])
        if not opts:
            opts = [{"label": f"{r['parent']} · any", "country": "", "grade": "", "count": "", "box_kg": None}]
        by = {o["label"]: o for o in opts}
        mine = took.get(r["key"], {})
        word = pc.box_word(r["parent"])
        unit = _unit(r["unit"])
        if r["parent"] != last_parent:
            st.markdown(f"#### {r['parent']}")
            last_parent = r["parent"]
        with st.container(border=True):
            head = st.empty()
            sug = pc.suggest(r, opts)[0]
            asked = " · ".join(f"{k} {fmt_num(round(v, 1))}" for k, v in
                               sorted(r["asked"].items(), key=lambda kv: (kv[0] == pc.NO_SPEC, kv[0])))
            st.markdown(f"<div class='pc-info'>{', '.join(r['customers'])} · {r['skus']} SKU(s) · Asked {asked}"
                        + (f" · <span class='pc-sug'>Suggested {sug}</span>" if sug != "-" else "") + "</div>"
                        + ("<div class='pc-info' style='margin-top:-.3rem'>By customer: " + " · ".join(
                            f"{k} {fmt_num(round(v, 1))}" for k, v in sorted(r["by_customer"].items())) + "</div>"
                           if len(r["by_customer"]) > 1 else "")
                        + "".join(f"<div class='pc-need-note'>● {n}</div>" for n in needs.get(r["key"], []))
                        + "".join(f"<div class='pc-note'>⚠ {n}</div>" for n in r["notes"][:3]),
                        unsafe_allow_html=True)
            for label, n in mine.items():
                st.markdown(f"<div class='pc-done'>✓ Taken: {label} · {fmt_num(n)} {word}</div>",
                            unsafe_allow_html=True)
            typed: dict[str, float] = {}
            if not frozen:
                nk = f"{base}_{i}_rows"
                n_rows = st.session_state.get(nk, 1)
                for j in range(n_rows):
                    c = st.columns([2.4, 1, 1, 0.3], vertical_alignment="bottom")
                    first = j == 0
                    opt = c[0].selectbox("Country · grade · count · box", [None] + list(by),
                                         format_func=lambda v: "Choose…" if v is None else v,
                                         key=f"{base}_{i}_{j}_opt", label_visibility="visible" if first else "collapsed")
                    with c[1].container(key=f"pcnum_{i}_{j}_{nonce}"):
                        n = st.number_input("Trays" if word == "Tray" else "Boxes", min_value=0, step=1, value=0,
                                            key=f"{base}_{i}_{j}_n",
                                            label_visibility="visible" if first else "collapsed")
                    h = pc.holds(by.get(opt), r["unit"], r["parent"]) if opt else None
                    if opt and n:
                        c[2].markdown(f"<div class='pc-eq'>= {fmt_num(n * h)} {unit}</div>" if h
                                      else "<div class='pc-eq'>(holding not known)</div>", unsafe_allow_html=True)
                        typed[opt] = typed.get(opt, 0) + n
                        entries.append({"customer_sku_name": r["key"], "parent_sku": r["parent"], "country": opt,
                                        "spec": by[opt].get("count", ""), "boxes": int(n)})
                    if j == n_rows - 1 and n_rows > 1 and c[3].button("✕", key=f"{base}_{i}_{j}_x", type="tertiary",
                                                                       help="Remove this line"):
                        st.session_state[nk] = n_rows - 1
                        st.rerun(scope="fragment")
                if st.button("＋ Add another count", key=f"{base}_{i}_add", type="tertiary"):
                    st.session_state[nk] = n_rows + 1
                    st.rerun(scope="fragment")
            both = dict(mine)
            for k, v in typed.items():
                both[k] = both.get(k, 0) + v
            total, known = pc.in_boxes(both, opts, r["unit"], r["parent"])
            stt = pc.status(r["need"], total, known, bool(both))
            n_ok += stt == "Enough"
            n_bad += stt in ("Short", "Not started")
            gap = round(total - r["need"], 1)
            chip = {"Enough": f"Enough · +{fmt_num(gap)}" if gap > 0 else "Enough",
                    "Short": f"Short · {fmt_num(-gap)}"}.get(stt, stt)
            head.markdown(f"<div class='pc-top'><div><span class='pc-ttl'>{r['parent']}"
                          f"{' · ' + r['variety'] if r['variety'] else ''}</span> <span class='pc-need'>· need "
                          f"{fmt_num(round(r['need'], 1))} {unit}</span></div><span class='pc-chip {CHIP.get(stt, '')}'>"
                          f"{chip}</span></div>", unsafe_allow_html=True)
            if both:
                pct = min(100, int(100 * total / r["need"])) if r["need"] and known else 0
                colour = "#639922" if stt == "Enough" else "#EF9F27"
                st.markdown(f"<div class='pc-bar'><div class='pc-fill' style='width:{pct}%;background:{colour}'></div></div>"
                            f"<div class='pc-foot'><span>In {word.lower()}s {fmt_num(round(total, 1))} of "
                            f"{fmt_num(round(r['need'], 1))} {unit}</span><span>{fmt_num(sum(both.values()))} {word}"
                            "</span></div>", unsafe_allow_html=True)
    st.caption(f"{n_ok} of {len(rows)} rows have enough.")
    if not frozen:
        c = st.columns([2, 2.4, 2, 2.6])
        rnd = len(hist) + 1
        if hist.empty:
            reason = preprod.REASONS[0]                 # the first trip is always the first take-out
            c[0].markdown("<div class='pc-eq'>First take-out</div>", unsafe_allow_html=True)
        else:
            reason = c[0].selectbox("Reason", preprod.REASONS[1:], key=f"{base}_reason", label_visibility="collapsed")
        if c[1].button(f"Save take-out · round {rnd}", type="primary", icon=":material/outbox:",
                       disabled=not entries, width="stretch", key=f"{base}_save"):
            try:
                n = preprod.save_round(get_backend(), day, city, pc.CITY_GROUP, entries, reason, user.email)
            except SheetError as e:
                st.error(f"Not saved. {e}")
                return
            st.session_state["pc_nonce"] = nonce + 1
            common.flash("success", f"Take-out saved ({n} line(s)).")
            st.rerun()
        with c[2].popover(f"Freeze {city}", icon=":material/lock:", width="stretch",
                          disabled=bool(entries) or hist.empty,
                          help="After the first take-out is saved" if hist.empty else None):
            st.markdown(f"**Sure you want to freeze {city}?** No more take-outs for this date after this.")
            if n_bad:
                st.warning(f"{n_bad} row(s) are short or not started.")
            if st.button("Yes, freeze", type="primary", icon=":material/lock:", key=f"{base}_frz"):
                _freeze(day, city, True, user)
        if entries:
            c[3].caption("Boxes typed above are not saved yet.")
    else:
        with st.popover("Unfreeze", icon=":material/lock_open:"):
            if st.button("Yes, unfreeze", key=f"{base}_unf"):
                _freeze(day, city, False, user)
    st.markdown("##### Take-out history")
    if hist.empty:
        st.caption("Nothing taken out yet.")
    else:
        st.dataframe(hist, hide_index=True, width="stretch")


def _freeze(day: str, city: str, frozen: bool, user: User) -> None:
    try:
        preprod.set_frozen(get_backend(), day, city, pc.CITY_GROUP, frozen, user.email)
    except SheetError as e:
        st.error(f"Not saved. {e}")
        return
    common.flash("success", f"{city} {'frozen' if frozen else 'unfrozen'}.")
    st.rerun()


# ------------------------------------------------------------------ Production sheet tab (Creator only)

def actual_table(rows: list[dict], took: dict, parent_df, needs: dict | None = None) -> pd.DataFrame:
    out = []
    for r in rows:
        opts = pc.options(parent_df, r["parent"], r["variety"])
        mine = took.get(r["key"], {})
        total, known = pc.in_boxes(mine, opts, r["unit"], r["parent"])
        word = pc.box_word(r["parent"])
        stt = pc.status(r["need"], total, known, bool(mine))
        out.append({"Fruit": r["parent"], "Variety": r["variety"],
                    "Need": f"{fmt_num(round(r['need'], 1))} {_unit(r['unit'])}",
                    "Estimate": pc.suggest(r, opts)[0],
                    "Taken (actual)": (" | ".join(f"{k} · {fmt_num(v)}" for k, v in mine.items())
                                       + f" = {fmt_num(sum(mine.values()))} {word}") if mine else "-",
                    "Fruit in boxes": f"{fmt_num(round(total, 1))} {_unit(r['unit'])}" if mine else "-",
                    "Extra / short": (f"{'+' if total >= r['need'] else ''}{fmt_num(round(total - r['need'], 1))}"
                                      if mine and known else stt),
                    "Customer needs": "; ".join((needs or {}).get(r["key"], []))})
    return pd.DataFrame(out)


def render_estimate_actual(all_lines: pd.DataFrame, m, day: str) -> None:
    from core import mapping_sheet
    try:
        data = preprod.read_all()
        parent_df = mapping_sheet.load()[1]
    except SheetError as e:
        common.sheet_error(e)
        return
    st.caption("Creator only (trial). The same clubbing as Pre-production actual: what was actually taken out "
               "of primary against the need and the estimate.")
    for city in sorted(all_lines["city"].unique()):
        rows = city_rows(all_lines[all_lines["city"] == city], day, m)
        if not rows:
            continue
        took = pc.taken(data[preprod.PREPROD_ACTUAL], day, city)
        df = actual_table(rows, took, parent_df, pc.customer_notes(rows, preprod._read(pc.CUSTOMER_NOTES), city))
        frozen = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, pc.CITY_GROUP)[0]
        st.markdown(f"### {city}" + (" · 🔒 frozen" if frozen else ""))
        boxes = sum(sum(v.values()) for v in took.values())
        short = int((df["Extra / short"].astype(str).str.startswith("-")).sum())
        c = st.columns(4)
        c[0].metric("Boxes / trays taken", fmt_num(boxes))
        c[1].metric("Rows", len(df))
        c[2].metric("Short", short)
        c[3].metric("Not started", int((df["Taken (actual)"] == "-").sum()))
        st.dataframe(common.numbered(df), hide_index=True, width="stretch")
