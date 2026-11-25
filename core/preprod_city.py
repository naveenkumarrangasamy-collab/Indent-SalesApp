"""Pre-production actual, city level (24 Nov evening, user-approved; owners only, trial).

Replaces the per-customer take-out. For one delivery date + city every customer is clubbed:
- one row per fruit (Parent SKU), Apple also per variety, and per unit (pcs / kg / punnets / packs),
  so a suggestion is always in the unit the orders are in;
- every Blueberry is punnets (125 g, 1 Box, Pack... all the same), 12 a tray;
- need = the PO qty of the line when its indent has a PO (an item not on the PO = 0, a PO-only item
  counts), else the indent qty; x pieces / kg per pack;
- "Asked" = the need split by the counts / sizes the customers asked for (their spec), so a customer
  that wants something different is not hidden by the clubbing; notes flag lines without a spec and
  POs much lower than the indent.
The team picks an option "Country · Grade · Count · Box kg" (New Mapping Parent tab) and types the
boxes; rounds add up (tab Preprod_Actual, group = CITY_GROUP). Pure functions, tested."""
from __future__ import annotations

import math
import re

import pandas as pd

from core import config
from core.models import fmt_num, to_number
from core.preprod import _c, _k, is_count, need_unit, parse_spec

CITY_GROUP = "All customers"
CUSTOMER_NOTES = "Customer_Notes"     # optional tab: City, Customer, Parent SKU, Note (blank City = every city)
DEFAULT_NOTES = [{"City": "", "Customer": "More", "Parent SKU": "Avocado", "Note": "green colour"}]   # user 25 Nov
NO_SPEC = "spec not set"
SIZE_PARENTS = {"kiwi", "grapes", "blueberry", "cherry", "cherries"}   # plain numbers are mm, not counts


def _per_tray() -> float:
    return float(next(iter(config.punnets_per_tray().values()), 12))


def is_berry(parent: str) -> bool:
    return _k(parent) in config.punnets_per_tray()


def club_key(parent: str, variety: str, unit: str) -> str:
    return f"{_c(parent)}|{_c(variety)}|{unit}"


def spec_items(spec: str, parent: str) -> list[str]:
    """'18C, 20C' -> ['18', '20'] (counts); Kiwi '33, 36' -> ['33mm', '36mm']; junk -> []."""
    s = _c(spec)
    if not s or s == "-" or s.casefold().startswith(("not in new", "mapping not", "spec not", "to fill")):
        return []
    items = parse_spec(s)
    if _k(parent) in SIZE_PARENTS:
        items = [f"{x}mm" if re.fullmatch(r"\d{2,3}", x) else x.replace(" ", "") for x in items]
    return items


def spec_text(items: list[str]) -> str:
    if not items:
        return NO_SPEC
    counts = [x for x in items if is_count(x)]
    if len(counts) == len(items) and len(items) > 1:
        lo, hi = min(map(int, counts)), max(map(int, counts))
        return f"{lo}–{hi}C"
    if len(counts) == len(items):
        return f"{items[0]}C"
    return ", ".join(items)


def _guess_parent(name: str, parents: list[str]) -> str:
    n = _k(name)
    for p in sorted(parents, key=len, reverse=True):
        if p and _k(p) in n:
            return p
    return ""


