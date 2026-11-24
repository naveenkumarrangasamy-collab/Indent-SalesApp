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

ICON = {"Enough": "🟢", "Short": "🟡", "Not started": "🔴", "Taken": "⚪"}
COL_OPT, COL_BOX = "Country · grade · count · box", "Boxes"


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


@st.fragment
def _body(user: User, day: str, city: str, rows: list[dict], data, parent_df) -> None:
    frozen, f_at, f_by = preprod.freeze_state(data[preprod.PREPROD_FREEZE], day, city, pc.CITY_GROUP)
    took = pc.taken(data[preprod.PREPROD_ACTUAL], day, city)
    hist = preprod.rounds(data[preprod.PREPROD_ACTUAL], day, city, pc.CITY_GROUP)
    nonce = st.session_state.get("pc_nonce", 0)
    base = f"pc_{nonce}_{day}_{city}"
    if frozen:
        st.success(f"🔒 {city} frozen by {f_by} at {f_at[11:16] or f_at}. No more take-outs.")
    entries, n_ok, n_bad = [], 0, 0
    last_parent = None
    for i, r in enumerate(rows):
        opts = pc.options(parent_df, r["parent"], r["variety"])
        if not opts:
            opts = [{"label": f"{r['parent']} · any", "country": "", "grade": "", "count": "", "box_kg": None}]
        mine = took.get(r["key"], {})
        labels = [o["label"] for o in opts] + [x for x in mine if x not in {o["label"] for o in opts}]
        sug, _, _ = pc.suggest(r, opts)
        total, known = pc.in_boxes(mine, opts, r["unit"], r["parent"])
        stt = pc.status(r["need"], total, known, bool(mine))
        n_ok += stt == "Enough"
        n_bad += stt in ("Short", "Not started")
        if r["parent"] != last_parent:
            st.markdown(f"#### {r['parent']}")
            last_parent = r["parent"]
        with st.container(border=True):
            c = st.columns([2.6, 1.4, 5.4, 1.4])
            title = r["variety"] or r["parent"]
            c[0].markdown(f"**{title}** · {fmt_num(round(r['need'], 1))} {_unit(r['unit'])}")
            c[0].caption(f"{r['skus']} SKU(s) · {', '.join(r['customers'])}")
            asked = " · ".join(f"{k} {fmt_num(round(v, 1))}" for k, v in
                               sorted(r["asked"].items(), key=lambda kv: (kv[0] == pc.NO_SPEC, kv[0])))
            c[0].caption(f"Asked: {asked}")
            for note in r["notes"][:3]:
                c[0].markdown(f"<span style='font-size:.78rem;color:#7A4F00'>⚠ {note}</span>",
                              unsafe_allow_html=True)
            c[1].markdown("**Suggested**")
            c[1].markdown(sug if sug != "-" else "— (no count asked)")
            if mine:
                c[2].caption("Taken so far: " + " · ".join(f"{k} × {fmt_num(v)}" for k, v in mine.items()))
            if not frozen:
                ed = c[2].data_editor(
                    pd.DataFrame({COL_OPT: [None, None], COL_BOX: [None, None]}),
                    key=f"{base}_{i}", num_rows="dynamic", hide_index=True, width="stretch",
                    column_config={COL_OPT: st.column_config.SelectboxColumn(COL_OPT, options=labels, width="medium",
                                                                              required=False),
                                   COL_BOX: st.column_config.NumberColumn(COL_BOX, min_value=0, step=1,
                                                                          format="%d", width="small")})
                by = {o["label"]: o for o in opts}
                for rec in ed.to_dict("records"):
                    n = rec.get(COL_BOX)
                    if rec.get(COL_OPT) and n and not pd.isna(n) and n > 0:
                        o = by.get(rec[COL_OPT], {})
                        entries.append({"customer_sku_name": r["key"], "parent_sku": r["parent"],
                                        "country": rec[COL_OPT], "spec": o.get("count", ""), "boxes": int(n)})
            c[3].markdown(f"{ICON.get(stt, '')} **{stt}**")
            if mine:
                c[3].caption(f"In boxes: {fmt_num(round(total, 1))} {_unit(r['unit'])}"
                             + ("" if known else " (some boxes not known)"))
                if known and stt != "Not started":
                    d = round(total - r["need"], 1)
                    c[3].caption(f"{'+' if d >= 0 else ''}{fmt_num(d)} vs need")
    st.caption(f"{n_ok} of {len(rows)} rows have enough.")
    if not frozen:
        c = st.columns([2, 2, 2, 3])
        reason = c[0].selectbox("Reason", preprod.REASONS, index=0 if hist.empty else 1, key=f"{base}_reason",
                                label_visibility="collapsed")
        if c[1].button(f"Save take-out · round {len(hist) + 1}", type="primary", icon=":material/outbox:",
                       disabled=not entries, width="stretch", key=f"{base}_save"):
            try:
                n = preprod.save_round(get_backend(), day, city, pc.CITY_GROUP, entries, reason, user.email)
            except SheetError as e:
                st.error(f"Not saved. {e}")
                return
            st.session_state["pc_nonce"] = nonce + 1
            common.flash("success", f"Take-out saved ({n} line(s)).")
            st.rerun()
        with c[2].popover("Freeze city", icon=":material/lock:", disabled=bool(entries)):
            st.markdown(f"**Freeze {city}?** No more take-outs for {day} after this.")
            if n_bad:
                st.warning(f"{n_bad} row(s) are short or not started.")
            if st.button("Yes, freeze", type="primary", key=f"{base}_frz"):
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

def actual_table(rows: list[dict], took: dict, parent_df) -> pd.DataFrame:
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
                                      if mine and known else stt)})
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
        df = actual_table(rows, took, parent_df)
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
