"""Two read-only tabs in the Google Sheet for people (19 Nov, user-approved):

- Indent_vs_PO: one row per indent item (and per PO-only item): indent qty, PO qty,
  difference, result. Differences are coloured red.
- Indent_Changes: one row per change made to an indent item (qty / price changed,
  item added or removed, delivery date moved), newest first.

Both are rebuilt from Indent_Lines, PO_Freeze, Change_Log (and PO_Item_Map) after
every save, so they are never edited by hand. The app itself never reads them."""
from __future__ import annotations

import re
import threading

import pandas as pd

from core.models import fmt_num
from core.schema import CHANGE_LOG, INDENT_LINES, PO_END, PO_FREEZE, PO_ITEM_MAP, STATUS_CANCELLED

VS_TAB = "Indent_vs_PO"
CHANGES_TAB = "Indent_Changes"

VS_COLS = ["Delivery", "City", "Customer", "Store", "Indent", "PO no", "PO at", "Customer SKU Name",
           "Indent qty", "PO qty", "Diff", "Result"]
CH_COLS = ["Delivery", "Indent", "City", "Customer", "Store", "Customer SKU Name", "Time", "By", "Change"]

BAD = ("Differs", "Not on PO", "Not on indent")
RED = (0.99, 0.85, 0.84)
GREEN = (0.85, 0.94, 0.85)


def _day(d) -> str:
    try:
        return pd.Timestamp(str(d)[:10]).strftime("%d-%b-%Y")
    except (ValueError, TypeError):
        return str(d or "")


def _when(ts) -> str:
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    if pd.isna(t):
        return str(ts or "")
    return t.tz_convert("Asia/Kolkata").strftime("%d-%b %H:%M")


def item_map(df: pd.DataFrame | None) -> dict[str, dict[str, str]]:
    """PO_Item_Map as {customer: {PO name or code (case-folded): our SKU name}}."""
    out: dict[str, dict[str, str]] = {}
    if df is None or df.empty:
        return out
    for r in df.to_dict("records"):
        sku = str(r.get("Customer SKU Name") or "").strip()
        cust = str(r.get("Customer") or "").strip().casefold()
        if not sku:
            continue
        for k in (r.get("PO Item Code"), r.get("PO Item Name")):
            if str(k or "").strip():
                out.setdefault(cust, {})[" ".join(str(k).split()).casefold()] = sku
    return out


def vs_rows(lines: pd.DataFrame, po: pd.DataFrame | None, maps: dict | None = None) -> list[dict]:
    """Indent vs PO for every indent (current version, not deleted)."""
    from core import indents
    out = []
    if lines is None or lines.empty:
        return out
    cur = indents.current_rows(lines)
    order = (cur.groupby("indent_id").first()
                .reset_index()
                .sort_values(["delivery_date", "customer", "store", "indent_id"],
                             ascending=[False, True, True, True]))
    for h in order.to_dict("records"):
        iid = str(h["indent_id"])
        snap = indents.snapshot(lines, iid)
        if snap is None or snap.status == STATUS_CANCELLED:
            continue
        info = indents.po_info(po, iid)
        pos = po[(po["indent_id"].astype(str) == iid)
                 & (po.get("kind", pd.Series("", index=po.index)).astype(str).str.lower() != PO_END)] \
            if po is not None and not po.empty and "indent_id" in po.columns else pd.DataFrame()
        po_at = _when(pos["confirmed_at"].iloc[-1]) if len(pos) and "confirmed_at" in pos.columns else ""
        base = {"Delivery": _day(h["delivery_date"]), "City": h["city"], "Customer": h["customer"],
                "Store": h["store"], "Indent": iid, "PO no": ", ".join(info["numbers"]), "PO at": po_at}
        if info["pos"] == 0 or info["qty"] is None:
            res = "No PO yet" if info["pos"] == 0 else "PO without item qty"
            for x in snap.lines:
                out.append({**base, "Customer SKU Name": x.customer_sku_name, "Indent qty": fmt_num(x.qty),
                            "PO qty": "", "Diff": "", "Result": res})
            continue
        more = indents.is_multi_po(snap.header.customer) and not info["ended"]
        for r in indents.po_vs_indent(snap.lines, info, (maps or {}).get(str(h["customer"]).strip().casefold(), {})):
            if r["indent_qty"] is None:
                result = "Not on indent"
            elif r["ok"]:
                result = "Match"
            elif r["po_qty"] is None:
                result = "Not on PO"
            else:
                result = "Differs"
            if more and result != "Match":
                result = "More POs coming"
            d = r["diff"]
            out.append({**base, "Customer SKU Name": r["customer_sku_name"],
                        "Indent qty": "" if r["indent_qty"] is None else fmt_num(r["indent_qty"]),
                        "PO qty": "" if r["po_qty"] is None else fmt_num(r["po_qty"]),
                        "Diff": "" if r["ok"] or d is None else ("+" if d > 0 else "") + fmt_num(d),
                        "Result": result})
    return out


