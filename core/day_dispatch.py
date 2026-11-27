"""Dispatch and Returns at the end of the day (27 Nov, trial; user-approved preview).

The PO is final: the invoice is on the PO qty only. The team may still send more than the PO (extra stock);
what comes back is typed on Returns, and the check per item is
    sent = with the customer + returned;  billed = the smaller of (with the customer, PO qty).
No PO yet -> the indent qty stands in for the PO. An indent item that is not on the PO is asked 0.

MT stock is a pool per city + day + fruit (+ variety for Apple) + customer lot, from Production Detail Process:
piece lots in packs ('2PC' x 150), kg lots in kg. Every dispatch takes from the pool, whoever the customer is.

Tabs Day_Dispatch / Day_Returns: create only (never edited); a later round for the same indent adds up."""
from __future__ import annotations

import re
import uuid

import pandas as pd

from core import boxes, config
from core import processed as pr
from core import processed2 as p2
from core.models import IndentLine
from core.prod_actual import pkey
from core.schema import DAY_DISPATCH, DAY_RETURNS

GRADES = {"hg", "sg", "xf"}          # 'Gala HG' is still Gala for the customer
REASONS = ["Extra stock back", "Damaged", "Quality", "Short shelf life", "Other"]


def _s(v) -> str:
    return " ".join(str(v or "").split())


def _n(s) -> str:
    return _s(s).casefold()


def vkey(parent, variety) -> str:
    """Variety only where the customer chooses one (Apple); grade words dropped."""
    if pkey(parent) not in {pkey(x) for x in config.variety_parents()}:
        return ""
    return " ".join(w for w in _n(variety).split() if w not in GRADES)


def pool_of(parent, variety, lot, lot_size) -> tuple[str, str, float]:
    """(pool key, unit, pool units in one lot). Piece lots: packs of that size; kg / gram lots: kg.
    Box lots have no pool yet ('' key)."""
    kind, n = boxes.per_lot(lot, lot_size)
    base = f"{pkey(parent)}|{vkey(parent, variety)}"
    if kind == "pcs":
        return f"{base}|{n:g}pc", "packs", 1.0
    if kind == "kg" and n:
        return f"{base}|kg", "kg", float(n)
    return "", "box", 0.0


def pool_label(key: str) -> str:
    p, v, pack = (key.split("|") + ["", ""])[:3]
    return " · ".join(x for x in (p.title(), v.title(), pack.upper().replace("PC", " PC") if pack != "kg" else "Kg")
                      if x)


def mt_made(lots: pd.DataFrame, saved: pd.DataFrame, day: str, city: str) -> dict[str, float]:
    """{pool key: MT ready} from what is saved (or submitted) on Production Detail Process for the day + city."""
    if lots is None or lots.empty or "production_date" not in lots.columns:
        return {}
    raw = lots[(lots["production_date"].astype(str).str[:10] == day) & (lots["city"].astype(str) == city)]
    done = p2.latest(saved, day, city)
    out: dict[str, float] = {}
    for key, it in p2.items(raw).items():
        s = done.get(f"{day}|{city}|{key}")
        for ln in (s or {}).get("lines", []):
            ln = p2.clean_line(ln)
            base = f"{pkey(it.get('parent_sku'))}|{vkey(it.get('parent_sku'), it.get('variety'))}"
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*PC", _s(ln.get("pack")), flags=re.I)
            if m:
                k, q = f"{base}|{float(m.group(1)):g}pc", pr._f(ln.get("mt_packs"))
            elif p2.lot_unit(ln.get("pack", "")) == "Kg":
                k, q = f"{base}|kg", pr._f(ln.get("mt_loose_kg"))
            else:
                continue
            if q:
                out[k] = out.get(k, 0.0) + q
    return out


