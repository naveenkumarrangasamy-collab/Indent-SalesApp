"""City-level Batching plan and Actual dispatch (25 Nov; owners only, trial).

Flow for one delivery date + city (every customer clubbed, like Pre-production actual):
1. Pre-production actual records the boxes taken out, per fruit row (club key) and option
   ('Country · Grade · Count · Box kg').
2. Batching plan: per take-out option the team types what grading gave: **MT** (good, for the
   customers), **GT** (general trade) and **Dump**. Left = fruit in the boxes − MT − GT − Dump.
   It can be changed any time (last saved row wins, tab City_Grading).
3. Actual dispatch: per indent (customer + delivery point) the team types what is sent, in the SKU's own
   unit (packs of 2 pcs, kg, punnets …). That comes out of the fruit row's MT stock. More than asked is allowed
   up to `dispatch_extra_pct` (default 10 %, per customer possible) once "send extra" is ticked. Saving makes
   the Delivery Order (Dispatch_Lines, so Returns / invoice keep working) and **locks** the indent;
   an owner can unlock it (Dispatch_Locks) to send a corrected one.
4. End of day: per fruit row, fruit taken = MT + GT + Dump (+ not graded) and MT = dispatched + MT left.
   A row where more was dispatched than MT graded is red.
The functions take DataFrames so they can be tested without the sheet.
"""
from __future__ import annotations

import pandas as pd

from core import config
from core import preprod
from core import preprod_city as pc
from core.models import fmt_num, to_number
from core.schema import CITY_GRADING, DISPATCH_LINES, DISPATCH_LOCKS

ROUND = 3


