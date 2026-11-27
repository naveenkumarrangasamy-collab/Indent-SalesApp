"""Processed (25 Nov, trial): what came out of a lot on a grading table.

Second half of the team's BLR_ProdTracking sheet. The lot (fruit, size, box kg A, pcs per box,
boxes B) comes from Pre-Production Actual; the user types only:
  MT ready packs (D1) of a customer lot + loose kg (D2),
  MT leftover box / kg / pcs (E1 E2 E3), GT box / kg / pcs (F1 F2 F3), dump kg / pcs (G1 G2).
Everything else is worked out exactly like the sheet:
  X = A / pcs per box            C = pack kg (kg / gm lot, or pieces x X)
  H = A x B                      I = E1 x A + E2 + E3 x X        J = H - I
  K = D1 x C + D2                L = F1 x A + F2 + F3 x X        M = G1 + G2 x X
  lotting = J - (K + L + M)  (+ loss, - gain)      efficiency K/J, non MT L/J, dump M/J
"""
from __future__ import annotations

import re
import uuid

import pandas as pd

from core import config
from core.schema import PROCESSED

INPUTS = ["mt_packs", "mt_loose_kg", "left_box", "left_kg", "left_pcs", "gt_box", "gt_kg", "gt_pcs",
          "dump_kg", "dump_pcs"]


def _f(v) -> float:
    try:
        n = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
    return n if n == n else 0.0


def pack_label(lot_size: str) -> str:
    """'2 Pcs' -> '2PC', '1 Kg' -> '1Kg', '250 gm' -> '250gm'; else as given."""
    s = str(lot_size or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(pcs?|pc|piece|pieces)", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}PC"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*kgs?", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}Kg"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|gm|gms|gram|grams)", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}gm"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(box|boxes)", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}Box"
    return s


def is_box(label) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?\s*box(es)?", str(label or "").strip(), flags=re.I))


def pack_kg(label: str, x: float | None, box_kg: float | None = None) -> tuple[float | None, str]:
    """(kg in one pack, 'PC' | 'Pack' | 'Kg') for a pack label; pieces need X (kg per piece).
    'Pack' = a gram pack ('250gm', or '0.250 kg' as saved before 27 Nov): counted in packs like a piece lot.
    'Kg' = a kg lot ('1Kg'): typed in kg."""
    s = str(label or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*box(es)?", s, flags=re.I)
    if m:      # 27 Nov (user): graded fruit repacked and sold as a box of the item's own box weight; counted in boxes
        return (float(m.group(1)) * box_kg if box_kg else None), "Pack"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*PC", s, flags=re.I)
    if m:
        return (float(m.group(1)) * x if x else None), "PC"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|gm|gms)", s, flags=re.I)
    if m:
        return float(m.group(1)) / 1000, "Pack"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*kg", s, flags=re.I)
    if m:
        return float(m.group(1)), ("Kg" if float(m.group(1)) >= 1 else "Pack")
    return None, ""


GRAM_PACKS = ["100gm", "200gm", "250gm", "500gm", "750gm"]   # 27 Nov (user): customer lots of fruit sold by weight
GRAM_PARENTS = {"grapes", "blueberry", "litchi", "longan"}   # never offered piece lots (1PC, 2PC ...)
EXTRA_GRAM = {"blueberry": ["125gm"]}                        # the punnet
PIECE_GRAM = {"orange": ["250gm"]}                           # 27 Nov (user): Orange is also packed in 250 gm


def lot_choices(parent: str, piece: bool, indent_packs: list[str]) -> list[str]:
    """Customer lots offered for an item. Fruit sold by weight (no pieces per box, or grapes / blueberry /
    litchi / longan): gram packs + 1Kg, never piece lots. Others: the day's indent packs, 1-4 PC and 1Kg.
    Every item also has '1Box' = one box of its own box weight (graded and repacked as a box)."""
    from core.prod_actual import pkey
    k = pkey(parent)
    if not piece or k in GRAM_PARENTS:
        base = ([p for p in indent_packs if pack_kg(p, None)[0]] + EXTRA_GRAM.get(k, []) + GRAM_PACKS
                + ["1Kg", "1Box"])
    else:
        base = list(indent_packs) + ["1PC", "2PC", "3PC", "4PC"] + PIECE_GRAM.get(k, []) + ["1Kg", "1Box"]
    return list(dict.fromkeys(base))