def demand(view: pd.DataFrame, ask_variety) -> list[dict]:
    """Batching view with PO columns (production_calc.with_po) for ONE date + city -> clubbed rows:
    {key, parent, variety, unit, need, skus, customers, asked {spec text: need}, notes, lines}."""
    if view is None or view.empty:
        return []
    parents = [p for p in view["Parent SKU"].map(_c).unique() if p]
    rows: dict[str, dict] = {}
    for r in view.to_dict("records"):
        name, parent = _c(r["Customer SKU Name"]), _c(r.get("Parent SKU"))
        parent = parent or _guess_parent(name, parents) or "Not mapped"
        status = _c(r.get("Status"))
        ind = to_number(r.get("Indent qty")) or 0.0
        po = r.get("PO qty")
        po = None if po is None or po == "" or (isinstance(po, float) and pd.isna(po)) else to_number(po)
        if status in ("No PO yet", ""):
            lots = ind
        else:
            lots = po or 0.0                     # not on the PO = not wanted; PO-only item = its PO qty
        if lots <= 0:
            continue
        unit, per = need_unit(name, r.get("Lot", ""), parent)
        variety = _c(r.get("Variety")) if ask_variety(parent) else ""
        key = club_key(parent, variety, unit)
        g = rows.setdefault(key, {"key": key, "parent": parent, "variety": variety, "unit": unit, "need": 0.0,
                                  "skus": set(), "customers": set(), "asked": {}, "notes": [], "lines": 0,
                                  "by_customer": {}})
        need = lots * per
        g["need"] += need
        g["skus"].add(_k(name))
        g["customers"].add(_c(r["Customer"]))
        g["by_customer"][_c(r["Customer"])] = g["by_customer"].get(_c(r["Customer"]), 0.0) + need
        g["lines"] += 1
        st = spec_text(spec_items(r.get("Spec", ""), parent))
        g["asked"][st] = g["asked"].get(st, 0.0) + need
        if po is not None and ind and po < ind * 0.8 and status != "Not on PO":
            g["notes"].append(f"{_c(r['Customer'])} {name}: PO {fmt_num(po)} vs indent {fmt_num(ind)} "
                              "(need from the PO)")
    out = []
    for g in rows.values():
        g["skus"], g["customers"] = len(g["skus"]), sorted(g["customers"])
        g["need"] = round(g["need"], 3)
        out.append(g)
    return sorted(out, key=lambda g: (_k(g["parent"]), _k(g["variety"]), g["unit"]))


def customer_notes(rows: list[dict], tab: pd.DataFrame | None, city: str) -> dict[str, list[str]]:
    """{club key: ['More: green colour', ...]}: what one customer asks differently for that fruit
    (25 Nov: More wants green avocados). Built-in DEFAULT_NOTES + the optional Customer_Notes tab."""
    reqs = list(DEFAULT_NOTES)
    if tab is not None and not tab.empty:
        cols = {_k(c).replace(" ", "").replace("_", ""): c for c in tab.columns}
        get = lambda r, n: _c(r.get(cols.get(n, ""), ""))
        reqs += [{"City": get(r, "city"), "Customer": get(r, "customer"), "Parent SKU": get(r, "parentsku"),
                  "Note": get(r, "note")} for r in tab.to_dict("records")]
    out: dict[str, list[str]] = {}
    for g in rows:
        for q in reqs:
            if not q["Note"] or _k(q["Parent SKU"]) != _k(g["parent"]):
                continue
            if q["City"] and _k(q["City"]) not in _k(city):
                continue
            for cust in g["customers"]:
                if _k(cust).startswith(_k(q["Customer"])):
                    t = f"{cust}: {q['Note']}"
                    if t not in out.setdefault(g["key"], []):
                        out[g["key"]].append(t)
    return out


# ------------------------------------------------------------------ options (New Mapping Parent tab)

def options(parent_df: pd.DataFrame | None, parent: str, variety: str = "") -> list[dict]:
    """Every 'Country · Grade · Count · Box kg' for this fruit (Apple: only grades of its variety).
    [{label, country, grade, count, box_kg}]. A row without a spec gives one option without a count."""
    from core.mapping_sheet import _variety_ok
    if parent_df is None or parent_df.empty:
        return []
    p = parent_df[parent_df["parent"].map(_k) == _k(parent)]
    if variety:
        keep = p[[_variety_ok(g, variety, parent) for g in p["grade"]]]
        p = keep if not keep.empty else p
    out, seen = [], set()
    for r in p.to_dict("records"):
        grade = _c(r.get("grade"))
        show_grade = grade and _k(grade) != _k(parent)
        kg = r.get("box_kg")
        kg = float(kg) if kg is not None and not pd.isna(kg) and float(kg) > 0 else None
        items = spec_items(r.get("spec", ""), parent) or [""]
        for it in items:
            label = " · ".join(x for x in (_c(r.get("country")), grade if show_grade else "",
                                           f"{it}C" if is_count(it) else it,
                                           f"{fmt_num(kg)} kg" if kg else "") if x)
            if label and label not in seen:
                seen.add(label)
                out.append({"label": label, "country": _c(r.get("country")), "grade": grade, "count": it,
                            "box_kg": kg})
    return out


