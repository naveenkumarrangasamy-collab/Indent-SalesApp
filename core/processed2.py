"""Processed, option 2 (26 Nov, trial): accounted table by table.

One *item* = everything of one fruit + variety + size + origin + brand on one table (boxes added later to the
same table join it). For an item the team types MT Ready per customer lot (1PC, 2PC, 1Kg ...), and ONCE for the
whole item: left-over MT going back, GT stock and dump. Same maths as the team's sheet:
H = A x B, I = E1*A + E2 + E3*X, J = H - I, K = sum(D1*C + D2), L = F1*A + F2 + F3*X, M = G1 + G2*X.
Sum check (K + L + M) / J must be 97-101 % (never above 101 %); efficiency = K / J.

Tab Processed_Table: every save / submit writes a full snapshot of the item (one row per customer lot + one
'table' row), tied by save_id; the newest snapshot of an item wins. status = draft | submitted."""
from __future__ import annotations

import re
import uuid

import pandas as pd

from core import config
from core import processed as pr
from core.schema import PROCESSED_TABLE

TABLE_FIELDS = ["left_box", "left_kg", "left_pcs", "gt_box", "gt_kg", "gt_pcs", "dump_kg", "dump_pcs"]
MT_FIELDS = ["mt_packs", "mt_loose_kg"]
LOW, HIGH = 0.97, pr.MAX_SUM
TRACK_TAB = "Production_Tracking_2"
TRACK_HEAD = ["Production Date", "City", "Table #", "Executive", "Parent SKU Name", "Origin", "Variety", "Brand",
              "Size Spec",
              "Purchase Lot weight in Kgs (A)", "# of Pcs in Purchase lot",
              "# Qty Moved to Grading table (Vendor Lots / Boxes) (B)", "Production prod Classification",
              "Cux Lot", "MT Ready (Dispatch) (Cux Lots) (D1)", "MT Ready (Disptach) (Loose Kg) (D2)",
              "MT Ready in Kgs (K)", "Left over MT Ready in Kgs (I)", "GT Stock in Kgs (L)", "Dump in Kgs (M)",
              "Actual NW used for Production Kgs (J = H - I)", "Category Efficiency% (K / J)",
              "Sum check (K+L+M) / J", "Status", "Operations team Comments"]


def _s(v) -> str:
    return " ".join(str(v or "").split())


def item_key(r: dict) -> str:
    """27 Nov: executive level. One item = one executive + table + fruit / variety / size / origin / brand.
    Lots saved before executives existed keep their old key (no name in front)."""
    base = "|".join(_s(r.get(c)).casefold() for c in ("table_no", "parent_sku", "variety", "size", "origin", "brand"))
    ex = _s(r.get("executive")).casefold()
    return f"{ex}|{base}" if ex else base


def lot_unit(pack: str) -> str:
    """'PC' for a piece customer lot (1PC, 2PC ...), 'Kg' for a kg lot, '' when not chosen.
    27 Nov (user): a piece lot is entered ONLY in packs, a kg lot ONLY in kg (MT Ready lines only)."""
    return pr.pack_kg(pack, 1.0)[1]


def clean_line(ln: dict) -> dict:
    """The MT line with the box that does not belong to its lot type emptied."""
    u = lot_unit(ln.get("pack", ""))
    out = dict(ln)
    if u == "PC":
        out["mt_loose_kg"] = None
    elif u == "Kg":      # typed in kg; packs saved the old way (30 x 1Kg) are carried over as kg
        kg = pr._f(ln.get("mt_loose_kg")) + pr._f(ln.get("mt_packs")) * (pr.pack_kg(ln.get("pack", ""), 1.0)[0] or 0)
        out["mt_loose_kg"] = kg or None
        out["mt_packs"] = None
    return out


