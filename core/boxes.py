"""Convert production quantities into boxes.

How many boxes a production line makes:
  * Count specs ("22C" = 22 pieces per box): pieces / count. A spec with two
    counts ("20C, 22C") gives a range (pieces/22 - pieces/20).
  * Kg and gram lots: total kg / kg per box.
  * Lots that already are boxes ("17.5 Kg Box"): the qty itself.

Kg per box comes from, in order:
  1. the optional Box_Conversion tab (Parent SKU, Spec, Box, Pcs per box,
     Kg per box); Spec may be a count ("22C"), the exact spec text, or blank
     for every spec of that parent;
  2. the "Box Kgs" column of Mapping Whole for that SKU;
  3. defaults for avocado counts: up to 36C a 4 kg box, higher counts a
     10 kg box (e.g. 65C = 65 pieces in a 10 kg box).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pandas as pd

BOX_TAB = "Box_Conversion"
BOX_COLUMNS = ["Parent SKU", "Spec", "Box", "Pcs per box", "Kg per box"]
AVOCADO_SMALL_MAX = 36           # counts up to this go in 4 kg boxes
_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*C\b", re.I)


def _num(v) -> float | None:
    try:
        x = float(str(v).strip().replace(",", ""))
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def kg_of(text) -> float | None:
    """'4Kg', '10 kg', '4' -> kg."""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


@dataclass
class Rule:
    parent: str
    spec: str          # '22C', exact spec text, or '' for any
    box: str
    pcs: float | None
    kg: float | None


def parse_rules(df: pd.DataFrame | None) -> list[Rule]:
    if df is None or df.empty:
        return []
    cols = {c.strip().casefold().replace(" ", "").replace("-", "").replace("_", ""): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None
    cp, cs, cb = col("parentsku", "parent"), col("spec", "count", "specsize"), col("box", "boxtype")
    cn, ck = col("pcsperbox", "piecesperbox", "pcs"), col("kgperbox", "boxkg", "boxkgs", "kg")
    out = []
    for r in df.to_dict("records"):
        parent = str(r.get(cp, "") or "").strip() if cp else ""
        if not parent:
            continue
        out.append(Rule(parent, str(r.get(cs, "") or "").strip() if cs else "",
                        str(r.get(cb, "") or "").strip() if cb else "",
                        _num(r.get(cn)) if cn else None, kg_of(r.get(ck)) if ck else None))
    return out


def read_rules() -> list[Rule]:
    from core.sheets import SheetError, get_backend
    try:
        return parse_rules(get_backend().read(BOX_TAB))
    except (SheetError, KeyError, ValueError):
        return []


def per_lot(lot: str, size: str) -> tuple[str, float]:
    """What one lot is: ('pcs', n), ('kg', x), ('box', kg-or-0)."""
    s = str(size or "").strip().casefold()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    n = sum(nums) / len(nums) if nums else 1.0          # '150-180 gm' -> 165
    if "box" in s or str(lot).casefold() == "box":
        return "box", (n if "kg" in s else 0.0)
    if "kg" in s:
        return "kg", n
    if re.search(r"\bg(m|ms|rams?)?\b", s):
        return "kg", n / 1000
    return "pcs", n


def counts_in(spec: str) -> list[float]:
    return [float(x) for x in _COUNT.findall(str(spec or ""))]


def _rule(rules: list[Rule], parent: str, key: str) -> Rule | None:
    p, k = parent.casefold(), key.casefold().replace(" ", "")
    for r in rules:
        if r.parent.casefold() == p and r.spec.casefold().replace(" ", "") == k:
            return r
    return None


def _fmt(x: float) -> str:
    return f"{x:,.1f}".rstrip("0").rstrip(".")


def convert(parent: str, spec: str, pcs: float, kg: float, boxes_given: float,
            box_kg_mapped: float | None, rules: list[Rule]) -> tuple[str, str, str]:
    """(Units, Box, Boxes) texts for one production line."""
    if box_kg_mapped is not None and (not isinstance(box_kg_mapped, (int, float)) or math.isnan(box_kg_mapped)
                                      or box_kg_mapped <= 0):
        box_kg_mapped = None
    units = []
    if pcs:
        units.append(f"{pcs:,.0f} pcs")
    if kg:
        units.append(f"{_fmt(kg)} kg")
    if boxes_given:
        units.append(f"{_fmt(boxes_given)} box")
    base = (spec or "").split(" - ")[0].strip()      # spec without the grade words
    counts = counts_in(base)
    is_avocado = parent.strip().casefold().startswith("avocado")

    def box_for(count: float | None) -> Rule:
        key = f"{count:g}C" if count else base
        r = _rule(rules, parent, key) or _rule(rules, parent, base) or _rule(rules, parent, "")
        if r:
            return Rule(r.parent, r.spec, r.box, r.pcs or count, r.kg or box_kg_mapped)
        kgb = box_kg_mapped
        if kgb is None and is_avocado and count:
            kgb = 4.0 if count <= AVOCADO_SMALL_MAX else 10.0
        return Rule(parent, key, "", count, kgb)

    found = [box_for(c) for c in counts] or [box_for(None)]
    vals = []
    for r in found:
        v = 0.0
        ok = True
        if pcs:
            if r.pcs:
                v += pcs / r.pcs
            elif r.kg and kg == 0:
                ok = False
            else:
                ok = False
        if kg:
            if r.kg:
                v += kg / r.kg
            else:
                ok = False
        v += boxes_given
        if ok and (pcs or kg or boxes_given):
            vals.append(v)
    first = found[0]
    label = first.box or (f"{_fmt(first.kg)} kg box" if first.kg else "box")
    if counts and pcs:
        label += f" ({'–'.join(_fmt(c) for c in sorted(set(counts)))} pcs)"
    if not vals:
        return " + ".join(units), ("" if not (pcs or kg) else "not mapped"), ""
    lo, hi = min(vals), max(vals)
    boxes = _fmt(lo) if abs(hi - lo) < 0.05 else f"{_fmt(lo)}–{_fmt(hi)}"
    return " + ".join(units), label, boxes


def default_rows(specs: list[tuple[str, str]]) -> list[dict]:
    """Starter rows for the Box_Conversion tab from the counts in use."""
    rows, seen = [], set()
    for parent, spec in specs:
        for c in counts_in(spec):
            key = (parent.casefold(), c)
            if key in seen:
                continue
            seen.add(key)
            kg = (4.0 if c <= AVOCADO_SMALL_MAX else 10.0) if parent.casefold().startswith("avocado") else ""
            rows.append({"Parent SKU": parent, "Spec": f"{c:g}C",
                         "Box": f"{kg:g} kg box" if kg else "box", "Pcs per box": c, "Kg per box": kg})
    return sorted(rows, key=lambda r: (r["Parent SKU"], float(str(r["Spec"])[:-1])))