def _added_qty(text: str) -> str:
    m = re.search(r"qty\s*=\s*([^;]+)", str(text or ""))
    return m.group(1).strip() if m else ""


def change_rows(lines: pd.DataFrame, log: pd.DataFrame | None) -> list[dict]:
    """Only real changes to items (and moved delivery dates), newest first."""
    if log is None or log.empty or lines is None or lines.empty:
        return []
    from core import indents
    head = indents.current_rows(lines, include_cancelled=True).groupby("indent_id").first()
    rows = []
    for c in log.to_dict("records"):
        t, f = str(c.get("change_type") or ""), str(c.get("field") or "")
        if t == "line_changed":
            what = f"{c.get('old_value')} → {c.get('new_value')}" if f == "qty" else \
                f"{f} {c.get('old_value')} → {c.get('new_value')}"
        elif t == "line_added":
            what = f"added {_added_qty(c.get('new_value'))}".strip()
        elif t == "line_removed":
            what = "removed"
        elif t == "header_changed" and f == "delivery_date":
            what = f"delivery {_day(c.get('old_value'))} → {_day(c.get('new_value'))}"
        else:
            continue                                     # status changes (PO, lock, delete) are not item changes
        iid = str(c.get("indent_id") or "")
        h = head.loc[iid] if iid in head.index else {}
        rows.append({"_ts": pd.to_datetime(c.get("changed_at"), errors="coerce", utc=True),
                     "Delivery": _day(h.get("delivery_date", "")), "Indent": iid, "City": h.get("city", ""),
                     "Customer": h.get("customer", ""), "Store": h.get("store", ""),
                     "Customer SKU Name": c.get("customer_sku_name") or "",
                     "Time": _when(c.get("changed_at")),
                     "By": str(c.get("changed_by") or "").split("@")[0], "Change": what})
    rows.sort(key=lambda r: (r["_ts"] if not pd.isna(r["_ts"]) else pd.Timestamp(0, tz="UTC")), reverse=True)
    for r in rows:
        r.pop("_ts")
    return rows


def _values(rows: list[dict], cols: list[str]) -> list[list]:
    return [cols] + [[r.get(c, "") for c in cols] for r in rows]


def refresh(backend=None) -> None:
    """Rebuild both tabs (one read, two writes, two colour calls)."""
    from core import indents
    b = backend or indents.get_backend()
    tabs = set(b.list_tabs())
    want = [t for t in (INDENT_LINES, PO_FREEZE, CHANGE_LOG, PO_ITEM_MAP) if t in tabs]
    data = b.read_many(want)
    lines = indents.prepare(data.get(INDENT_LINES, pd.DataFrame()))
    po = data.get(PO_FREEZE)
    vs = vs_rows(lines, po, item_map(data.get(PO_ITEM_MAP)))
    ch = change_rows(lines, data.get(CHANGE_LOG))
    b.replace_tab(VS_TAB, _values(vs, VS_COLS))
    b.color_rows(VS_TAB, len(VS_COLS), {RED: [i + 2 for i, r in enumerate(vs) if r["Result"] in BAD]},
                 n_rows=len(vs) + 1)
    b.replace_tab(CHANGES_TAB, _values(ch, CH_COLS))
    b.color_rows(CHANGES_TAB, len(CH_COLS), {}, n_rows=len(ch) + 1)


_lock = threading.Lock()
_again = threading.Event()


def refresh_soon() -> None:
    """After a save: rebuild the tabs in the background (Google Sheets) so the
    save itself is not slowed down; runs at once on the local test backend.
    Never raises: these tabs are only a view."""
    from core import indents
    try:
        b = indents.get_backend()
    except Exception:  # noqa: BLE001
        return
    if type(b).__name__ != "GoogleBackend":
        try:
            refresh(b)
        except Exception:  # noqa: BLE001
            pass
        return

    def run():
        while True:
            _again.clear()
            try:
                refresh(b)
            except Exception:  # noqa: BLE001 - a view; the next save tries again
                pass
            if not _again.is_set():
                return

    _again.set()
    if _lock.acquire(blocking=False):
        def guarded():
            try:
                run()
            finally:
                _lock.release()
        threading.Thread(target=guarded, daemon=True).start()


__all__ = ["refresh", "refresh_soon", "vs_rows", "change_rows", "item_map", "VS_TAB", "CHANGES_TAB"]
