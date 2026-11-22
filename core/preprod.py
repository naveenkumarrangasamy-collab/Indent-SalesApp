"""Pre-production actual and Batching plan (22 Nov; owners only while being tried).

Flow, per delivery date + city + customer (stores clubbed like Production by customer,
cold rooms apart):
1. Pre-production actual: the ground team picks the country of each SKU (that gives the
   counts / sizes and the box weight) and records the boxes taken out of storage at each
   count. They can come back any number of times (a "take-out round", e.g. more 90C boxes
   after grading loss). When the customer's stock is all out, they FREEZE the customer.
2. Batching plan (frozen customers only): per count, the good pieces (or kg) used from
   those boxes. The app works out what was left in the boxes (back to stock), the extra
   over the indent (allowed up to `batching_extra_pct`, default 10 %) and a status.

Tabs (append-only, created on first save): Preprod_Actual, Preprod_Freeze, Batching_Plan.
Country / spec / box kg come from the Batching_Master tab; until it has the SKU, from the
New tab (Spec-Origin + Spec-Size) and Mapping Whole (Spec-Origin, Spec-Size, Box Kgs).
The pure functions below take DataFrames so they can be tested without the sheet.
"""
from __future__ import annotations

import math
import re
import uuid

import pandas as pd

from core import config
from core.lots import lot_size
from core.models import fmt_num, to_number
from core.schema import BATCHING_MASTER, BATCHING_PLAN, PREPROD_ACTUAL, PREPROD_FREEZE

ANY = "Any"
REASONS = ["First take-out", "More for grading loss", "Short in first take-out", "Other"]
FROZEN, OPEN, NOT_STARTED = "Frozen", "Open", "Not started"


def _c(v) -> str:
    return " ".join(str(v or "").split())


def _k(v) -> str:
    return _c(v).casefold()


def extra_limit_pct() -> float:
    """How much more than the indent may be batched (secret `batching_extra_pct`, default 10)."""
    try:
        return float(config.get("batching_extra_pct", 10))
    except (TypeError, ValueError):
        return 10.0


def max_allowed(need: float, pct: float | None = None) -> float:
    pct = extra_limit_pct() if pct is None else pct
    return math.floor(need * (1 + pct / 100) + 1e-9)


# ------------------------------------------------------------------ spec / units

def parse_spec(spec: str) -> list[str]:
    """'90, 100, 110' / '22C, 24C' / '90C | 100C' -> ['90', '100', '110'] (counts kept as plain
    numbers); sizes that are not counts stay as written: '1C, 2C, 65mm' -> ['1C', '2C', '65mm']."""
    out = []
    for part in re.split(r"[,|;/]+", str(spec or "")):
        p = _c(part)
        if not p or p == "-":
            continue
        m = re.fullmatch(r"(\d{2,3})\s*[cC]?", p)
        p = m.group(1) if m and int(m.group(1)) >= 10 else p
        if p.casefold() not in {x.casefold() for x in out}:
            out.append(p)
    return out


def is_count(spec_item: str) -> bool:
    return bool(re.fullmatch(r"\d{2,3}", str(spec_item))) and int(spec_item) >= 10


def spec_label(spec_item: str) -> str:
    return f"{spec_item}C" if is_count(spec_item) else str(spec_item)


def _box_kg(v) -> float | None:
    n = to_number(re.sub(r"[^\d.]", "", str(v or "")) or 0)
    return n or None


def need_unit(sku_name: str, lot: str) -> tuple[str, float]:
    """What the indent qty is counted in for batching: ('pcs', pieces per pack), ('kg', kg per
    pack) or ('packs', 1) when neither is known (gram packs, boxes)."""
    from core.production_calc import _kg_per_lot, _pcs_per_lot
    size = lot_size(sku_name) or _c(lot)
    pcs = _pcs_per_lot(size)
    if pcs:
        return "pcs", float(pcs)
    if str(lot or "").strip().casefold() == "pcs" and not size.strip():
        return "pcs", 1.0
    kg = _kg_per_lot(size, lot)
    if kg:
        return "kg", float(kg)
    return "packs", 1.0