def items(raw: pd.DataFrame) -> dict[str, dict]:
    """Items of one day + city: {item_key: lot-like dict (boxes summed, box kg = kg / boxes)}, by table."""
    if raw is None or raw.empty:
        return {}
    lots = raw.drop_duplicates("entry_id", keep="last").to_dict("records")
    by: dict[str, list[dict]] = {}
    for r in lots:
        by.setdefault(item_key(r), []).append(r)
    out = {}
    for key, ms in by.items():
        boxes = sum(pr._f(m.get("boxes_moved")) for m in ms)
        kg = sum(pr._f(m.get("box_kg")) * pr._f(m.get("boxes_moved")) for m in ms)
        pcs = sum(pr._f(m.get("pcs_per_box")) * pr._f(m.get("boxes_moved")) for m in ms)
        stock = list(dict.fromkeys(_s(m.get("stock_type")) for m in ms if _s(m.get("stock_type"))))
        f = ms[0]
        out[key] = {**f, "key": key, "table_no": _s(f.get("table_no")), "boxes_moved": boxes,
                    "executive": _s(f.get("executive")),
                    "last_at": max((str(m.get("saved_at") or "") for m in ms), default=""),
                    "box_kg": round(kg / boxes, 4) if boxes else pr._f(f.get("box_kg")),
                    "taken_kg": kg, "taken_pcs": pcs, "stock_type": " / ".join(stock)}
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["executive"].casefold(), kv[1]["table_no"].zfill(3),
                                                    _s(kv[1].get("parent_sku")))))


def total(item: dict, mt_lines: list[dict], tbl: dict) -> dict:
    """mt_lines: [{'pack', 'mt_packs', 'mt_loose_kg'}]; tbl: the once-per-item boxes."""
    a, pcs, b = item.get("box_kg"), item.get("pcs_per_box"), item.get("boxes_moved")
    t = pr.compute(a, pcs, b, "1Kg", tbl or {})
    per, k = [], 0.0
    for ln in mt_lines:
        ln = clean_line(ln)
        c = pr.compute(a, pcs, b, ln.get("pack", ""), ln)
        per.append(c["mt_kg"])
        k += c["mt_kg"]
    j = t["used_kg"]
    out = k + t["gt_kg_total"] + t["dump_kg_total"]
    return {"x": t["x"], "taken_kg": t["taken_kg"], "left_kg": t["left_kg_total"], "used_kg": j, "mt_kg": k,
            "mt_per_line": per, "gt_kg": t["gt_kg_total"], "dump_kg": t["dump_kg_total"], "out_kg": out,
            "to_go": j - out, "sum": out / j if j > 0 else None, "efficiency": k / j if j > 0 else None}


