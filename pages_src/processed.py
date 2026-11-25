"""Processed page (25 Nov, trial): MT / GT / dump out of each lot on a table.

Built for phones: one thing at a time (Fruit -> Table -> Lot -> Cux lot), empty number boxes
(no zeros to delete), boxes that do not fit the fruit are hidden, live result under the inputs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, indents, masters
from core import prod_actual as pa
from core import processed as pr
from core.auth import User
from core.sheets import SheetError, get_backend
from pages_src import common

CSS = """<style>
.st-key-pr_card {border:1px solid #DDE3EA; border-radius:10px; padding:12px 14px 4px 14px; background:#FBFCFD;}
.st-key-pr_card label p {font-size:0.8rem; color:#4A5562; font-weight:600;}
.pr-info {font-size:0.82rem; color:#4A5562; background:#F1F4F7; border-radius:8px; padding:6px 10px; margin:2px 0 8px 0;}
.pr-grp {font-size:0.85rem; font-weight:700; margin:6px 0 -6px 0;}
.pr-res {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; margin:6px 0 10px 0;}
.pr-res div {border-radius:8px; padding:6px 4px; text-align:center; background:#F1F4F7; font-size:0.75rem; color:#4A5562;}
.pr-res b {display:block; font-size:1.05rem; color:#1F2933;}
.pr-kg {font-size:0.78rem; color:#4A5562; margin-top:-2px;}
.pr-var {display:inline-block; background:#EDE7FB; color:#4B2A9E; font-weight:700; border-radius:999px;
         padding:1px 10px; margin:0 2px; font-size:0.85rem;}
@media (max-width: 640px) { .pr-res {grid-template-columns:repeat(2,minmax(0,1fr));} }
</style>"""


def _num(label: str, key: str, step: float = 1.0):
    return st.number_input(label, min_value=0.0, step=step, value=None, key=key, placeholder="0", format="%g")


def _pending() -> list[dict]:
    return st.session_state.setdefault("pr_rows", [])


def _eff_colour(e) -> tuple[str, str]:
    if e is None:
        return "#F1F4F7", "#1F2933"
    if e >= 0.9:
        return "#E6F4EA", "#1E7B34"
    if e >= 0.85:
        return "#FFF4D6", "#8A5A00"
    return "#FDECEC", "#B42318"


@st.dialog("Save these?", width="large")
def _confirm(rows: list[dict], user: User) -> None:
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pr_ok"):
        try:
            n = pr.save(get_backend(), rows, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        st.session_state["pr_rows"] = []
        common.flash("success", f"{n} saved · see Production sheet → Processed.")
        st.rerun()
    if c2.button("Back", width="stretch", key="pr_back"):
        st.rerun()


def render(user: User) -> None:
    common.show_flash()
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### Processed")
    try:
        m = masters.load_masters()
        lots = pa.read()
        lines = indents.current_rows(indents.read_lines())
    except SheetError as e:
        common.sheet_error(e, "Could not load.")
        return

    cities = [c for c in m.cities() if user.sees_all_cities or user.in_my_cities(c)]
    top = st.columns([1, 3])
    day = top[0].date_input("Date", value=config.now_ist().date(), key="pr_day", format="DD/MM/YYYY").isoformat()
    city = cities[0] if cities else ""
    if len(cities) > 1:
        with top[1]:
            city = st.pills("City", cities, default=cities[0], key="pr_city") or cities[0]

    day_lots = pd.DataFrame(pa.view(lots, day, city))  # short names, for the check below
    raw = lots.copy() if lots is not None and not lots.empty else pd.DataFrame()
    if not raw.empty and "production_date" in raw.columns:
        raw = raw[(raw["production_date"].astype(str).str[:10] == day) & (raw["city"].astype(str) == city)]
    if day_lots.empty or raw.empty:
        st.info("No lots on tables for this date yet. Add them on **Pre-Production Actual** first.")
        _preview(user)
        return

    if not st.toggle("Phone view", key="pr_phone", help="One lot at a time (cards), easier on a phone"):
        _grid(raw, lines, day, city, user)
        return
    fruits = sorted({str(x) for x in raw["parent_sku"] if str(x).strip()}, key=str.casefold)
    fruit = st.pills("Fruit", fruits, key=f"pr_fruit_{day}")
    if fruit:
        f_lots = raw[raw["parent_sku"] == fruit]
        tables = sorted({str(t) for t in f_lots["table_no"]}, key=lambda t: (len(t), t))
        table = st.pills("Table", tables, key=f"pr_table_{day}_{fruit}",
                         default=tables[0] if len(tables) == 1 else None)
        if table:
            t_lots = f_lots[f_lots["table_no"].astype(str) == table].to_dict("records")
            _card(fruit, table, t_lots, lines, day, city)
    _preview(user)
    _saved(day, city)


def _lot_label(r: dict) -> str:
    bits = [r.get("size") or "", r.get("variety") or "", f"{pr._f(r.get('boxes_moved')):g} box"]
    return " · ".join(b for b in bits if b)


def _card(fruit: str, table: str, t_lots: list[dict], lines, day: str, city: str) -> None:
    with st.container(key="pr_card"):
        if len(t_lots) > 1:
            labels = [_lot_label(r) for r in t_lots]
            i = st.selectbox("Lot on table", range(len(t_lots)), format_func=lambda k: labels[k],
                             key=f"pr_lot_{day}_{fruit}_{table}")
        else:
            i = 0
        lot = t_lots[i]
        a, pcs, b = pr._f(lot.get("box_kg")), pr._f(lot.get("pcs_per_box")), pr._f(lot.get("boxes_moved"))
        x = a / pcs if a and pcs else 0
        from html import escape
        var = str(lot.get("variety") or "").strip()
        var_html = f"<span class='pr-var'>{escape(var)}</span> · " if var else ""
        st.markdown(f"<div class='pr-info'><b>{escape(fruit)}</b> {var_html}table {escape(table)} · "
                    f"{escape(str(lot.get('size') or ''))} · {b:g} box × {a:g} kg = "
                    f"<b>{a * b:g} kg</b>{f' · {x:.3f} kg/pc' if x else ''}</div>", unsafe_allow_html=True)

        needs = pr.packs_for(lines, fruit, day, city)
        options = list(needs) or ["1PC", "2PC", "3PC", "1Kg"]
        pack = st.pills("Cux lot", options, key=f"pr_pack_{lot.get('entry_id')}",
                        default=options[0] if len(options) == 1 else None)
        if not pack:
            st.caption("Pick the customer lot made from this lot.")
            return
        _, unit = pr.pack_kg(pack, x or None)
        if unit == "PC" and not x:
            st.warning("This lot has no Pcs/box, so piece packs can't be weighed. Fix it on Pre-Production Actual.")
        k = f"pr_{lot.get('entry_id')}_{pack}"
        piece = bool(x)                     # loose pieces only when we know kg per piece

        st.markdown("<div class='pr-grp' style='color:#1E7B34'>MT ready</div>", unsafe_allow_html=True)
        c = st.columns(2)
        with c[0]:
            d1 = _num(f"Packs ({pack})", f"{k}_d1")
        with c[1]:
            d2 = _num("Loose kg", f"{k}_d2", 0.1) if unit == "Kg" else None

        vals = {"mt_packs": d1, "mt_loose_kg": d2}
        for title, pre in (("MT leftover", "left"), ("GT Ready", "gt")):
            st.markdown(f"<div class='pr-grp'>{title}</div>", unsafe_allow_html=True)
            c = st.columns(2)
            with c[0]:
                vals[f"{pre}_box"] = _num("Box", f"{k}_{pre}_box")
            with c[1]:
                vals[f"{pre}_pcs" if piece else f"{pre}_kg"] = (_num("Pcs", f"{k}_{pre}_pcs") if piece
                                                                else _num("Kg", f"{k}_{pre}_kg", 0.1))
        st.markdown("<div class='pr-grp'>Dump</div>", unsafe_allow_html=True)
        c = st.columns(2)
        with c[0]:
            vals["dump_kg"] = _num("Kg", f"{k}_g1", 0.1)
        with c[1]:
            vals["dump_pcs"] = _num("Pcs", f"{k}_g2") if piece else None

        r = pr.compute(a, pcs, b, pack, vals)
        _result(r)
        if st.button("Add to preview", icon=":material/add:", type="primary", width="stretch", key=f"{k}_add",
                     disabled=not d1 and not any(vals.values())):
            _pending().append(pr.row(lot, pack, vals, day, city))
            for kk in list(st.session_state):
                if str(kk).startswith(k + "_"):
                    st.session_state.pop(kk, None)
            st.rerun()


def _result(r: dict) -> None:
    j = r["used_kg"]
    if j <= 0:
        st.error("Leftover is more than what was taken: check the boxes.")
        return
    loss = r["lotting"]
    bg, fg = _eff_colour(r["efficiency"])
    loss_txt = f"{'Loss' if loss >= 0 else 'Gain'}<b>{abs(loss):.2f} kg</b>"
    st.markdown(
        f"<div class='pr-res'><div>{loss_txt}</div>"
        f"<div style='background:{bg};color:{fg}'>Efficiency<b style='color:{fg}'>{pr.pct(r['efficiency'])}</b></div>"
        f"<div>GT Ready<b>{pr.pct(r['non_mt'])}</b></div><div>Dump<b>{pr.pct(r['dump_pct'])}</b></div></div>"
        f"<div class='pr-kg'>Taken {r['taken_kg']:.2f} · Leftover {r['left_kg_total']:.2f} · Used {j:.2f} · "
        f"MT {r['mt_kg']:.2f} · GT Ready {r['gt_kg_total']:.2f} · Dump {r['dump_kg_total']:.2f} kg</div>",
        unsafe_allow_html=True)


def _preview(user: User) -> None:
    rows = _pending()
    if not rows:
        return
    st.markdown(f"#### Preview · {len(rows)} to save")
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c = st.columns([1, 1])
    if c[0].button("Save all", type="primary", icon=":material/save:", width="stretch", key="pr_save"):
        _confirm(rows, user)
    drop = c[1].selectbox("Remove", ["—"] + [f"#{i + 1}" for i in range(len(rows))], key="pr_drop",
                          label_visibility="collapsed")
    if drop != "—":
        rows.pop(int(drop[1:]) - 1)
        st.session_state.pop("pr_drop", None)
        st.rerun()


def _saved(day: str, city: str) -> None:
    v = pr.latest(pr.read(), day, city)
    if v.empty:
        return
    st.markdown(f"#### Saved · {len(v)}")
    st.dataframe(common.numbered(pr.view(v)), hide_index=True, width="stretch")


# ------------------------------------------------------------------ grid (sheet-like) view, 25 Nov

G_COLS = {  # grid column -> processed input key
    "MT Ready (D1)": "mt_packs", "MT Ready kg (D2)": "mt_loose_kg",
    "Left over box (E1)": "left_box", "Left over kg (E2)": "left_kg", "Left over pcs (E3)": "left_pcs",
    "GT Ready box (F1)": "gt_box", "GT Ready kg (F2)": "gt_kg", "GT Ready pcs (F3)": "gt_pcs",
    "Dump kg (G1)": "dump_kg", "Dump pcs (G2)": "dump_pcs",
}
LOCKED = ["#", "Fruit", "Variety", "Size", "Table", "Boxes (B)", "Box kg (A)", "Pcs/box"]
DEFAULT_PACKS = ["1PC", "2PC", "3PC", "1Kg"]
PICK = "pick ▼"
NUM_RE = r"^\s*\d*(\.\d+)?\s*$"


def _cell(v) -> str:
    """Number cells are text (empty, not 'None'): '700', '2.5' or ''."""
    return "" if _blank(v) else f"{pr._f(v):g}"


def _pack(r: dict) -> str:
    p = r.get("Cux Lot")
    return "" if _blank(p) or p == PICK else str(p)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""


def _grid_row(lot: dict, pack: str = "", vals: dict | None = None, saved: bool = False) -> dict:
    vals = vals or {}
    r = {"lot_id": str(lot.get("entry_id")), "Fruit": lot.get("parent_sku", ""), "Variety": lot.get("variety", ""),
         "Size": lot.get("size", ""), "Table": str(lot.get("table_no", "")),
         "Boxes (B)": pr._f(lot.get("boxes_moved")), "Box kg (A)": pr._f(lot.get("box_kg")),
         "Pcs/box": pr._f(lot.get("pcs_per_box")) or None, "Cux Lot": pack or PICK}
    for col, k in G_COLS.items():
        v = vals.get(k)
        r[col] = "" if _blank(v) or pr._f(v) == 0 and not saved else _cell(v)
    c = vals.get("comment")
    r["Comments"] = "" if _blank(c) else str(c)
    r["_saved"] = saved
    return _with_result(r)


def _vals(r: dict) -> dict:
    return {k: (None if _blank(r.get(col)) else pr._f(r.get(col))) for col, k in G_COLS.items()}


def _with_result(r: dict) -> dict:
    vals = _vals(r)
    if not _pack(r) or not (any(v for v in vals.values()) or r.get("Comments")):
        r["Efficiency"], r["Status"] = "", "Saved" if r.get("_saved") else "Not entered"
        return r
    c = pr.compute(r["Box kg (A)"], r["Pcs/box"], r["Boxes (B)"], _pack(r), vals)
    r["Efficiency"] = pr.pct(c["efficiency"]) if c["used_kg"] > 0 else "check"
    r["Status"] = "Saved" if r.get("_saved") else "Not saved"
    return r


def _grid_base(raw: pd.DataFrame, day: str, city: str, key: str) -> list[dict]:
    """Rows kept in the session: saved entries first, every lot of the day at least once."""
    lots = raw.drop_duplicates("entry_id", keep="last")
    lots = lots.assign(_t=lots["table_no"].astype(str).str.zfill(3)).sort_values(["_t", "parent_sku"])
    ids = list(lots["entry_id"].astype(str))
    base = st.session_state.get(key)
    if base is not None and {r["lot_id"] for r in base} >= set(ids):
        return base
    done = pr.latest(pr.read(), day, city)
    by_lot: dict[str, list[dict]] = {}
    for r in done.to_dict("records") if not done.empty else []:
        by_lot.setdefault(str(r.get("lot_id")), []).append(r)
    keep = {r["lot_id"]: r for r in base or []}
    rows = []
    for lot in lots.to_dict("records"):
        lid = str(lot["entry_id"])
        if base is not None and lid in keep:
            rows += [r for r in base if r["lot_id"] == lid]
            continue
        saved = by_lot.get(lid, [])
        if saved:
            rows += [_grid_row(lot, o.get("cux_lot", ""), o, saved=True) for o in saved]
        else:
            rows.append(_grid_row(lot))
    st.session_state[key] = rows
    return rows


def _grid_edit(key: str, ekey: str) -> None:
    """data_editor on_change: copy the edits into the session rows and work out the result again."""
    base = st.session_state.get(key, [])
    for i, ch in (st.session_state.get(ekey) or {}).get("edited_rows", {}).items():
        r = base[int(i)]
        for col, v in ch.items():
            r[col] = v
        r["_saved"] = False
        _with_result(r)
    st.session_state.pop(ekey, None)


def _grid(raw: pd.DataFrame, lines, day: str, city: str, user: User) -> None:
    key, ekey = f"pg_rows_{day}_{city}", f"pg_ed_{day}_{city}"
    lots = {str(r["entry_id"]): r for r in raw.to_dict("records")}
    base = _grid_base(raw, day, city, key)
    packs = []
    for fruit in {r["Fruit"] for r in base}:
        packs += [p for p in pr.packs_for(lines, fruit, day, city) if p not in packs]
    packs += [p for p in DEFAULT_PACKS if p not in packs]
    entered = sum(1 for r in base if r["Status"] != "Not entered")
    st.caption(f"{len(base)} line(s) · {entered} entered · the rest is worked out and goes to "
               "**Production Tracking**.")
    st.markdown(
        "<div style='font-size:0.82rem;margin:-4px 0 6px 0'>"
        "<span style='background:#F1F4F7;border-radius:6px;padding:2px 8px'>🔒 filled for you</span> &nbsp;"
        "<span style='background:#FFF4D6;border-radius:6px;padding:2px 8px'>▼ pick from the list</span> &nbsp;"
        "<span style='background:#E6F4EA;border-radius:6px;padding:2px 8px'>✏️ type the number</span> &nbsp;"
        "<span style='background:#EDE7FB;border-radius:6px;padding:2px 8px'>💬 type a note</span> &nbsp;"
        "· double-click a cell (or tap it) to type · scroll sideways for more columns</div>",
        unsafe_allow_html=True)

    df = pd.DataFrame([{"#": i + 1, **{k: v for k, v in r.items() if k not in ("lot_id", "_saved")}}
                       for i, r in enumerate(base)])
    tips = {"MT Ready (D1)": "Customer packs made (in the Cux Lot chosen)",
            "MT Ready kg (D2)": "Loose MT kg, only for kg packs",
            "Left over box (E1)": "Full MT boxes not used", "Left over kg (E2)": "Loose MT kg not used",
            "Left over pcs (E3)": "Loose MT pieces not used", "GT Ready box (F1)": "Boxes to GT",
            "GT Ready kg (F2)": "Loose kg to GT", "GT Ready pcs (F3)": "Loose pieces to GT",
            "Dump kg (G1)": "Dump in kg", "Dump pcs (G2)": "Dump in pieces"}
    cfg = {col: st.column_config.TextColumn(f"✏️ {col}", width="medium", validate=NUM_RE,
                                            help=tips[col] + " · numbers only") for col in G_COLS}
    lock = {"#": ("#", "small"), "Fruit": ("🔒 Fruit", "small"), "Variety": ("🔒 Variety", "small"),
            "Size": ("🔒 Size", "small"), "Table": ("🔒 Table", "small"), "Boxes (B)": ("🔒 Boxes (B)", "small"),
            "Box kg (A)": ("🔒 Box kg (A)", "small"), "Pcs/box": ("🔒 Pcs/box", "small")}
    for col, (lab, w) in lock.items():
        cfg[col] = (st.column_config.NumberColumn(lab, format="%g", width=w, pinned=col in ("#", "Fruit", "Variety"))
                    if col in ("#", "Boxes (B)", "Box kg (A)", "Pcs/box")
                    else st.column_config.TextColumn(lab, width=w, pinned=col in ("Fruit", "Variety")))
    cfg["Cux Lot"] = st.column_config.SelectboxColumn("▼ Cux Lot", options=[PICK] + packs, width="medium",
                                                      required=True,
                                                      help="Pick the customer pack made from this lot")
    cfg["Comments"] = st.column_config.TextColumn("💬 Comments", width="large", max_chars=200,
                                                  help="Operations note, e.g. loose box, returns mixed")
    cfg["Efficiency"] = st.column_config.TextColumn("Efficiency", width="small", help="MT kg ÷ used kg")
    cfg["Status"] = st.column_config.TextColumn("Status", width="small")
    st.data_editor(df, key=ekey, hide_index=True, width="stretch", column_config=cfg, num_rows="fixed",
                   disabled=list(lock) + ["Efficiency", "Status"], on_change=_grid_edit, args=(key, ekey),
                   column_order=list(lock) + ["Cux Lot"] + list(G_COLS) + ["Comments", "Efficiency", "Status"])

    c = st.columns([2, 1, 1])
    labels = [f"#{i + 1} · {r['Fruit']} · table {r['Table']} · {r['Size']}" for i, r in enumerate(base)]
    with c[0]:
        pick = st.selectbox("Another pack from", range(len(base)), format_func=lambda i: labels[i],
                            index=None, placeholder="Another pack from line…", key=f"pg_dup_{day}",
                            label_visibility="collapsed")
    if c[1].button("＋ Add line", width="stretch", key="pg_add", disabled=pick is None):
        src = base[pick]
        base.insert(pick + 1, _grid_row(lots.get(src["lot_id"], {}) or {"entry_id": src["lot_id"]}))
        st.session_state.pop(ekey, None)
        st.session_state.pop(f"pg_dup_{day}", None)
        st.rerun()
    todo = [r for r in base if r["Status"] == "Not saved"]
    if c[2].button(f"Save {len(todo)} line(s)" if todo else "Save", type="primary", icon=":material/save:",
                   width="stretch", key="pg_save", disabled=not todo):
        rows = [pr.row(lots[r["lot_id"]], _pack(r), _vals(r), day, city, r.get("Comments") or "")
                for r in todo if r["lot_id"] in lots]
        _grid_confirm(rows, todo, user)
    bad = [i + 1 for i, r in enumerate(base) if r["Efficiency"] == "check"]
    if bad:
        st.warning("Line " + ", ".join(f"#{b}" for b in bad) + ": leftover is more than what went on the table.")


@st.dialog("Save these lines?", width="large")
def _grid_confirm(rows: list[dict], todo: list[dict], user: User) -> None:
    st.dataframe(common.numbered(pr.view(rows)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    if c1.button("Save", type="primary", icon=":material/save:", width="stretch", key="pg_ok"):
        try:
            n = pr.save(get_backend(), rows, user.email)
        except SheetError as e:
            st.error(f"Not saved. {e}")
            return
        for r in todo:
            r["_saved"] = True
            _with_result(r)
        common.flash("success", f"{n} line(s) saved · see Production Tracking.")
        st.rerun()
    if c2.button("Back", width="stretch", key="pg_back"):
        st.rerun()