def per_box(spec_item: str, unit: str, box_kg: float | None) -> float | None:
    """What one box at this count / size holds, in the line's unit (None = not known)."""
    if unit == "pcs":
        return float(spec_item) if is_count(spec_item) else None
    if unit == "kg":
        return box_kg
    return None


# ------------------------------------------------------------------ demand

def demand(lines: pd.DataFrame) -> pd.DataFrame:
    """Indent lines (current version, one date) -> one row per city + customer group + SKU name:
    city, group, customer, customer_sku_name, parent_sku, variety, qty, unit, per, need, indents."""
    from core.production_calc import customer_group
    cols = ["city", "group", "customer", "customer_sku_name", "parent_sku", "variety", "qty", "unit", "per",
            "need", "indents"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    df = lines.copy()
    df["qty"] = df["qty"].map(to_number)
    df = df[df["qty"] > 0]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["group"] = [customer_group(c, s) for c, s in zip(df["customer"], df["store"])]
    df["_name"] = df["customer_sku_name"].map(_c)
    df["_key"] = df["_name"].str.casefold()
    rows = []
    for (city, group, _), g in df.groupby(["city", "group", "_key"], sort=False):
        first = g.iloc[0]
        unit, per = need_unit(first["_name"], first.get("lot", ""))
        qty = float(g["qty"].sum())
        rows.append({"city": _c(city), "group": group, "customer": _c(first["customer"]),
                     "customer_sku_name": first["_name"], "parent_sku": _c(first.get("parent_sku")),
                     "variety": _c(first.get("variety")), "qty": qty, "unit": unit, "per": per,
                     "need": round(qty * per, 3), "indents": ", ".join(sorted(set(g["indent_id"])))})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["city", "group", "parent_sku", "customer_sku_name"],
                           key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)


# ------------------------------------------------------------------ countries

def country_options(masters, bmaster: pd.DataFrame | None, city: str, customer: str, sku_name: str,
                    parent: str) -> dict[str, dict]:
    """{country: {'spec': [...], 'unit': 'Box'|'Tray', 'box_kg': float|None, 'source': str}}.
    1) Batching_Master rows for this SKU (city or blank city), 2) New tab rows (one per origin),
    3) Mapping Whole rows. Box kg also from Mapping Whole when the others have none."""
    trays = {p.casefold() for p in config.tray_parents()}
    unit_default = "Tray" if _k(parent) in trays else "Box"
    out: dict[str, dict] = {}

    def add(country, spec, unit, kg, source):
        country = _c(country) or ANY
        items = parse_spec(spec)
        if not items and country in out:
            return
        cur = out.get(country)
        if cur and cur["spec"]:
            if not cur["box_kg"] and kg:
                cur["box_kg"] = kg
            return
        out[country] = {"spec": items, "unit": _c(unit).title() or unit_default, "box_kg": kg, "source": source}

    def match(df, name_col="Customer SKU Name"):
        if df is None or df.empty or name_col not in df.columns:
            return pd.DataFrame()
        hit = df[(df["Customer"].map(_k) == _k(customer)) & (df[name_col].map(_k) == _k(sku_name))]
        if "City" in hit.columns and not hit.empty:
            exact = hit[hit["City"].map(_k) == _k(city)]
            hit = exact if not exact.empty else hit[hit["City"].map(_k) == ""]
        return hit

    mw_kg = {}
    sku = getattr(masters, "sku", None) if masters is not None else None
    mw = match(sku)
    for r in mw.to_dict("records") if not mw.empty else []:
        kg = _box_kg(r.get("Box-Kg"))
        if kg:
            mw_kg[_k(r.get("Spec-Origin")) or _k(ANY)] = kg

    bm = match(bmaster)
    for r in bm.to_dict("records") if not bm.empty else []:
        add(r.get("Country"), r.get("Spec"), r.get("Unit"), _box_kg(r.get("Box Kg"))
            or mw_kg.get(_k(r.get("Country"))), "Batching_Master")
    if not out:
        nb = match(getattr(masters, "prod_base", None) if masters is not None else None)
        for r in nb.to_dict("records") if not nb.empty else []:
            for origin in [o for o in re.split(r"[,/]+", str(r.get("Spec-Origin") or "")) if _c(o)] or [ANY]:
                add(origin, r.get("Spec-Size"), "", mw_kg.get(_k(origin)), "New tab")
    if not out:
        for r in mw.to_dict("records") if not mw.empty else []:
            add(r.get("Spec-Origin"), r.get("Spec-Size"), "", _box_kg(r.get("Box-Kg")), "Mapping Whole")
    if out and not any(v["box_kg"] for v in out.values()) and mw_kg:
        kg = next(iter(mw_kg.values()))
        for v in out.values():
            v["box_kg"] = kg
    return out