def line_pcs(pack: str, packs) -> float:
    """Pieces in a customer lot line: '2PC' x 50 packs = 100 pcs; kg packs = 0."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*PC", str(pack or "").strip(), flags=re.I)
    return float(m.group(1)) * pr._f(packs) if m else 0.0


def state_of(t: dict) -> str:
    """'empty' | 'low' | 'ok' | 'over' for a total."""
    if t["sum"] is None or t["out_kg"] <= 0:
        return "empty"
    if t["sum"] > HIGH + 1e-9:
        return "over"
    return "ok" if t["sum"] >= LOW else "low"


def snapshot(item: dict, mt_lines: list[dict], tbl: dict, comment: str, status: str, day: str, city: str,
             user: str) -> list[dict]:
    sid, stamp = uuid.uuid4().hex[:10], config.now_iso()
    base = {"save_id": sid, "saved_at": stamp, "saved_by": user, "production_date": day, "city": city,
            "item_key": item["key"], "table_no": item.get("table_no", ""), "parent_sku": item.get("parent_sku", ""),
            "variety": item.get("variety", ""), "size": item.get("size", ""), "origin": item.get("origin", ""),
            "brand": item.get("brand", ""), "status": status, "executive": item.get("executive", "")}
    rows = [{**base, "kind": "mt", "cux_lot": ln.get("pack", ""),
             **{f: pr._f(clean_line(ln).get(f)) for f in MT_FIELDS}}
            for ln in mt_lines if ln.get("pack")]
    rows.append({**base, "kind": "table", "cux_lot": "", **{f: pr._f((tbl or {}).get(f)) for f in TABLE_FIELDS},
                 "comment": _s(comment)})
    return rows


def save(backend, rows: list[dict]) -> int:
    if rows:
        backend.append_dicts(PROCESSED_TABLE, rows)
        from core import indents
        try:
            indents.clear_cache()
        except Exception:  # noqa: BLE001
            pass
        publish(backend)
    return len(rows)


DAY_KEY = "_day"


def close_rows(day: str, city: str, user: str, status: str = "closed") -> list[dict]:
    """The row that confirms (closes) or reopens a whole day for a city."""
    return [{"save_id": uuid.uuid4().hex[:10], "saved_at": config.now_iso(), "saved_by": user,
             "production_date": day, "city": city, "item_key": DAY_KEY, "status": status, "kind": "day"}]


def day_state(saved: pd.DataFrame, day: str, city: str) -> dict | None:
    """{'by', 'at'} when the day is confirmed for this city (the newest day row says closed), else None."""
    if saved is None or saved.empty or "kind" not in saved.columns:
        return None
    d = saved[(saved["kind"].astype(str) == "day") & (saved["production_date"].astype(str).str[:10] == day)
              & (saved["city"].astype(str) == city)]
    if d.empty:
        return None
    r = d.iloc[-1]
    return {"by": str(r.get("saved_by") or ""), "at": str(r.get("saved_at") or "")} \
        if str(r.get("status")) == "closed" else None


def read(backend=None) -> pd.DataFrame:
    from core import store_settings
    return store_settings._read(backend, PROCESSED_TABLE)


def latest(saved: pd.DataFrame, day: str | None = None, city: str | None = None) -> dict[str, dict]:
    """{(day|city|item_key): {'status', 'lines', 'tbl', 'comment', 'saved_at', 'saved_by'}} from the newest
    snapshot of each item."""
    if saved is None or saved.empty or "save_id" not in saved.columns:
        return {}
    d = saved.copy()
    d = d[d["kind"].astype(str) != "day"] if "kind" in d.columns else d
    d["production_date"] = d["production_date"].astype(str).str[:10]
    if day:
        d = d[d["production_date"] == day]
    if city:
        d = d[d["city"].astype(str) == city]
    out: dict[str, dict] = {}
    last = d.drop_duplicates(["production_date", "city", "item_key"], keep="last")
    keep = set(last["save_id"].astype(str))
    for sid, grp in d[d["save_id"].astype(str).isin(keep)].groupby(d["save_id"].astype(str), sort=False):
        recs = grp.to_dict("records")
        head = recs[-1]
        tbl_row = next((r for r in recs if str(r.get("kind")) == "table"), {})
        out[f"{head['production_date']}|{head['city']}|{head['item_key']}"] = {
            "status": str(head.get("status") or "draft"), "saved_at": str(head.get("saved_at") or ""),
            "saved_by": str(head.get("saved_by") or ""), "comment": _s(tbl_row.get("comment")),
            "lines": [{"pack": _s(r.get("cux_lot")), **{f: pr._f(r.get(f)) or None for f in MT_FIELDS}}
                      for r in recs if str(r.get("kind")) == "mt"],
            "tbl": {f: pr._f(tbl_row.get(f)) or None for f in TABLE_FIELDS}}
    return out


CAT_HEAD = ["Fruit", "Variety", "Country", "Brand", "Counts clubbed", "Boxes", "Kg taken", "Kg used (J)",
            "MT kg (K)", "GT kg (L)", "Dump kg (M)", "Category Efficiency % (K / J)", "GT Created % (L / J)",
            "Dump % (M / J)", "Status"]


def eff_band(v: float | None) -> str:
    """27 Nov (user): 'green' 90 % and above, 'amber' 80-90, 'yellow' 70-80, 'red' below 70; '' = no number."""
    if v is None:
        return ""
    return "green" if v >= 0.9 else "amber" if v >= 0.8 else "yellow" if v >= 0.7 else "red"


def category_rows(lots: pd.DataFrame, saved: pd.DataFrame, days: set[str] | None = None,
                  city: str | None = None) -> tuple[list[dict], dict]:
    """Category efficiency (27 Nov): one row per fruit + variety + country + brand, every count / table / day
    clubbed. J, K, L, M are added up over the items that have something saved (submitted or only saved);
    items not started add only to boxes and kg taken. Returns (rows, totals); the percentages are numbers
    0-1 or None."""
    if lots is None or lots.empty or "production_date" not in lots.columns:
        return [], {}
    done = latest(saved)
    d = lots.copy()
    d["production_date"] = d["production_date"].astype(str).str[:10]
    if days is not None:
        d = d[d["production_date"].isin(days)]
    if city:
        d = d[d["city"].astype(str) == city]
    groups: dict[tuple, dict] = {}
    for (day, c), grp in d.groupby(["production_date", d["city"].astype(str)], sort=False):
        for key, it in items(grp).items():
            gk = tuple(_s(it.get(x)) for x in ("parent_sku", "variety", "origin", "brand"))
            g = groups.setdefault(gk, {"sizes": [], "boxes": 0.0, "taken": 0.0, "j": 0.0, "k": 0.0, "l": 0.0,
                                       "m": 0.0, "submitted": 0, "saved": 0, "none": 0})
            if _s(it.get("size")) and _s(it.get("size")) not in g["sizes"]:
                g["sizes"].append(_s(it.get("size")))
            g["boxes"] += pr._f(it.get("boxes_moved"))
            g["taken"] += it["taken_kg"]
            s = done.get(f"{day}|{c}|{key}")
            if not s or not (s["lines"] or any(s["tbl"].values())):
                g["none"] += 1
                continue
            t = total(it, s["lines"], s["tbl"])
            g["j"] += t["used_kg"]
            g["k"] += t["mt_kg"]
            g["l"] += t["gt_kg"]
            g["m"] += t["dump_kg"]
            g["submitted" if s["status"] == "submitted" else "saved"] += 1

    def pct(n, j):
        return n / j if j > 0 else None

    def size_key(x):
        m = re.match(r"\d+(?:\.\d+)?", x)
        return (float(m.group(0)) if m else 1e9, x)
    rows, tot = [], {"j": 0.0, "k": 0.0, "l": 0.0, "m": 0.0, "submitted": 0, "saved": 0, "none": 0}
    for gk in sorted(groups, key=lambda x: tuple(y.casefold() for y in x)):
        g = groups[gk]
        for f in tot:
            tot[f] += g[f]
        bits = [f"{g[n]} {w}" for n, w in (("submitted", "submitted"), ("saved", "saved, not submitted"),
                                           ("none", "not started")) if g[n]]
        rows.append({"Fruit": gk[0], "Variety": gk[1], "Country": gk[2], "Brand": gk[3],
                     "Counts clubbed": ", ".join(sorted(g["sizes"], key=size_key)), "Boxes": g["boxes"],
                     "Kg taken": g["taken"], "Kg used (J)": g["j"], "MT kg (K)": g["k"], "GT kg (L)": g["l"],
                     "Dump kg (M)": g["m"], "Category Efficiency % (K / J)": pct(g["k"], g["j"]),
                     "GT Created % (L / J)": pct(g["l"], g["j"]), "Dump % (M / J)": pct(g["m"], g["j"]),
                     "Status": " · ".join(bits)})
    tot.update(efficiency=pct(tot["k"], tot["j"]), gt=pct(tot["l"], tot["j"]), dump=pct(tot["m"], tot["j"]))
    return rows, tot


def _r(v, n=2):
    return "" if v in ("", None) else round(float(v), n)


def track_rows(lots: pd.DataFrame, saved: pd.DataFrame) -> list[list]:
    """Tracking rows, newest date first: one row per customer lot (its MT) + one 'Table total' row
    (left-over, GT, dump); the item's efficiency and sum repeat on every row."""
    if lots is None or lots.empty or "production_date" not in lots.columns:
        return []
    done = latest(saved)
    rows = []
    d = lots.copy()
    d["production_date"] = d["production_date"].astype(str).str[:10]
    for (day, city), grp in d.groupby(["production_date", d["city"].astype(str)], sort=False):
        for key, it in items(grp).items():
            first = [day, city, f"Table {it['table_no']}", it.get("executive", ""), it.get("parent_sku", ""), it.get("origin", ""),
                     it.get("variety", ""), it.get("brand", ""), it.get("size", ""), _r(it.get("box_kg"), 3),
                     pr._f(it.get("pcs_per_box")) or "", _r(it.get("boxes_moved")), it.get("stock_type", "")]
            s = done.get(f"{day}|{city}|{key}")
            if not s:
                rows.append(first + [""] * 10 + ["Not started", ""])
                continue
            t = total(it, s["lines"], s["tbl"])
            tail = [_r(t["used_kg"]), pr.pct(t["efficiency"]), pr.pct(t["sum"]),
                    "Submitted" if s["status"] == "submitted" else "In process"]
            for ln, kg in zip(s["lines"], t["mt_per_line"]):
                rows.append(first + [ln["pack"], _r(ln.get("mt_packs")), _r(ln.get("mt_loose_kg")), _r(kg),
                                     "", "", ""] + tail + [""])
            rows.append(first + ["Table total", "", "", _r(t["mt_kg"]), _r(t["left_kg"]), _r(t["gt_kg"]),
                                 _r(t["dump_kg"])] + tail + [s["comment"]])
    rows.sort(key=lambda r: (r[0], str(r[2]).replace("Table ", "").zfill(3), str(r[4])))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def publish(backend=None) -> int:
    """Rewrite the Production_Tracking_2 tab. Never raises."""
    try:
        from core import indents
        from core import prod_actual as pa
        b = backend or indents.get_backend()
        rows = track_rows(pa.read(b), read(b))
        b.replace_tab(TRACK_TAB, [TRACK_HEAD] + rows)
        return len(rows)
    except Exception:  # noqa: BLE001
        return -1
