"""26 Nov: device alerts on PO upload (core/alerts.py)."""
import pandas as pd

from core import alerts
from core.models import IndentHeader


def _hdr(city="PTP Bangalore", customer="Swiggy", store="Swiggy WH2"):
    return IndentHeader(delivery_date="2026-11-26", city=city, customer=customer, store=store, expected_time="10:00")


def _row(name, ind, po):
    diff = (po or 0) - (ind or 0)
    ok = (po is None and not ind) or (po is not None and ind is not None and abs(po - ind) < 1e-9) \
        or (ind is None and not po)
    return {"customer_sku_name": name, "lot": "", "indent_qty": ind, "po_qty": po, "diff": diff, "ok": ok}


def test_recipients_by_role_and_city():
    access = pd.DataFrame([
        {"Email": "wh@x.com", "Role": "warehouse", "Status": "active", "City": "PTP Bangalore"},
        {"Email": "whh@x.com", "Role": "warehouse", "Status": "active", "City": "PTP Hyderabad"},
        {"Email": "own@x.com", "Role": "owner", "Status": "active", "City": ""},
        {"Email": "cr@x.com", "Role": "owner_full", "Status": "active", "City": "PTP Chennai"},
        {"Email": "sales@x.com", "Role": "sales", "Status": "active", "City": "PTP Bangalore"},
        {"Email": "gone@x.com", "Role": "owner", "Status": "revoked", "City": ""},
    ])
    to = alerts.recipients(access, "PTP Bangalore")
    assert set(to) >= {"wh@x.com", "own@x.com", "cr@x.com"}
    assert "whh@x.com" not in to and "sales@x.com" not in to and "gone@x.com" not in to


def test_messages_only_names_and_diffs_with_threshold():
    rows = [_row("1Pc - Imported Avocado", 211, 161),          # -50: alert
            _row("1Pc - Green Kiwi", 300, 295),                 # -5 of 300 (1.7 %): no alert
            _row("1Kg - Nectr gala apple Large", 60, 47),       # -13 of 60 (22 %): alert
            _row("1Tray - Mandarin", 25, None),                 # not on the PO: -25
            _row("250gm - Imported Red Globe Grapes", None, 40)]   # new SKU
    msgs = alerts.messages(_hdr(), rows, ["1Pc - Imported Avocado"])
    kinds = {m["kind"]: m for m in msgs}
    assert kinds["diff"]["title"] == "PO difference · Swiggy · Swiggy WH2"
    assert kinds["diff"]["lines"] == ["1Pc - Imported Avocado  -50", "1Kg - Nectr gala apple Large  -13",
                                      "1Tray - Mandarin  -25"]
    assert kinds["new"]["lines"] == ["250gm - Imported Red Globe Grapes  +40"]
    assert kinds["spec"]["lines"] == ["1Pc - Imported Avocado"]
    # multi-PO customers: no differences per PO (they come at End of POs)
    assert "diff" not in {m["kind"] for m in alerts.messages(_hdr(), rows, [], with_diffs=False)}


def test_topic_is_per_email_and_private():
    a, b = alerts.topic("A@x.com "), alerts.topic("a@x.com")
    assert a == b and a.startswith("mtindent-") and a != alerts.topic("c@x.com") and "x.com" not in a
