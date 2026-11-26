"""Device alerts on PO upload (26 Nov, user-approved preview).

Sent to the people who work on stock: Access rows with role Warehouse, Owner or Creator (active), in the
indent's city (no cities = all). Addressed by the **login e-mail**: browser push to every device where that
person tapped "Allow alerts on this device" (core/webpush.py; no extra app, no account).

Three alerts, each only the Customer SKU name as entered and the difference:
- **PO difference**: a one-PO customer's PO, or End of POs for multi-PO customers (Swiggy), with items whose
  PO qty differs from the indent by at least `alert_min_units` (20) or `alert_min_pct` (10 %).
- **New SKU in PO**: items on the PO that are not on the indent (every PO, also Swiggy's).
- **Spec not mapped**: items on the PO with no Spec-Size (New tab / New Mapping Combination).

Sending never blocks or fails a PO upload; every alert is logged in Mail_Log (kind "alert").
"""
from __future__ import annotations

import threading

from core import config
from core.models import fmt_num

ALERT_ROLES = ("warehouse", "owner", "owner_full")


# ------------------------------------------------------------------ settings

def min_units() -> float:
    try:
        return float(config.get("alert_min_units", 20))
    except (TypeError, ValueError):
        return 20.0


def min_pct() -> float:
    try:
        return float(config.get("alert_min_pct", 10))
    except (TypeError, ValueError):
        return 10.0


def _norm(email: str) -> str:
    return str(email or "").strip().casefold()


# ------------------------------------------------------------------ who

def _cities(v) -> list[str]:
    import re
    return [" ".join(c.split()) for c in re.split(r"[,;\n]", str(v or "")) if c.strip()]


def recipients(access, city: str) -> list[str]:
    """Active Warehouse / Owner / Creator e-mails for this city (a person with no cities gets every city).
    The Creator e-mail from the secrets is always included."""
    out: list[str] = []
    want = " ".join(str(city or "").split()).casefold()
    if access is not None and not access.empty:
        for r in access.to_dict("records"):
            if str(r.get("Status", "")).strip().lower() != "active":
                continue
            role = str(r.get("Role", "")).strip().lower()
            if role not in ALERT_ROLES:
                continue
            cities = [c.casefold() for c in _cities(r.get("City", ""))] if role != "owner_full" else []
            if cities and "all cities" not in cities and want not in cities:
                continue
            e = _norm(r.get("Email", ""))
            if e and e not in out:
                out.append(e)
    owner = _norm(config.owner_email())
    if owner and owner not in out:
        out.append(owner)
    return out


# ------------------------------------------------------------------ what

def _big(indent_qty, diff) -> bool:
    d = abs(float(diff or 0))
    if d < 1e-9:
        return False
    ind = abs(float(indent_qty or 0))
    return d >= min_units() or ind < 1e-9 or d / ind * 100 >= min_pct()


def _signed(v) -> str:
    v = float(v)
    return ("+" if v > 0 else "") + fmt_num(v)


def _where(header) -> str:
    cust, store = str(header.customer).strip(), str(header.store).strip()
    return cust if not store or store.casefold() == cust.casefold() else f"{cust} · {store}"


def messages(header, rows: list[dict], spec_missing: list[str], with_diffs: bool = True) -> list[dict]:
    """rows = indents.po_vs_indent(...). Only names and differences go in the text."""
    where, out = _where(header), []
    if with_diffs:
        diff = [r for r in rows if r["indent_qty"] is not None and not r["ok"] and _big(r["indent_qty"], r["diff"])]
        if diff:
            out.append({"kind": "diff", "title": f"PO difference · {where}", "tags": ["warning"], "priority": 4,
                        "lines": [f"{r['customer_sku_name']}  {_signed(r['diff'])}" for r in diff]})
    new = [r for r in rows if r["indent_qty"] is None and r["po_qty"]]
    if new:
        out.append({"kind": "new", "title": f"New SKU in PO · {where}", "tags": ["package"], "priority": 4,
                    "lines": [f"{r['customer_sku_name']}  {_signed(r['po_qty'])}" for r in new]})
    if spec_missing:
        out.append({"kind": "spec", "title": f"Spec not mapped · {where}", "tags": ["straight_ruler"],
                    "priority": 3, "lines": list(dict.fromkeys(spec_missing))})
    return out