def compute(box_kg, pcs_per_box, boxes, pack: str, vals: dict) -> dict:
    a, b = _f(box_kg), _f(boxes)
    pcs = _f(pcs_per_box)
    x = a / pcs if a and pcs else 0.0
    c, unit = pack_kg(pack, x or None, a or None)
    c = c or 0.0
    v = {k: _f(vals.get(k)) for k in INPUTS}
    h = a * b
    i = v["left_box"] * a + v["left_kg"] + v["left_pcs"] * x
    j = h - i
    k = v["mt_packs"] * c + v["mt_loose_kg"]
    l_ = v["gt_box"] * a + v["gt_kg"] + v["gt_pcs"] * x
    m = v["dump_kg"] + v["dump_pcs"] * x

    def pct(n):
        return n / j if j > 0 else None
    return {"x": x, "pack_kg": c, "unit": unit, "taken_kg": h, "left_kg_total": i, "used_kg": j, "mt_kg": k,
            "gt_kg_total": l_, "dump_kg_total": m, "lotting": j - (k + l_ + m),
            "efficiency": pct(k), "non_mt": pct(l_), "dump_pct": pct(m)}


def packs_for(lines: pd.DataFrame, parent: str, day: str, city: str) -> dict[str, float]:
    """{pack label: qty needed} from the day's indents for this fruit (current versions)."""
    from core.prod_actual import pkey
    if lines is None or lines.empty:
        return {}
    d = lines[(lines["delivery_date"].astype(str).str[:10] == day)
              & (lines["parent_sku"].map(pkey) == pkey(parent))]
    if city:
        d = d[d["city"].astype(str) == city]
    out: dict[str, float] = {}
    for r in d.to_dict("records"):
        lab = pack_label(r.get("lot_size") or r.get("lot"))
        if lab:
            out[lab] = out.get(lab, 0.0) + _f(r.get("qty"))
    return {k: v for k, v in sorted(out.items()) if v > 0}


def sum_check(r: dict) -> float | None:
    """(K + L + M) / J of a computed line: 100 % = every kg used is accounted; lower = a box missed / lotting."""
    j = r.get("used_kg") or 0
    return (r["mt_kg"] + r["gt_kg_total"] + r["dump_kg_total"]) / j if j > 0 else None


MAX_SUM = 1.02   # 27 Nov (user): up to 102 % is saved (and questioned later); above it saving is blocked (was 101 %)


def over_limit(t: dict) -> bool:
    """True when a group's customer lots add up to more than 102 % of what was used."""
    return t.get("sum") is not None and t["sum"] > MAX_SUM + 1e-9


def sum_colour(v: float | None) -> tuple[str, str]:
    """Target band 97-102 % green, 90-96 % amber, otherwise red (26 Nov)."""
    if v is None:
        return "#F1F5F9", "#64748B"
    if 0.97 <= v <= MAX_SUM:
        return "#EAF3DE", "#27500A"
    if 0.90 <= v < 0.97:
        return "#FAEEDA", "#633806"
    return "#FCEBEB", "#791F1F"


def _gkey(r: dict) -> tuple:
    return tuple(str(r.get(c) or "").strip().casefold()
                 for c in ("parent_sku", "variety", "size", "origin", "brand"))


def group_lots(raw: pd.DataFrame) -> dict[str, dict]:
    """Lots of one day + city clubbed by fruit + variety + size + origin + brand (26 Nov): boxes added later to the
    same spec join the group. Key = member entry ids joined by '+'. The group acts as one lot: boxes summed,
    box kg = taken kg / boxes (so A x B is the real kg taken)."""
    if raw is None or raw.empty:
        return {}
    lots = raw.drop_duplicates("entry_id", keep="last").to_dict("records")
    lots.sort(key=lambda r: (str(r.get("table_no") or "").zfill(3), str(r.get("entry_id"))))
    by: dict[tuple, list[dict]] = {}
    for r in lots:
        by.setdefault(_gkey(r), []).append(r)
    out = {}
    for members in by.values():
        boxes = sum(_f(m.get("boxes_moved")) for m in members)
        kg = sum(_f(m.get("box_kg")) * _f(m.get("boxes_moved")) for m in members)
        pcs = sum(_f(m.get("pcs_per_box")) * _f(m.get("boxes_moved")) for m in members)
        first = members[0]
        gid = "+".join(str(m["entry_id"]) for m in members)
        tables = list(dict.fromkeys(str(m.get("table_no") or "") for m in members))
        stock = list(dict.fromkeys(str(m.get("stock_type") or "") for m in members if m.get("stock_type")))
        out[gid] = {**first, "entry_id": gid, "table_no": " + ".join(t for t in tables if t),
                    "boxes_moved": boxes, "box_kg": round(kg / boxes, 4) if boxes else _f(first.get("box_kg")),
                    "stock_type": " / ".join(stock), "taken_kg": kg, "taken_pcs": pcs,
                    "members": [{"entry_id": str(m["entry_id"]), "table_no": str(m.get("table_no") or ""),
                                 "boxes": _f(m.get("boxes_moved")), "box_kg": _f(m.get("box_kg"))}
                                for m in members]}
    return out


def member_map(groups: dict[str, dict]) -> dict[str, str]:
    """entry id (or a saved group id) -> today's group id."""
    m = {}
    for gid, g in groups.items():
        m[gid] = gid
        for x in g["members"]:
            m[x["entry_id"]] = gid
    return m