def suggestion(need: float, unit: str, opt: dict) -> str:
    """'90C: 6 Box | 100C: 5 Box' (all at one count), or '5 Box of 15 kg' for kg lines."""
    word = opt.get("unit") or "Box"
    if unit == "kg" and opt.get("box_kg"):
        return f"{math.ceil(need / opt['box_kg'] - 1e-9)} {word} of {fmt_num(opt['box_kg'])} kg"
    parts = [f"{spec_label(s)}: {math.ceil(need / float(s) - 1e-9)} {word}"
             for s in opt.get("spec", []) if unit == "pcs" and is_count(s)]
    return " | ".join(parts) or ", ".join(spec_label(s) for s in opt.get("spec", [])) or "-"


# ------------------------------------------------------------------ saved data

def _norm(df: pd.DataFrame | None, cols: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df


def _scope(df: pd.DataFrame, day: str, city: str, group: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    m = (df["delivery_date"].map(_c) == _c(day)) & (df["city"].map(_k) == _k(city))
    if group is not None:
        m &= df["group"].map(_k) == _k(group)
    return df[m]


def taken(actual: pd.DataFrame | None, day: str, city: str, group: str) -> dict[str, dict]:
    """{sku key: {'country': str, 'boxes': {spec: n}}} summed over every take-out round."""
    df = _scope(_norm(actual, ["delivery_date", "city", "group", "customer_sku_name", "country", "spec",
                               "boxes"]), day, city, group)
    out: dict[str, dict] = {}
    for r in df.to_dict("records"):
        n = to_number(r.get("boxes"))
        if not n:
            continue
        d = out.setdefault(_k(r["customer_sku_name"]), {"country": _c(r.get("country")), "boxes": {}})
        if not d["country"]:
            d["country"] = _c(r.get("country"))
        s = _c(r.get("spec"))
        d["boxes"][s] = d["boxes"].get(s, 0) + n
    return out


def rounds(actual: pd.DataFrame | None, day: str, city: str, group: str) -> pd.DataFrame:
    """Take-out history: one row per round (time, by, reason, what)."""
    df = _scope(_norm(actual, ["round_id", "saved_at", "saved_by", "delivery_date", "city", "group",
                               "customer_sku_name", "spec", "boxes", "reason"]), day, city, group)
    cols = ["Round", "Saved", "By", "Reason", "Boxes taken out"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = []
    for i, (_, g) in enumerate(df.groupby("round_id", sort=False), start=1):
        what = {}
        for r in g.to_dict("records"):
            what.setdefault(_c(r["customer_sku_name"]), []).append(
                f"{spec_label(_c(r['spec']))} {fmt_num(to_number(r['boxes']))}")
        first = g.iloc[0]
        out.append({"Round": i, "Saved": _c(first["saved_at"])[11:16] or _c(first["saved_at"]),
                    "By": _c(first["saved_by"]), "Reason": _c(first["reason"]),
                    "Boxes taken out": " · ".join(f"{k}: {', '.join(v)}" for k, v in what.items())})
    return pd.DataFrame(out, columns=cols)


def freeze_state(freeze: pd.DataFrame | None, day: str, city: str, group: str) -> tuple[bool, str, str]:
    """(frozen, at, by) - the last freeze / unfreeze row wins."""
    df = _scope(_norm(freeze, ["delivery_date", "city", "group", "action", "at", "by"]), day, city, group)
    if df.empty:
        return False, "", ""
    last = df.iloc[-1]
    return _k(last["action"]) == "freeze", _c(last["at"]), _c(last["by"])


def used_saved(plan: pd.DataFrame | None, day: str, city: str, group: str) -> dict[tuple[str, str], float]:
    """{(sku key, spec): used} - the last saved value per SKU + spec."""
    df = _scope(_norm(plan, ["delivery_date", "city", "group", "customer_sku_name", "spec", "used"]),
                day, city, group)
    out = {}
    for r in df.to_dict("records"):
        out[(_k(r["customer_sku_name"]), _c(r["spec"]))] = to_number(r.get("used"))
    return out


# ------------------------------------------------------------------ statuses

def actual_status(need: float, hold: float | None, boxes: float) -> str:
    if not boxes:
        return NOT_STARTED
    if hold is None:
        return "Taken"            # holding not known (no count / box kg): just taken
    return "Enough" if hold + 1e-9 >= need else "Not enough"


def batch_status(need: float, used: float, any_entry: bool, pct: float | None = None) -> str:
    if not any_entry:
        return "Pending"
    if used > max_allowed(need, pct) + 1e-9:
        return "Over limit"
    return "Covered" if used + 1e-9 >= need else "Short"


# ------------------------------------------------------------------ writing

def _read(tab: str) -> pd.DataFrame:
    from core import store_settings
    return store_settings._read(None, tab)


def read_all() -> dict[str, pd.DataFrame]:
    return {t: _read(t) for t in (BATCHING_MASTER, PREPROD_ACTUAL, PREPROD_FREEZE, BATCHING_PLAN)}


def save_round(backend, day: str, city: str, group: str, entries: list[dict], reason: str, user: str) -> int:
    """entries: [{customer_sku_name, parent_sku, country, spec, boxes}] (boxes > 0 only are saved)."""
    rid, stamp = uuid.uuid4().hex[:10], config.now_iso()
    rows = [{"round_id": rid, "saved_at": stamp, "saved_by": user, "delivery_date": day, "city": city,
             "group": group, "customer_sku_name": e["customer_sku_name"], "parent_sku": e.get("parent_sku", ""),
             "country": e.get("country", ""), "spec": e["spec"], "boxes": e["boxes"], "reason": reason}
            for e in entries if to_number(e.get("boxes")) > 0]
    if rows:
        backend.append_dicts(PREPROD_ACTUAL, rows)
        _clear()
    return len(rows)


def set_frozen(backend, day: str, city: str, group: str, frozen: bool, user: str) -> None:
    backend.append_dicts(PREPROD_FREEZE, [{"delivery_date": day, "city": city, "group": group,
                                           "action": "freeze" if frozen else "unfreeze",
                                           "at": config.now_iso(), "by": user}])
    _clear()


def save_plan(backend, day: str, city: str, group: str, rows: list[dict], user: str) -> int:
    """rows: [{customer_sku_name, country, spec, boxes, used, unit}]."""
    stamp = config.now_iso()
    out = [{"saved_at": stamp, "saved_by": user, "delivery_date": day, "city": city, "group": group, **r}
           for r in rows]
    if out:
        backend.append_dicts(BATCHING_PLAN, out)
        _clear()
    return len(out)


def _clear() -> None:
    from core import indents
    try:
        indents.clear_cache()
    except Exception:  # noqa: BLE001
        pass