def asked(lines: pd.DataFrame, po: pd.DataFrame | None, day: str, city: str,
          links: dict | None = None) -> list[dict]:
    """One row per indent item of the day + city (current versions): indent qty, PO qty (None = no PO yet or
    not on the PO), asked = PO qty when the indent has a PO (not on it = 0), else the indent qty.
    Items only on the PO come last for their indent. links = PO_Item_Map per customer."""
    if lines is None or lines.empty:
        return []
    d = lines[(lines["delivery_date"].astype(str).str[:10] == day) & (lines["city"].astype(str) == city)]
    from core import indents
    out = []
    for iid, grp in d.groupby("indent_id", sort=True):
        recs = [r for r in grp.to_dict("records") if _s(r.get("customer_sku_name"))]
        if not recs:
            continue
        head = recs[0]
        info = indents.po_info(po, str(iid))
        has_po = info["qty"] is not None
        ils = [IndentLine(parent_sku=r["parent_sku"], customer_sku_name=r["customer_sku_name"],
                          variety=r.get("variety", ""), lot=r.get("lot", ""), qty=r["qty"]) for r in recs]
        cmp = {_n(c["customer_sku_name"]): c for c in indents.po_vs_indent(
            ils, info, item_map=(links or {}).get(_n(head.get("customer")), {}))} if has_po else {}
        base = {"indent_id": str(iid), "customer": _s(head.get("customer")), "store": _s(head.get("store")),
                "has_po": has_po, "po_numbers": ", ".join(info["numbers"])}
        for r in recs:
            ind = pr._f(r.get("qty"))
            c = cmp.pop(_n(r["customer_sku_name"]), None)
            poq = c["po_qty"] if c else None
            if not has_po and ind <= 0:
                continue
            if has_po and ind <= 0 and not poq:
                continue
            key, unit, per = pool_of(r.get("parent_sku"), r.get("variety"), r.get("lot"), r.get("lot_size"))
            out.append({**base, "customer_sku_name": _s(r["customer_sku_name"]), "parent_sku": _s(r.get("parent_sku")),
                        "variety": _s(r.get("variety")), "lot": _s(r.get("lot")), "lot_size": _s(r.get("lot_size")),
                        "indent_qty": ind, "po_qty": poq, "asked": (poq or 0.0) if has_po else ind,
                        "basis": "PO" if has_po else "Indent", "pool_key": key, "unit": unit, "per": per})
        for c in cmp.values():                       # on the PO, not on the indent
            if c["indent_qty"] is None and c["po_qty"]:
                out.append({**base, "customer_sku_name": _s(c["customer_sku_name"]), "parent_sku": "", "variety": "",
                            "lot": "", "lot_size": "", "indent_qty": 0.0, "po_qty": c["po_qty"],
                            "asked": c["po_qty"], "basis": "PO", "pool_key": "", "unit": "box", "per": 0.0,
                            "po_only": True})
    return out


def read(tab: str, backend=None) -> pd.DataFrame:
    from core import store_settings
    return store_settings._read(backend, tab)


def _day(df: pd.DataFrame, day: str, city: str) -> pd.DataFrame:
    if df is None or df.empty or "delivery_date" not in df.columns:
        return pd.DataFrame()
    return df[(df["delivery_date"].astype(str).str[:10] == day) & (df["city"].astype(str) == city)]


def totals(df: pd.DataFrame, day: str, city: str, col: str) -> dict[tuple, float]:
    """{(indent_id, item name): qty added over every round}."""
    out: dict[tuple, float] = {}
    for r in _day(df, day, city).to_dict("records"):
        k = (str(r.get("indent_id")), _n(r.get("customer_sku_name")))
        out[k] = out.get(k, 0.0) + pr._f(r.get(col))
    return out


def rounds(df: pd.DataFrame, day: str, city: str, id_col: str) -> dict[str, list[dict]]:
    """{indent_id: [{'at', 'by', 'n'}]} one per saved round, oldest first."""
    out: dict[str, list[dict]] = {}
    d = _day(df, day, city)
    if d.empty:
        return out
    for (iid, _), grp in d.groupby([d["indent_id"].astype(str), d[id_col].astype(str)], sort=False):
        r = grp.iloc[0]
        out.setdefault(iid, []).append({"at": str(r.get("saved_at") or ""), "by": str(r.get("saved_by") or ""),
                                        "n": len(grp)})
    return out


