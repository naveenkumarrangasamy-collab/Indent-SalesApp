"""Return grading and the MT stock pool (23 Nov night; OWNERS ONLY while being tried).

Returns of delivery day D are graded on the next morning into MT (good for another MT
customer), GT (sell to general trade) and Dump. The MT part, plus the Batching plan's left-over
**MT Grade** of day D, is the **MT stock** for Pre-production of day D + 1. It is pooled by
city + parent SKU + variety + unit (pcs / kg / punnets), not by customer. Pre-production records
how much of it each SKU uses; whatever is not used that day goes to GT (it is simply not counted
on later days).

Tabs (append-only, created on first save, last row wins):
- Return_Grading: one row per indent + SKU (grade of the returns of day D).
- Return_Use: one row per pool day + city + customer group + SKU (MT stock used in Pre-production).
Quantities are in the Pre-production unit (pieces, kg or punnets), never in packs.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core import config
from core.models import fmt_num, to_number
from core.schema import RETURN_GRADING, RETURN_USE

GRADED, PART, NOT_GRADED = "Graded", "Part graded", "Not graded"


def _c(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else " ".join(str(v).split())


def _k(v) -> str:
    return _c(v).casefold()


def next_day(day: str) -> str:
    return (date.fromisoformat(_c(day)[:10]) + timedelta(days=1)).isoformat()


def prev_day(day: str) -> str:
    return (date.fromisoformat(_c(day)[:10]) - timedelta(days=1)).isoformat()


def _norm(df: pd.DataFrame | None, cols: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df


def _spec(v) -> str:
    v = _c(v)
    return f"{v}C" if v.isdigit() and int(v) >= 10 else (v or "any size")


def pool_key(city: str, parent: str, variety: str, unit: str) -> tuple[str, str, str, str]:
    var = _k(variety) if _k(parent) in {_k(x) for x in config.variety_parents()} else ""   # Apple only
    return _k(city), _k(parent), var, _k(unit)


# ------------------------------------------------------------------ grading

def grading_saved(grading: pd.DataFrame | None, return_date: str) -> dict[tuple[str, str], dict]:
    """{(indent_id, sku key): {'spec', 'mt', 'gt', 'dump'}} - the last saved grade of each returned item."""
    df = _norm(grading, ["return_date", "indent_id", "customer_sku_name", "spec", "mt", "gt", "dump"])
    df = df[df["return_date"].map(_c) == _c(return_date)]
    out = {}
    for r in df.to_dict("records"):
        out[(_c(r["indent_id"]), _k(r["customer_sku_name"]))] = {
            "spec": _c(r["spec"]), **{c: (to_number(r[c]) if _c(r[c]) else None) for c in ("mt", "gt", "dump")}}
    return out


def grade_status(returned: float, mt: float | None, gt: float | None, dump: float | None) -> tuple[str, float]:
    """(status, still to grade). More than returned is 'Over'."""
    done = (mt or 0) + (gt or 0) + (dump or 0)
    left = round(returned - done, 3)
    if left < -1e-9:
        return "Over", left
    if mt is None and gt is None and dump is None:
        return NOT_GRADED, left
    return (GRADED, 0.0) if abs(left) < 1e-9 else (PART, left)


def save_grading(backend, return_date: str, rows: list[dict], user: str) -> int:
    """rows: [{indent_id, city, customer, customer_sku_name, parent_sku, variety, unit, spec, returned, mt, gt, dump}]."""
    stamp = config.now_iso()
    out = [{"saved_at": stamp, "saved_by": user, "return_date": return_date, "pool_date": next_day(return_date),
            **r} for r in rows]
    if out:
        backend.append_dicts(RETURN_GRADING, out)
    return len(out)


# ------------------------------------------------------------------ pool

def pool(grading: pd.DataFrame | None, plan: pd.DataFrame | None, day: str) -> dict[tuple, dict]:
    """MT stock for Pre-production of `day`: {pool key: {'qty': total, 'parts': {label: qty}}}.
    From the grading of returns of day - 1 (last row per indent + SKU) and the Batching plan's
    MT Grade of day - 1 (item rows that carry parent_sku)."""
    src = prev_day(day)
    out: dict[tuple, dict] = {}

    def add(key, qty, label):
        if qty and qty > 0:
            d = out.setdefault(key, {"qty": 0.0, "parts": {}})
            d["qty"] = round(d["qty"] + qty, 3)
            d["parts"][label] = round(d["parts"].get(label, 0) + qty, 3)

    g = _norm(grading, ["return_date", "indent_id", "city", "customer_sku_name", "parent_sku", "variety", "unit",
                        "spec", "mt"])
    g = g[g["return_date"].map(_c) == src]
    last = {}
    for r in g.to_dict("records"):
        last[(_c(r["indent_id"]), _k(r["customer_sku_name"]))] = r
    for r in last.values():
        add(pool_key(r["city"], r["parent_sku"], r["variety"], r["unit"]), to_number(r["mt"]),
            f"returns {_spec(r['spec'])}")

    p = _norm(plan, ["delivery_date", "city", "group", "customer_sku_name", "spec", "mt_grade", "parent_sku",
                     "variety", "unit"])
    p = p[(p["delivery_date"].map(_c) == src) & (p["spec"].map(_c) == "_item")]
    last = {}
    for r in p.to_dict("records"):
        last[(_k(r["city"]), _k(r["group"]), _k(r["customer_sku_name"]))] = r
    for r in last.values():
        if _c(r["parent_sku"]):
            add(pool_key(r["city"], r["parent_sku"], r["variety"], r["unit"]), to_number(r["mt_grade"]),
                "batching MT grade")
    return out


def uses(use: pd.DataFrame | None, day: str) -> dict[tuple[str, str, str], dict]:
    """{(city, group, sku key): {'qty', 'key' (pool key)}} - the last saved use per SKU on `day`."""
    df = _norm(use, ["use_date", "city", "group", "customer_sku_name", "parent_sku", "variety", "unit", "qty"])
    df = df[df["use_date"].map(_c) == _c(day)]
    out = {}
    for r in df.to_dict("records"):
        out[(_k(r["city"]), _k(r["group"]), _k(r["customer_sku_name"]))] = {
            "qty": to_number(r["qty"]), "key": pool_key(r["city"], r["parent_sku"], r["variety"], r["unit"])}
    return out


def available(pool_: dict, uses_: dict, key: tuple, me: tuple[str, str, str]) -> float:
    """MT stock left for one SKU: the pool for its key minus what every OTHER SKU / customer used."""
    total = pool_.get(key, {}).get("qty", 0.0)
    other = sum(u["qty"] for k, u in uses_.items() if u["key"] == key and k != me)
    return max(round(total - other, 3), 0.0)


def pool_text(pool_: dict, key: tuple) -> str:
    parts = pool_.get(key, {}).get("parts", {})
    return " · ".join(f"{fmt_num(v)} {k}" for k, v in parts.items())


def save_uses(backend, day: str, city: str, group: str, rows: list[dict], user: str) -> int:
    """rows: [{customer_sku_name, parent_sku, variety, unit, qty}]."""
    stamp = config.now_iso()
    out = [{"saved_at": stamp, "saved_by": user, "use_date": day, "city": city, "group": group, **r} for r in rows]
    if out:
        backend.append_dicts(RETURN_USE, out)
    return len(out)


def used_for(uses_: dict, city: str, group: str) -> dict[str, float]:
    """{sku key: MT stock used} for one customer group."""
    return {k[2]: u["qty"] for k, u in uses_.items() if k[0] == _k(city) and k[1] == _k(group) and u["qty"]}


def pool_summary(pool_: dict) -> list[str]:
    return [f"{k[1].title()}{' ' + k[2].title() if k[2] else ''}: {fmt_num(v['qty'])} {k[3]}"
            for k, v in sorted(pool_.items()) if v["qty"]]

