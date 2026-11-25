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
    """'2 Pcs' -> '2PC', '1 Kg' -> '1Kg', '250 gm' -> '0.250 kg'; else as given."""
    s = str(lot_size or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(pcs?|pc|piece|pieces)", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}PC"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*kgs?", s, flags=re.I)
    if m:
        return f"{float(m.group(1)):g}Kg"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|gm|gms|gram|grams)", s, flags=re.I)
    if m:
        return f"{float(m.group(1)) / 1000:.3f} kg"
    return s


def pack_kg(label: str, x: float | None) -> tuple[float | None, str]:
    """(kg in one pack, 'PC' | 'Kg') for a pack label; pieces need X (kg per piece)."""
    s = str(label or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*PC", s, flags=re.I)
    if m:
        return (float(m.group(1)) * x if x else None), "PC"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*kg", s, flags=re.I)
    if m:
        return float(m.group(1)), "Kg"
    return None, ""


def compute(box_kg, pcs_per_box, boxes, pack: str, vals: dict) -> dict:
    a, b = _f(box_kg), _f(boxes)
    pcs = _f(pcs_per_box)
    x = a / pcs if a and pcs else 0.0
    c, unit = pack_kg(pack, x or None)
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
