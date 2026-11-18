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