def holds(opt: dict | None, unit: str, parent: str) -> float | None:
    """What one box of this option holds in the row's unit (None = not known)."""
    if unit == "punnets" or is_berry(parent):
        return _per_tray()
    if not opt:
        return None
    if unit == "pcs" and is_count(opt.get("count", "")):
        return float(opt["count"])
    if unit == "kg" and opt.get("box_kg"):
        return float(opt["box_kg"])
    return None


def box_word(parent: str) -> str:
    return "Tray" if _k(parent) in {p.casefold() for p in config.tray_parents()} or is_berry(parent) else "Box"


def suggest(row: dict, opts: list[dict]) -> tuple[str, int, int]:
    """('≈ 17–18 Box', lo, hi) from the asked counts; kg rows by the usual box kg; punnets ÷ 12."""
    word, need, unit = box_word(row["parent"]), row["need"], row["unit"]
    if unit == "punnets" or is_berry(row["parent"]):
        n = math.ceil(need / _per_tray() - 1e-9)
        return f"{n} Tray", n, n
    if unit == "kg":
        kgs = sorted({o["box_kg"] for o in opts if o.get("box_kg")})
        if not kgs:
            return "by kg (box kg not known)", 0, 0
        lo, hi = math.ceil(need / kgs[-1] - 1e-9), math.ceil(need / kgs[0] - 1e-9)
    elif unit == "pcs":
        lo = hi = 0
        known = False
        for st, n in row["asked"].items():
            counts = [int(x) for x in re.findall(r"\d{2,3}", st)] if st.endswith("C") else []
            if not counts:
                continue
            known = True
            lo += math.ceil(n / max(counts) - 1e-9)
            hi += math.ceil(n / min(counts) - 1e-9)
        if not known:
            return "-", 0, 0
    else:
        return "-", 0, 0
    txt = f"≈ {lo} {word}" if lo == hi else f"≈ {lo}–{hi} {word}"
    left = sum(n for st, n in row["asked"].items() if not st.endswith("C")) if unit == "pcs" else 0
    if left:
        txt += f" + {fmt_num(round(left))} pcs without a count"
    return txt, lo, hi


# ------------------------------------------------------------------ saved take-outs

def taken(actual: pd.DataFrame | None, day: str, city: str) -> dict[str, dict[str, float]]:
    """{club key: {option label: boxes}} summed over every round (group = CITY_GROUP)."""
    out: dict[str, dict[str, float]] = {}
    if actual is None or actual.empty:
        return out
    df = actual.copy()
    for c in ("delivery_date", "city", "group", "customer_sku_name", "country", "boxes"):
        if c not in df.columns:
            df[c] = ""
    df = df[(df["delivery_date"].map(_c) == _c(day)) & (df["city"].map(_k) == _k(city))
            & (df["group"].map(_k) == _k(CITY_GROUP))]
    for r in df.to_dict("records"):
        n = to_number(r.get("boxes"))
        if n:
            d = out.setdefault(_c(r["customer_sku_name"]), {})
            d[_c(r["country"])] = d.get(_c(r["country"]), 0.0) + n
    return out


def in_boxes(took: dict[str, float], opts: list[dict], unit: str, parent: str) -> tuple[float, bool]:
    """(fruit in the boxes taken, all known?)."""
    by = {o["label"]: o for o in opts}
    total, known = 0.0, True
    for label, n in took.items():
        h = holds(by.get(label) or _from_label(label), unit, parent)
        if h is None:
            known = False
        else:
            total += n * h
    return total, known


def _from_label(label: str) -> dict:
    """An option no longer in the master: read the count / box kg back from its label."""
    count = next((m.group(1) for m in re.finditer(r"\b(\d{2,3})C\b", label)), "")
    kg = re.search(r"(\d+(?:\.\d+)?) kg", label)
    return {"label": label, "count": count, "box_kg": float(kg.group(1)) if kg else None}


def status(need: float, total: float, known: bool, any_taken: bool) -> str:
    if not any_taken:
        return "Not started"
    if not known:
        return "Taken"
    return "Enough" if total + 1e-9 >= need else "Short"
