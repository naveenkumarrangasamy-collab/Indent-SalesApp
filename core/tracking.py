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


def until_hour() -> int:
    """Last column of the Hourly tracker (26 Nov, user: till 7 PM). Secret `tracker_until`; the mail hours
    (hourly_mail_from / _to) are not touched."""
    try:
        return max(9, min(23, int(config.get("tracker_until", 19))))
    except (TypeError, ValueError):
        return 19


def points(day: str, now: datetime | None = None) -> list[tuple[str, datetime | None]]:
    """(label, moment) every 30 min from the first mail hour to 7 PM (`tracker_until`); None = still to come.
    Plus 'Now' while the day is still open. A future delivery day is tracked on today's clock, so orders
    entered today for tomorrow show up as they come in (26 Nov)."""
    first, _last = hourly.hours()
    now = now or config.now_ist()
    d = min(date.fromisoformat(day), now.date())
    t = datetime.combine(d, time(first, 0), tzinfo=config.IST)
    end = datetime.combine(d, time(until_hour(), 0), tzinfo=config.IST)
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
        rows = indents.po_vs_indent(cur.lines, info, customer=h.customer) if info["qty"] is not None else [
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


def _po_events(lines: pd.DataFrame, po: pd.DataFrame | None, iid: str, customer: str) -> list[tuple]:
    """26 Nov (user): every PO upload / End of POs of one indent, oldest first, as
    (UTC time, {item key: PO qty or None = not on the PO}, ended). Each event holds the PO as it stood
    then (one-PO customers: the latest PO; multi-PO: all POs so far, summed)."""
    if po is None or po.empty or "indent_id" not in po.columns or "confirmed_at" not in po.columns:
        return []
    rows = po[po["indent_id"].astype(str) == str(iid)].copy()
    if rows.empty:
        return []
    rows["_t"] = pd.to_datetime(rows["confirmed_at"], errors="coerce", utc=True)
    rows = rows.dropna(subset=["_t"]).sort_values("_t", kind="stable")
    cur = indents.snapshot(lines, iid)
    if cur is None:
        return []
    out = []
    for t in sorted(set(rows["_t"])):
        info = indents.po_info(rows[rows["_t"] <= t], iid)
        if info["qty"] is None:
            continue
        res = indents.po_vs_indent(cur.lines, info, customer=customer)
        out.append((t, {_key(r["customer_sku_name"]): r["po_qty"] for r in res}, info["ended"]))
    return out


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
    26 Nov (user): a PO is tracked like an edit. From the half hour a PO is uploaded the cell shows the
    **PO qty**, with '(PO +940)' / '(PO −50)' in that half hour and the yellow / red after it, so the PO
    difference stays visible ('—' = not on the PO). Multi-PO customers (Swiggy): an item takes the PO qty
    once it is on a PO; items on no PO keep the indent qty until End of POs. PO-only items show from their
    PO. Last column: PO vs indent."""
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

        events = _po_events(lines, po, iid, str(last["customer"]))
        multi = indents.is_multi_po(str(last["customer"]))

        def po_at(t, k, _ev=events, _multi=multi):
            """(applies, qty or None, event time) of the PO for item k at point t."""
            T = pd.Timestamp(t).tz_convert("UTC")
            hit = None
            for e in _ev:
                if e[0] <= T:
                    hit = e
            if hit is None:
                return False, None, None
            q = hit[1].get(k)
            if _multi and not hit[2] and q is None:       # more POs coming: not on a PO yet = keep indent
                return False, None, None
            return True, q, max(e[0] for e in _ev if e[0] <= T and (k in e[1] or not _multi or e[2]))

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
                frozen_plain = not events and frozen_at is not None and frozen_at <= T   # PO without item qty
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
                applies, pq, pt = po_at(t, k)
                if applies:
                    qe = float(pq or 0)
                    shown = fmt_num(qe) if pq is not None else "—"
                    po_now = pt is not None and (lo is None or pt > lo)
                    dd = qe - (prev_q if prev_q is not None else q)
                    if po_now and dd:
                        changes += 1
                        cells.append((shown, f"(PO {'+' if dd > 0 else '−'}{fmt_num(abs(dd))})",
                                      "up" if dd > 0 else "down"))
                        mood = "yellow" if dd > 0 else "red"
                    elif po_now:                       # PO = indent: plain from here
                        mood = ""
                        cells.append((shown, "", ""))
                    else:
                        cells.append((shown, "", mood))
                    prev_q, prev_t = qe, t
                    continue
                if frozen_plain:
                    cells.append((fmt_num(q), "", ""))
                elif d:
                    changes += 1
                    cells.append((fmt_num(q), f"({'+' if d > 0 else '−'}{fmt_num(abs(d))})", "up" if d > 0 else "down"))
                    mood = "yellow" if d > 0 else "red"
                elif len(set(inside)) > 1:
                    changes += 1
                    cells.append((fmt_num(q), "(±)", "swing"))
                else:
                    cells.append((fmt_num(q), "", mood))
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
        # PO-only items (on the customer's PO, never on the indent): last, in red (19 Nov)
        for (pid, k), r in po_map.items():
            # PO-only = no indent qty (also while Swiggy's POs are still coming, 26 Nov)
            if pid == iid and str(r["Indent qty"]).strip() == "" and str(r["PO qty"]).strip() and k not in seen:
                cells, prev, seen_po = [], None, False
                for _lbl, t in pts:
                    applies, pq, _pt = po_at(t, k)
                    if not applies or pq is None:
                        cells.append(("·", "", "") if not seen_po else ("—", "", "yellow"))
                        continue
                    if prev is None or pq != prev:
                        cells.append((fmt_num(pq), f"(PO +{fmt_num(pq)})" if prev is None else
                                      f"(PO {'+' if pq > prev else '−'}{fmt_num(abs(pq - prev))})", "up"))
                    else:
                        cells.append((fmt_num(pq), "", "yellow"))
                    prev, seen_po = pq, True
                rows.append({"name": r["Customer SKU Name"], "cells": cells,
                             "po": f"Not on indent · PO {r['PO qty']}" + (f" · {r['Status']}" if "more coming"
                                                                         in str(r["Status"]) else ""),
                             "po_kind": "bad",
                             "changed": True, "po_only": True})
        edits = [ts_of[v] for v, g in vers[1:] if str(g["status"].iloc[0]) != "Frozen"]
        blocks.append({"indent": iid, "customer": str(last["customer"]), "store": str(last["store"]),
                       "city": str(last["city"]), "status": str(last["status"]),
                       "entered": first_ts, "edited": edits, "frozen_at": frozen_at,
                       "items": len(rows), "qty": sum(qty_in[vers[-1][0]].values()),
                       "changes": changes, "rows": rows})
    blocks.sort(key=lambda b: (b["customer"].casefold(), b["store"].casefold(), b["indent"]))
    return blocks