def group_total(lines: list[tuple[str, dict]], g: dict) -> dict:
    """Totals of a group's customer lots: kg taken (H), leftover (sum I), used (J = H - sum I),
    MT / GT / Dump (K, L, M), sum check (K+L+M)/J and efficiency K/J."""
    h = _f(g.get("box_kg")) * _f(g.get("boxes_moved"))
    i = k = l_ = m = 0.0
    for pack, vals in lines:
        c = compute(g.get("box_kg"), g.get("pcs_per_box"), g.get("boxes_moved"), pack, vals)
        i += c["left_kg_total"]
        k += c["mt_kg"]
        l_ += c["gt_kg_total"]
        m += c["dump_kg_total"]
    j = h - i
    return {"taken_kg": h, "left_kg": i, "used_kg": j, "mt_kg": k, "gt_kg": l_, "dump_kg": m,
            "out_kg": k + l_ + m, "to_go": j - (k + l_ + m),
            "sum": (k + l_ + m) / j if j > 0 else None, "efficiency": k / j if j > 0 else None}


def row(lot: dict, pack: str, vals: dict, day: str, city: str, comment: str = "") -> dict:
    r = compute(lot.get("box_kg"), lot.get("pcs_per_box"), lot.get("boxes_moved"), pack, vals)
    return {"production_date": day, "city": city, "parent_sku": lot.get("parent_sku", ""),
            "table_no": lot.get("table_no", ""), "lot_id": lot.get("entry_id", ""), "size": lot.get("size", ""),
            "variety": lot.get("variety", ""), "box_kg": _f(lot.get("box_kg")),
            "pcs_per_box": _f(lot.get("pcs_per_box")) or "", "boxes_moved": _f(lot.get("boxes_moved")),
            "cux_lot": pack, "pack_kg": round(r["pack_kg"], 4),
            **{k: _f(vals.get(k)) for k in INPUTS},
            "taken_kg": round(r["taken_kg"], 3), "used_kg": round(r["used_kg"], 3), "mt_kg": round(r["mt_kg"], 3),
            "gt_kg_total": round(r["gt_kg_total"], 3), "dump_kg_total": round(r["dump_kg_total"], 3),
            "lotting_kg": round(r["lotting"], 3),
            "efficiency": round(r["efficiency"], 4) if r["efficiency"] is not None else "",
            "non_mt": round(r["non_mt"], 4) if r["non_mt"] is not None else "",
            "dump_pct": round(r["dump_pct"], 4) if r["dump_pct"] is not None else "",
            "comment": str(comment or "").strip()}


def save(backend, rows: list[dict], user: str) -> int:
    stamp = config.now_iso()
    out = [{"entry_id": uuid.uuid4().hex[:10], "saved_at": stamp, "saved_by": user, **r} for r in rows]
    if out:
        backend.append_dicts(PROCESSED, out)
        from core import tracking_sheet
        tracking_sheet.publish(backend)
        from core import indents
        try:
            indents.clear_cache()
        except Exception:  # noqa: BLE001
            pass
    return len(out)


def read(backend=None) -> pd.DataFrame:
    from core import store_settings
    df = store_settings._read(backend, PROCESSED)
    return df if not df.empty else pd.DataFrame(columns=["lot_id", "cux_lot"])


def latest(saved: pd.DataFrame, day: str | None = None, city: str | None = None) -> pd.DataFrame:
    """Last save per lot + customer lot (a re-entry replaces the earlier one)."""
    if saved is None or saved.empty or "production_date" not in saved.columns:
        return pd.DataFrame()
    d = saved.copy()
    d["production_date"] = d["production_date"].astype(str).str[:10]
    if day:
        d = d[d["production_date"] == day]
    if city:
        d = d[d["city"].astype(str) == city]
    return d.drop_duplicates(["lot_id", "cux_lot"], keep="last").reset_index(drop=True)


def pct(v) -> str:
    if v in ("", None):
        return ""
    n = _f(v)
    return f"{round(n * 100)}%"


def view(rows: pd.DataFrame | list[dict]) -> pd.DataFrame:
    """Sheet-like table: inputs, kg and the four end-goal columns."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    out = pd.DataFrame({
        "Fruit": df["parent_sku"], "Table": df["table_no"], "Size": df["size"], "Cux lot": df["cux_lot"],
        "Taken kg": df["taken_kg"].map(_f).round(2), "MT packs": df["mt_packs"].map(_f),
        "Used kg": df["used_kg"].map(_f).round(2), "MT kg": df["mt_kg"].map(_f).round(2),
        "GT Ready kg": df["gt_kg_total"].map(_f).round(2), "Dump kg": df["dump_kg_total"].map(_f).round(2),
        "Lotting": df["lotting_kg"].map(_f).round(2),
        "Efficiency": df["efficiency"].map(pct), "GT Ready %": df["non_mt"].map(pct), "Dump %": df["dump_pct"].map(pct),
    })
    return out
