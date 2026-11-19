"""Shared by the Hourly tracker page and the hourly e-mail (19 Nov):
- the half-hour points of a delivery day (8:00, 8:30 ... 2:00 PM, + Now);
- SKU-level changes between two moments (only items whose qty changed);
- Indent vs PO rows per store and item."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from core import config, hourly, indents
from core.models import fmt_num, fmt_q

STEP_MIN = 30


def label(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")          # 8:00 AM, 8:30 AM, 1:30 PM


def points(day: str, now: datetime | None = None) -> list[tuple[str, datetime | None]]:
    """(label, moment) every 30 min from the first to the last mail hour; None = still to come.
    Plus 'Now' while the day is still open."""
    first, last = hourly.hours()
    d = date.fromisoformat(day)
    now = now or config.now_ist()
    t = datetime.combine(d, time(first, 0), tzinfo=config.IST)
    end = datetime.combine(d, time(last, 0), tzinfo=config.IST)
    out = []
    while t <= end:
        out.append((label(t), t if t <= now else None))
        t += timedelta(minutes=STEP_MIN)
    if now < end:
        out.append(("Now", now))
    return out


def _qty(lines: pd.DataFrame, when: datetime, day: str) -> pd.Series:
    from core import reports
    st_ = reports.state_at(lines, when)
    if st_ is None or st_.empty:
        return pd.Series(dtype=float)
    st_ = st_[st_["delivery_date"].astype(str) == str(day)]
    return st_.groupby(["customer", "store", "customer_sku_name"])["qty"].sum()


def sku_changes(lines: pd.DataFrame, day: str, since: datetime, upto: datetime) -> pd.DataFrame:
    """Items whose qty changed between `since` and `upto` (new and removed items too)."""
    cols = ["Customer", "Store", "Customer SKU Name", "Before", "Now", "Change"]
    if lines is None or lines.empty:
        return pd.DataFrame(columns=cols)
    a, b = _qty(lines, since, day), _qty(lines, upto, day)
    keys = sorted(set(a.index) | set(b.index), key=lambda k: tuple(str(x).casefold() for x in k))
    rows = []
    for k in keys:
        x, y = float(a.get(k, 0) or 0), float(b.get(k, 0) or 0)
        if x == y:
            continue
        rows.append({"Customer": k[0], "Store": k[1], "Customer SKU Name": k[2],
                     "Before": fmt_num(x) if k in a.index else "new", "Now": fmt_num(y) if k in b.index else "removed",
                     "Change": ("+" if y > x else "") + fmt_num(y - x)})
    return pd.DataFrame(rows, columns=cols)


def po_rows(lines: pd.DataFrame, po: pd.DataFrame, ids) -> pd.DataFrame:
    """Indent vs PO per store and item, for the given indents."""
    out = []
    for iid in sorted(ids):
        cur = indents.snapshot(lines, iid)
        if cur is None or cur.status == "Cancelled":
            continue
        info = indents.po_info(po, iid)
        h = cur.header
        if info["pos"] == 0:
            state_ = "No PO yet"
        elif info["qty"] is None:
            state_ = "PO without item qty"
        elif indents.is_multi_po(h.customer) and not info["ended"]:
            state_ = f"{info['pos']} PO(s), more coming"
        else:
            state_ = ""
        rows = indents.po_vs_indent(cur.lines, info) if info["qty"] is not None else [
            {"customer_sku_name": x.customer_sku_name, "indent_qty": float(x.qty), "po_qty": None,
             "diff": None, "ok": None} for x in cur.lines]
        for r in rows:
            out.append({"Customer": h.customer, "Store": h.store, "Indent": iid,
                        "Customer SKU Name": r["customer_sku_name"],
                        "Indent qty": fmt_q(r["indent_qty"]), "PO qty": fmt_q(r["po_qty"]),
                        "Difference": "" if r["diff"] is None or r["ok"] else
                        ("+" if r["diff"] > 0 else "") + fmt_num(r["diff"]),
                        "Status": state_ or ("Match" if r["ok"] else
                                             "Not on PO" if r["po_qty"] is None else
                                             "Not on indent" if r["indent_qty"] is None else "Differs")})
    return pd.DataFrame(out, columns=["Customer", "Store", "Indent", "Customer SKU Name", "Indent qty",
                                      "PO qty", "Difference", "Status"])


BAD = ("Differs", "Not on PO", "Not on indent")


# --------------------------------------------------------------- tracker grid (19 Nov, v3)

def _key(s) -> str:
    return " ".join(str(s or "").split()).casefold()


def grid(lines: pd.DataFrame, po: pd.DataFrame | None, day: str,
         pts: list[tuple[str, datetime | None]]) -> list[dict]:
    """The Hourly tracker, one block per indent of `day` (customer A-Z, then store):
    every item, its qty at each half-hour point, and how it changed.

    Each cell is (qty text, change text, kind):
    - kind 'up' / 'down' with change '(+46)' / '(-50)': the qty changed in that half hour
      (vs the previous point; an item entered and changed in the same half hour is compared
      with what was first entered; an item added to an existing indent shows '(+qty)');
    - kind 'swing' with '(±)': changed and back inside the half hour;
    - kind 'yellow' / 'red': no change now, but it went up / down earlier (kept until the PO);
    - kind '' plain; '·' text = not entered yet.
    From the PO (status Frozen) on, cells are plain. Last column: PO vs indent."""
    pts = [(lbl, t) for lbl, t in pts if t is not None]
    if lines is None or lines.empty or not pts:
        return []
    df = lines[lines["delivery_date"].astype(str) == str(day)].copy()
    if df.empty:
        return []
    df["_ts"] = pd.to_datetime(df["submitted_at"], errors="coerce", utc=True)
    po_map = {}
    if po is not None and not po.empty:
        po_rows_ = po_rows(lines, po, set(df["indent_id"]))
        po_map = {(r["Indent"], _key(r["Customer SKU Name"])): r for r in po_rows_.to_dict("records")}
    blocks = []
    for iid, part in df.groupby("indent_id"):
        part = part.sort_values(["version"])
        vers = [(int(v), g) for v, g in part.groupby("version")]
        last = vers[-1][1].iloc[0]
        if str(last["status"]) == "Cancelled":
            continue
        frozen_at = next((g["_ts"].iloc[0] for _, g in vers if str(g["status"].iloc[0]) == "Frozen"), None)
        names, seen = [], set()
        for _, g in vers:
            for n in g["customer_sku_name"]:
                if _key(n) not in seen:
                    seen.add(_key(n))
                    names.append(n)
        first_ts = vers[0][1]["_ts"].iloc[0]
        qty_in = {v: {_key(n): float(q) for n, q in zip(g["customer_sku_name"], g["qty"])} for v, g in vers}
        ts_of = {v: g["_ts"].iloc[0] for v, g in vers}

        def ver_at(t, _vers=vers, _ts=ts_of):
            T = pd.Timestamp(t).tz_convert("UTC")
            best = None
            for v, _ in _vers:
                if _ts[v] <= T:
                    best = v
            return best

        rows, changes = [], 0
        for n in names:
            k = _key(n)
            cells, prev_q, prev_t, mood = [], None, None, ""
            for lbl, t in pts:
                v = ver_at(t)
                q = qty_in[v].get(k) if v is not None else None
                if q is None:
                    cells.append(("·", "", ""))
                    prev_q, prev_t = None, t
                    continue
                T = pd.Timestamp(t).tz_convert("UTC")
                after_po = frozen_at is not None and frozen_at <= T
                lo = pd.Timestamp(prev_t).tz_convert("UTC") if prev_t is not None else None
                inside = [qty_in[vv].get(k) for vv, _ in vers
                          if ts_of[vv] <= T and (lo is None or ts_of[vv] > lo)]
                inside = [x for x in inside if x is not None]
                if prev_q is None:
                    # first appearance: compare with what was first entered; an item added to an
                    # existing indent counts from 0; nothing is shown at the very first point
                    first_v = next(vv for vv, _ in vers if k in qty_in[vv])
                    base = qty_in[first_v][k] if first_v == vers[0][0] else 0.0
                    d = 0.0 if lo is None else q - base
                else:
                    d = q - prev_q
                if after_po:
                    cells.append((fmt_num(q), "", ""))
                elif d:
                    changes += 1
                    cells.append((fmt_num(q), f"({'+' if d > 0 else '−'}{fmt_num(abs(d))})", "up" if d > 0 else "down"))
                    mood = "yellow" if d > 0 else "red"
                elif len(set(inside)) > 1:
                    changes += 1
                    cells.append((fmt_num(q), "(±)", "swing"))
                else:
                    cells.append((fmt_num(q), "", "" if after_po else mood))
                prev_q, prev_t = q, t
            r = po_map.get((iid, k))
            if r is None:
                po_txt, po_kind = "No PO yet", ""
            elif r["Status"] == "Match":
                po_txt, po_kind = f"PO {r['PO qty']} · Match", "ok"
            elif r["Status"] in BAD:
                po_txt = (f"PO {r['PO qty'] or '—'} · {r['Difference']}" if r["Status"] == "Differs"
                          else r["Status"])
                po_kind = "bad"
            else:
                po_txt, po_kind = r["Status"], ""
            rows.append({"name": n, "cells": cells, "po": po_txt, "po_kind": po_kind,
                         "changed": any(c[2] in ("up", "down", "swing") for c in cells)})
        edits = [ts_of[v] for v, g in vers[1:] if str(g["status"].iloc[0]) != "Frozen"]
        blocks.append({"indent": iid, "customer": str(last["customer"]), "store": str(last["store"]),
                       "city": str(last["city"]), "status": str(last["status"]),
                       "entered": first_ts, "edited": edits, "frozen_at": frozen_at,
                       "items": len(rows), "qty": sum(qty_in[vers[-1][0]].values()),
                       "changes": changes, "rows": rows})
    blocks.sort(key=lambda b: (b["customer"].casefold(), b["store"].casefold(), b["indent"]))
    return blocks