def spec_missing(header, rows: list[dict], m) -> list[str]:
    """PO items (qty > 0) whose spec size is not known."""
    if m is None:
        return []
    out = []
    for r in rows:
        if not r["po_qty"]:
            continue
        info = m.prod_info(header.city, header.customer, r["customer_sku_name"])
        if not info or not str(info.get("Spec-Size") or "").strip():
            out.append(r["customer_sku_name"])
    return out


# ------------------------------------------------------------------ send

def publish(email: str, title: str, lines: list[str], tags=None, priority: int = 3,
            kind: str = "") -> tuple[bool, str]:
    """Browser push to every device of this person (tags / priority kept for older callers)."""
    from core import webpush
    try:
        return webpush.send_to(email, title, lines, tag=kind)
    except Exception as e:  # noqa: BLE001 - an alert must never break the app
        return False, f"{type(e).__name__}: {e}"[:300]


def send(to: list[str], msgs: list[dict], ref: str = "") -> list[tuple[str, str, bool, str]]:
    from core import recipients as rec
    results = []
    for msg in msgs:
        for email in to:
            ok, why = publish(email, msg["title"], msg["lines"], kind=msg["kind"])
            results.append((email, msg["title"], ok, why))
            try:
                rec.log("alert", f"{ref} {msg['kind']}".strip(), email, ok, f"{msg['title']} · {why}")
            except Exception:  # noqa: BLE001
                pass
    return results


def _in_background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def _prepare(cur, info: dict, multi: bool, end: bool) -> tuple[list[str], list[dict]]:
    from core import indents, masters
    m = masters.load_masters()
    rows = indents.po_vs_indent(cur.lines, info, customer=cur.header.customer)
    if end:
        msgs = [x for x in messages(cur.header, rows, []) if x["kind"] == "diff"]
    else:
        msgs = messages(cur.header, rows, spec_missing(cur.header, rows, m), with_diffs=not multi)
    return (recipients(m.access, cur.header.city) if msgs else []), msgs


def after_po(cur, this_po: dict, multi: bool) -> None:
    """Called after a PO is saved; never raises, sending runs in the background. One-PO customers:
    differences of this PO. Multi-PO customers: only new SKUs + spec (differences at End of POs)."""
    try:
        to, msgs = _prepare(cur, {"qty": this_po}, multi, end=False)
    except Exception:  # noqa: BLE001
        return
    if to and msgs:
        _in_background(send, to, msgs, cur.indent_id)


def after_end_of_pos(cur, info: dict) -> None:
    """Multi-PO customers: all POs summed against the indent, at End of POs."""
    try:
        to, msgs = _prepare(cur, info, True, end=True)
    except Exception:  # noqa: BLE001
        return
    if to and msgs:
        _in_background(send, to, msgs, cur.indent_id)


def send_test(email: str) -> tuple[bool, str]:
    """A sample of each alert to one person, now (sidebar button)."""
    samples = [
        ("PO difference · Swiggy · Swiggy WH2", ["1Pc - Imported Avocado  -50",
                                                "1Kg - Nectr gala apple Large - 350-450g  -13"], ["warning"], 4),
        ("New SKU in PO · Swiggy · Swiggy WH1", ["250gm - Imported Red Globe Grapes  +40"], ["package"], 4),
        ("Spec not mapped · Swiggy · Swiggy WH2", ["1Pc - Imported Avocado"], ["straight_ruler"], 3),
    ]
    oks = []
    from core import webpush
    if not webpush.subscriptions(email):
        return False, "Alerts are not on for any of your devices yet: tap Allow alerts on this device first."
    for i, (title, lines, _tags, _prio) in enumerate(samples):
        ok, why = publish(email, "[TEST] " + title, lines, kind=f"test{i}")
        oks.append((ok, why))
    from core import recipients as rec
    good = all(ok for ok, _ in oks)
    try:
        rec.log("alert-test", "test", email, good, "; ".join(w for _, w in oks))
    except Exception:  # noqa: BLE001
        pass
    return good, ("3 test alerts sent." if good else "Not sent: " + "; ".join(w for ok, w in oks if not ok))