def _c(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else " ".join(str(v).split())


def _k(v) -> str:
    return _c(v).casefold()


def _num(v) -> float | None:
    s = _c(v)
    return None if s == "" else to_number(s)


# ------------------------------------------------------------------ grading (Batching plan)

def grading(df: pd.DataFrame | None, day: str, city: str) -> dict[tuple[str, str], dict]:
    """{(club key, option): {'mt', 'gt', 'dump', 'at', 'by'}} - the last saved row per option."""
    out: dict[tuple[str, str], dict] = {}
    if df is None or df.empty:
        return out
    for r in df.to_dict("records"):
        if _c(r.get("delivery_date")) != _c(day) or _k(r.get("city")) != _k(city):
            continue
        out[(_c(r.get("club_key")), _c(r.get("option")))] = {
            "mt": _num(r.get("mt")), "gt": _num(r.get("gt")), "dump": _num(r.get("dump")),
            "at": _c(r.get("saved_at")), "by": _c(r.get("saved_by"))}
    return out


def left(fruit: float | None, mt, gt, dump) -> float | None:
    if fruit is None:
        return None
    return round(fruit - (mt or 0) - (gt or 0) - (dump or 0), ROUND)


def grade_rows(row: dict, took: dict[str, float], opts: list[dict], saved: dict) -> list[dict]:
    """One line per take-out option of a fruit row: option, boxes, fruit (None = holding not known), mt, gt, dump,
    left, graded (any number typed)."""
    by = {o["label"]: o for o in opts}
    out = []
    for label, boxes in took.items():
        h = pc.holds(by.get(label) or pc._from_label(label), row["unit"], row["parent"])
        fruit = round(boxes * h, ROUND) if h else None
        v = saved.get((row["key"], label), {})
        mt, gt, dump = v.get("mt"), v.get("gt"), v.get("dump")
        out.append({"option": label, "boxes": boxes, "fruit": fruit, "mt": mt, "gt": gt, "dump": dump,
                    "left": left(fruit, mt, gt, dump),
                    "graded": any(x is not None for x in (mt, gt, dump))})
    return out


def grade_status(lines: list[dict]) -> str:
    """Not graded / Part graded / Graded / Over (more typed than the boxes hold)."""
    if not lines or not any(x["graded"] for x in lines):
        return "Not graded"
    if any(x["left"] is not None and x["left"] < -1e-9 for x in lines):
        return "Over"
    if all(x["graded"] and (x["left"] is None or abs(x["left"]) < 1e-9) for x in lines):
        return "Graded"
    return "Part graded"


def save_grading(backend, day: str, city: str, row: dict, lines: list[dict], user: str) -> int:
    stamp = config.now_iso()
    out = [{"saved_at": stamp, "saved_by": user, "delivery_date": day, "city": city, "club_key": row["key"],
            "parent_sku": row["parent"], "variety": row["variety"], "unit": row["unit"], "option": x["option"],
            "boxes": x["boxes"], "fruit": "" if x["fruit"] is None else x["fruit"],
            "mt": "" if x["mt"] is None else x["mt"], "gt": "" if x["gt"] is None else x["gt"],
            "dump": "" if x["dump"] is None else x["dump"]} for x in lines]
    if out:
        backend.append_dicts(CITY_GRADING, out)
        preprod._clear()
    return len(out)


# ------------------------------------------------------------------ dispatch

def extra_pct(customer: str) -> float:
    """How much more than asked may be sent: secret `dispatch_extra_pct`, a number (default 10) or
    {customer first word: pct, "default": pct} (user 25 Nov: per customer later)."""
    raw = config.get("dispatch_extra_pct", 10)
    if isinstance(raw, dict):
        first = _k(customer).split(" ")[0] if customer else ""
        for k, v in raw.items():
            if _k(k) == first or _k(k) == _k(customer):
                return float(v)
        return float(raw.get("default", 10))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 10.0


def unit_word(unit: str, per: float) -> str:
    """'packs of 2 pcs', 'pcs', 'kg', 'packs of 0.5 kg', 'punnets', 'packs'."""
    if unit == "punnets":
        return "punnets" if abs(per - 1) < 1e-9 else f"trays of {fmt_num(per)} punnets"
    if unit in ("pcs", "kg"):
        return unit if abs(per - 1) < 1e-9 else f"packs of {fmt_num(per)} {unit}"
    return "packs"


def indent_lines(lines: pd.DataFrame, po_qty: dict, po_ids: set, extras: list[dict], ask_variety) -> dict[str, dict]:
    """Current lines of ONE date + city -> {indent_id: {customer, store, lines: [...]}}. Asked = the PO qty when
    the indent has a PO (not on the PO = left out, PO-only items added), else the indent qty."""
    out: dict[str, dict] = {}
    if lines is None or lines.empty:
        return out
    parents = [p for p in lines["parent_sku"].map(_c).unique() if p]
    for iid, g in lines.groupby("indent_id", sort=True):
        first = g.iloc[0]
        d = out.setdefault(str(iid), {"customer": _c(first["customer"]), "store": _c(first["store"]),
                                      "city": _c(first["city"]), "lines": []})
        for r in g.to_dict("records"):
            name = _c(r["customer_sku_name"])
            qty = to_number(r.get("qty"))
            asked = qty
            if iid in po_ids:
                p = po_qty.get((iid, _k(name)))
                if p is None:
                    continue
                asked = float(p)
            if asked <= 0:
                continue
            d["lines"].append(_line(name, _c(r.get("parent_sku")), _c(r.get("variety")), _c(r.get("lot")),
                                    qty, asked, to_number(r.get("price")), parents, ask_variety))
        for e in extras:
            if _k(e.get("Customer")) == _k(first["customer"]) and _k(e.get("Delivery point")) == _k(first["store"]):
                name = _c(e["Customer SKU Name"])
                d["lines"].append(_line(name, "", "", "", 0.0, float(to_number(e.get("PO qty"))), 0.0, parents,
                                        ask_variety, po_only=True))
    return {i: d for i, d in out.items() if d["lines"]}


def _line(name, parent, variety, lot, qty, asked, price, parents, ask_variety, po_only=False) -> dict:
    parent = parent or pc._guess_parent(name, parents) or "Not mapped"
    unit, per = preprod.need_unit(name, lot, parent)
    variety = variety if ask_variety(parent) else ""
    return {"name": name, "parent": parent, "variety": variety, "lot": lot, "indent_qty": qty, "asked": asked,
            "price": price, "unit": unit, "per": per or 1.0, "key": pc.club_key(parent, variety, unit),
            "word": unit_word(unit, per or 1.0), "po_only": po_only}


def locks(df: pd.DataFrame | None) -> dict[str, str]:
    """{indent_id: doc_no unlocked} - an unlocked doc no longer locks the indent."""
    out: dict[str, str] = {}
    if df is None or df.empty:
        return out
    for r in df.to_dict("records"):
        if _k(r.get("action")) == "unlock":
            out[_c(r.get("indent_id"))] = _c(r.get("doc_no"))
    return out


def dispatch_state(ddf: pd.DataFrame | None, unlocked: dict[str, str], indent_id: str) -> dict:
    """{'doc_no', 'at', 'by', 'items' {sku key: row}, 'locked'} of the last dispatch of the indent, or {}."""
    from core import dispatch
    d = dispatch.dispatched(ddf, indent_id)
    if not d:
        return {}
    d["locked"] = unlocked.get(_c(indent_id)) != d["doc_no"]
    return d


def mt_used(ddf: pd.DataFrame | None, day: str, city: str, skip: str = "") -> dict[str, float]:
    """{club key: MT taken} by the last dispatch of every indent of this date + city (except `skip`).
    Unlocked dispatches still count until they are replaced: the goods went out."""
    from core import dispatch
    out: dict[str, float] = {}
    if ddf is None or ddf.empty or "indent_id" not in ddf.columns:
        return out
    df = ddf[(ddf["delivery_date"].map(_c) == _c(day)) & (ddf["city"].map(_k) == _k(city))]
    for iid in df["indent_id"].map(_c).unique():
        if iid == _c(skip):
            continue
        for r in dispatch.dispatched(df, iid).get("items", {}).values():
            k = _c(r.get("club_key"))
            if k:
                out[k] = round(out.get(k, 0.0) + to_number(r.get("from_mt")), ROUND)
    return out


def check(asked: float, qty: float | None, pct: float, extra_ok: bool) -> tuple[str, str]:
    """('ok'|'warn'|'bad', label) for one line: Same / n short / +n extra (needs 'send extra') / over the limit."""
    if qty is None:
        return "bad", "Not entered"
    diff = round(qty - asked, ROUND)
    if abs(diff) < 1e-9:
        return "ok", "Same"
    if diff < 0:
        return "warn", f"{fmt_num(-diff)} short"
    if qty > preprod.max_allowed(asked, pct) + 1e-9 and qty > asked + 1 + 1e-9:
        return "bad", f"+{fmt_num(diff)} over the {fmt_num(pct)} % limit"
    return ("ok" if extra_ok else "bad"), f"+{fmt_num(diff)} extra" + ("" if extra_ok else " · tick Send extra")


def day_check(rows: list[dict], fruit_mt: dict[str, dict], used: dict[str, float]) -> list[dict]:
    """End of day per fruit row: fruit taken, MT, GT, Dump, not graded, dispatched, MT left, ok."""
    out = []
    for r in rows:
        f = fruit_mt.get(r["key"], {})
        disp = used.get(r["key"], 0.0)
        mt = f.get("mt", 0.0)
        fruit = f.get("fruit")
        graded = round(mt + f.get("gt", 0.0) + f.get("dump", 0.0), ROUND)
        not_graded = round(fruit - graded, ROUND) if fruit is not None else None
        mt_left = round(mt - disp, ROUND)
        notes = []
        if mt_left < -1e-9:
            notes.append(f"sent {fmt_num(-mt_left)} more than MT graded")
        if not_graded is not None and not_graded > 1e-9:
            notes.append(f"{fmt_num(not_graded)} not graded")
        if not_graded is not None and not_graded < -1e-9:
            notes.append(f"graded {fmt_num(-not_graded)} more than taken")
        if not f.get("boxes"):
            notes.append("nothing taken out")
        out.append({"key": r["key"], "parent": r["parent"], "variety": r["variety"], "unit": r["unit"],
                    "need": r["need"], "boxes": f.get("boxes", 0), "fruit": fruit, "mt": mt,
                    "gt": f.get("gt", 0.0), "dump": f.get("dump", 0.0), "not_graded": not_graded,
                    "dispatched": disp, "mt_left": mt_left, "ok": not notes, "notes": notes})
    return out


def fruit_totals(rows: list[dict], took_all: dict, opts_for, saved: dict) -> dict[str, dict]:
    """{club key: {'boxes', 'fruit' (None = not known), 'mt', 'gt', 'dump'}} from the take-outs + grading."""
    out = {}
    for r in rows:
        lines = grade_rows(r, took_all.get(r["key"], {}), opts_for(r), saved)
        known = all(x["fruit"] is not None for x in lines)
        out[r["key"]] = {"boxes": sum(x["boxes"] for x in lines),
                         "fruit": round(sum(x["fruit"] or 0 for x in lines), ROUND) if known else None,
                         "mt": round(sum(x["mt"] or 0 for x in lines), ROUND),
                         "gt": round(sum(x["gt"] or 0 for x in lines), ROUND),
                         "dump": round(sum(x["dump"] or 0 for x in lines), ROUND)}
    return out


def save_unlock(backend, indent_id: str, doc_no: str, reason: str, user: str) -> None:
    backend.append_dicts(DISPATCH_LOCKS, [{"at": config.now_iso(), "by": user, "indent_id": indent_id,
                                           "doc_no": doc_no, "action": "unlock", "reason": reason}])


TABS = (CITY_GRADING, DISPATCH_LOCKS, DISPATCH_LINES)


def read_all() -> dict[str, pd.DataFrame]:
    return {t: preprod._read(t) for t in TABS}
