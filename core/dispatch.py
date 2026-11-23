"""Dispatch, returns and the two documents (23 Nov; owners only while being tried).

After Pre-production is frozen and the Batching plan saved, each indent is dispatched:
the warehouse types what is loaded per item (starts from the batching plan), which makes the
**Delivery Order** (proforma, document 1). When the store's returns are marked, the
**final invoice** (document 2) bills dispatched − returned.

Tabs (append-only, created on first save): Dispatch_Lines (the last doc_no per indent wins),
Return_Lines (the last invoice_no per indent wins). Quantities are in the indent's own units (lots).
"""
from __future__ import annotations

import pandas as pd

from core import config
from core.models import fmt_num, to_number
from core.schema import DISPATCH_LINES, RETURN_LINES

RETURN_REASONS = ["Damaged", "Quality", "Over PO qty", "Short shelf life", "Other"]


def _c(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _k(v) -> str:
    return _c(v).casefold()


def _read(tab: str) -> pd.DataFrame:
    from core import store_settings
    return store_settings._read(None, tab)


def read_all() -> dict[str, pd.DataFrame]:
    return {DISPATCH_LINES: _read(DISPATCH_LINES), RETURN_LINES: _read(RETURN_LINES)}


def _latest(df: pd.DataFrame | None, indent_id: str, doc_col: str) -> pd.DataFrame:
    """Rows of the last saved document of one indent."""
    if df is None or df.empty or "indent_id" not in df.columns or doc_col not in df.columns:
        return pd.DataFrame()
    rows = df[df["indent_id"].map(_c) == _c(indent_id)]
    if rows.empty:
        return rows
    last = _c(rows[doc_col].iloc[-1])
    return rows[rows[doc_col].map(_c) == last]


def dispatched(df: pd.DataFrame | None, indent_id: str) -> dict:
    """{'doc_no', 'at', 'by', 'vehicle', 'driver', 'items': {sku key: row}} of the last dispatch, or {}."""
    rows = _latest(df, indent_id, "doc_no")
    if rows.empty:
        return {}
    first = rows.iloc[0]
    return {"doc_no": _c(first["doc_no"]), "at": _c(first.get("dispatched_at")) or _c(first.get("saved_at")),
            "by": _c(first.get("saved_by")), "vehicle": _c(first.get("vehicle")), "driver": _c(first.get("driver")),
            "items": {_k(r["customer_sku_name"]): r for r in rows.to_dict("records")}}


def returned(df: pd.DataFrame | None, indent_id: str) -> dict:
    """{'invoice_no', 'at', 'by', 'items': {sku key: row}} of the last returns save, or {}."""
    rows = _latest(df, indent_id, "invoice_no")
    if rows.empty:
        return {}
    first = rows.iloc[0]
    return {"invoice_no": _c(first["invoice_no"]), "at": _c(first.get("saved_at")), "by": _c(first.get("saved_by")),
            "items": {_k(r["customer_sku_name"]): r for r in rows.to_dict("records")}}


def next_doc_no(df: pd.DataFrame | None, indent_id: str) -> str:
    """DO-IN046-1, DO-IN046-2 (a re-dispatch replaces the earlier one)."""
    n = 0
    if df is not None and not df.empty and "indent_id" in df.columns:
        n = df[df["indent_id"].map(_c) == _c(indent_id)]["doc_no"].map(_c).nunique()
    return f"DO-{_c(indent_id).replace('-', '')}-{n + 1}"


def invoice_no(indent_id: str) -> str:
    return f"INV-{_c(indent_id).replace('-', '')}"


def check(indent_qty: float, dispatch_qty: float | None, batched: float | None, pct: float) -> tuple[str, str]:
    """(vs indent, vs batching) labels for one item; each 'ok' / 'warn' / 'bad' prefixed: 'ok|Same'."""
    if dispatch_qty is None:
        return "bad|Not entered", ""
    diff = dispatch_qty - indent_qty
    lim = indent_qty * (1 + pct / 100)
    vi = ("ok|Same" if abs(diff) < 1e-9 else f"warn|{fmt_num(-diff)} short" if diff < 0
          else f"bad|+{fmt_num(diff)} over limit" if dispatch_qty > lim + 1e-9 else f"ok|+{fmt_num(diff)} extra")
    if batched is None:
        return vi, "neu|No batching"
    bd = dispatch_qty - batched
    vb = ("ok|Matches" if abs(bd) < 1e-6 else f"bad|+{fmt_num(bd)} over batching" if bd > 0
          else f"warn|{fmt_num(-bd)} under batching")
    return vi, vb


def save_dispatch(backend, head: dict, items: list[dict], user: str) -> str:
    """head: indent_id, delivery_date, city, customer, store, vehicle, driver, dispatched_at.
    items: [{customer_sku_name, lot, indent_qty, dispatch_qty, price, reason}]. Returns the DO number."""
    doc = next_doc_no(_read(DISPATCH_LINES), head["indent_id"])
    stamp = config.now_iso()
    rows = [{"saved_at": stamp, "saved_by": user, "doc_no": doc, **head, **it} for it in items]
    backend.append_dicts(DISPATCH_LINES, rows)
    return doc


def save_returns(backend, indent_id: str, doc_no: str, items: list[dict], user: str) -> str:
    """items: [{customer_sku_name, lot, dispatched, returned, reason, billed, price}]. Returns the invoice no."""
    inv = invoice_no(indent_id)
    stamp = config.now_iso()
    rows = [{"saved_at": stamp, "saved_by": user, "invoice_no": inv, "indent_id": indent_id, "doc_no": doc_no, **it}
            for it in items]
    backend.append_dicts(RETURN_LINES, rows)
    return inv


# ------------------------------------------------------------------ documents

def company() -> dict:
    """Seller details for the documents (secrets company_name, company_address, company_gstin)."""
    return {k: _c(config.get(f"company_{k}", "")) or f"[{k.upper()}]" for k in ("name", "address", "gstin")}


def _hsn_gst(parent: str) -> tuple[str, float]:
    hsn = config.get("hsn_codes", {}) or {}
    gst = config.get("gst_pct", {}) or {}
    p = _c(parent)
    pick = lambda d: next((v for k, v in dict(d).items() if _k(k) == _k(p)), None)  # noqa: E731
    return _c(pick(hsn)) or "", to_number(pick(gst)) if pick(gst) is not None else 0.0


def _money(v: float) -> str:
    return f"{v:,.2f}"


def delivery_order_pdf(head: dict, rows: list[dict]) -> bytes:
    from core import pdf_report
    co = company()
    sub = [f"Delivery Order {head['doc_no']} · Proforma, not a tax invoice",
           f"Indent {head['indent_id']} · PO {head.get('po') or '-'} · Delivery {head['delivery_date']}",
           f"From: {co['name']}, {co['address']} · GSTIN {co['gstin']}",
           f"To: {head['customer']} - {head['store']} ({head['city']})",
           f"Vehicle {head.get('vehicle') or '-'} · Driver {head.get('driver') or '-'} · "
           f"Dispatched {head.get('dispatched_at') or '-'}"]
    df = pd.DataFrame([{"#": i + 1, "Item": r["customer_sku_name"], "Indent": fmt_num(to_number(r["indent_qty"])),
                        "Dispatched": fmt_num(to_number(r["dispatch_qty"])), "Unit": r.get("lot", ""),
                        "Rate": _money(to_number(r.get("price"))),
                        "Amount": _money(to_number(r["dispatch_qty"]) * to_number(r.get("price")))}
                       for i, r in enumerate(rows)])
    total = sum(to_number(r["dispatch_qty"]) * to_number(r.get("price")) for r in rows)
    df = pd.concat([df, pd.DataFrame([{"#": "", "Item": "Total", "Amount": _money(total)}])], ignore_index=True).fillna("")
    return pdf_report.table_pdf("DELIVERY ORDER", sub, df,
                                "Received by (store): name, sign, date ______________________ · "
                                "Final invoice follows after returns are marked.")


def invoice_pdf(head: dict, rows: list[dict]) -> bytes:
    from core import pdf_report
    co = company()
    sub = [f"Tax invoice {head['invoice_no']} · FINAL · Date {head.get('date', '')}",
           f"Indent {head['indent_id']} · DO {head['doc_no']} · PO {head.get('po') or '-'}",
           f"Seller: {co['name']}, {co['address']} · GSTIN {co['gstin']}",
           f"Bill to: {head['customer']} - {head['store']} ({head['city']})"]
    out, taxable, tax = [], 0.0, 0.0
    for i, r in enumerate(rows):
        hsn, gst = _hsn_gst(r.get("parent_sku", ""))
        amt = to_number(r["billed"]) * to_number(r.get("price"))
        taxable += amt
        tax += amt * gst / 100
        out.append({"#": i + 1, "Item": r["customer_sku_name"], "HSN": hsn, "Dispatched": fmt_num(to_number(r["dispatched"])),
                    "Returned": fmt_num(to_number(r["returned"])), "Billed": fmt_num(to_number(r["billed"])),
                    "Unit": r.get("lot", ""), "Rate": _money(to_number(r.get("price"))), "GST %": fmt_num(gst),
                    "Amount": _money(amt)})
    df = pd.DataFrame(out)
    extra = [{"Item": "Taxable value", "Amount": _money(taxable)}, {"Item": "GST", "Amount": _money(tax)},
             {"Item": "Total", "Amount": _money(taxable + tax)}]
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True).fillna("")
    return pdf_report.table_pdf("TAX INVOICE", sub, df, f"For {co['name']} · Authorised signatory")