def pool_used(dispatch: pd.DataFrame, day: str, city: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in _day(dispatch, day, city).to_dict("records"):
        k = _s(r.get("pool_key"))
        if k:
            out[k] = out.get(k, 0.0) + pr._f(r.get("from_pool"))
    return out


def dispatch_rows(items: list[dict], qty: dict[str, float], day: str, city: str, user: str) -> list[dict]:
    """Rows of one round for one indent; items = its asked() rows, qty = {item name: lots sent now}."""
    did, stamp = uuid.uuid4().hex[:10], config.now_iso()
    rows = []
    for it in items:
        q = pr._f(qty.get(it["customer_sku_name"]))
        if q <= 0:
            continue
        rows.append({"dispatch_id": did, "saved_at": stamp, "saved_by": user, "delivery_date": day, "city": city,
                     **{c: it[c] for c in ("indent_id", "customer", "store", "customer_sku_name", "parent_sku",
                                           "variety", "lot", "lot_size", "pool_key", "unit", "per", "basis")},
                     "indent_qty": it["indent_qty"], "po_qty": "" if it["po_qty"] is None else it["po_qty"],
                     "asked_qty": it["asked"], "dispatch_qty": q, "from_pool": q * it["per"]})
    return rows


def return_rows(items: list[dict], qty: dict[str, float], reason: dict[str, str], day: str, city: str,
                user: str) -> list[dict]:
    """One row per item of the indent that was sent, 0 included (0 = 'nothing came back' was entered)."""
    rid, stamp = uuid.uuid4().hex[:10], config.now_iso()
    return [{"return_id": rid, "saved_at": stamp, "saved_by": user, "delivery_date": day, "city": city,
             "indent_id": it["indent_id"], "customer": it["customer"], "store": it["store"],
             "customer_sku_name": it["customer_sku_name"], "returned_qty": pr._f(qty.get(it["customer_sku_name"])),
             "reason": _s(reason.get(it["customer_sku_name"])) if pr._f(qty.get(it["customer_sku_name"])) else ""}
            for it in items]


def save(backend, tab: str, rows: list[dict]) -> int:
    if rows:
        backend.append_dicts(tab, rows)
        try:
            from core import indents
            indents.clear_cache()
        except Exception:  # noqa: BLE001
            pass
    return len(rows)


def check(asked_qty: float, sent: float, back: float, returns_in: bool) -> dict:
    """The full check of one item. Billed never goes above the PO (asked) qty."""
    held = sent - back
    extra = max(sent - asked_qty, 0.0)
    out = {"sent": sent, "returned": back, "with_customer": held, "extra_sent": extra,
           "extra_back": min(back, extra), "billed": max(min(held, asked_qty), 0.0),
           "over": max(held - asked_qty, 0.0), "short": max(asked_qty - held, 0.0)}
    if sent <= 0:
        out["status"] = "Not asked" if asked_qty <= 0 else "Not sent"
    elif back > sent + 1e-9:
        out["status"] = "Returned more than sent"
    elif not returns_in:
        out["status"] = "Returns pending"
    elif out["over"] > 1e-9:
        out["status"] = f"{out['over']:g} over PO with customer"
    elif out["short"] > 1e-9:
        out["status"] = f"Short {out['short']:g}"
    else:
        out["status"] = "Billed as PO"
    return out


CHECK_HEAD = ["Customer", "Delivery point", "Indent", "Item", "PO qty", "Indent qty", "Sent", "Extra sent",
              "Returned", "With customer", "Billed", "Status"]


def check_rows(items: list[dict], sent: dict, back: dict, back_rounds: dict) -> list[dict]:
    out = []
    for it in items:
        k = (it["indent_id"], _n(it["customer_sku_name"]))
        c = check(it["asked"], sent.get(k, 0.0), back.get(k, 0.0), it["indent_id"] in back_rounds)
        out.append({"Customer": it["customer"], "Delivery point": it["store"], "Indent": it["indent_id"],
                    "Item": it["customer_sku_name"], "PO qty": it["po_qty"] if it["has_po"] else None,
                    "Indent qty": it["indent_qty"], "Sent": c["sent"], "Extra sent": c["extra_sent"],
                    "Returned": c["returned"] if it["indent_id"] in back_rounds else None,
                    "With customer": c["with_customer"], "Billed": c["billed"], "Status": c["status"]})
    return out


STOCK_HEAD = ["MT stock", "Unit", "MT made", "Asked", "Dispatched", "MT left", "Returned", "Sold of MT"]


def stock_rows(made: dict[str, float], items: list[dict], sent: dict, back: dict) -> list[dict]:
    """End of day, per MT pool: made, asked (PO / indent), dispatched, left with the team, returned,
    and how much of the day's MT stayed with customers (0-1, None when nothing was made)."""
    agg: dict[str, dict] = {k: {"made": v, "asked": 0.0, "sent": 0.0, "back": 0.0} for k, v in made.items()}
    for it in items:
        if not it["pool_key"]:
            continue
        g = agg.setdefault(it["pool_key"], {"made": 0.0, "asked": 0.0, "sent": 0.0, "back": 0.0})
        k = (it["indent_id"], _n(it["customer_sku_name"]))
        g["asked"] += it["asked"] * it["per"]
        g["sent"] += sent.get(k, 0.0) * it["per"]
        g["back"] += back.get(k, 0.0) * it["per"]
    return [{"MT stock": pool_label(k), "Unit": "kg" if k.endswith("|kg") else "packs", "MT made": g["made"],
             "Asked": g["asked"], "Dispatched": g["sent"], "MT left": g["made"] - g["sent"], "Returned": g["back"],
             "Sold of MT": (g["sent"] - g["back"]) / g["made"] if g["made"] > 0 else None}
            for k, g in sorted(agg.items())]
