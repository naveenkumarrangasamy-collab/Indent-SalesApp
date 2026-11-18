from datetime import datetime

import pandas as pd

from core import config, tracking


def _row(v, at, qty, sku="2PC - Snacky Apple"):
    return {"indent_id": "IN-001", "version": v, "status": "Submitted", "submitted_at": at,
            "delivery_date": "2026-11-19", "customer": "Zepto", "store": "Y", "customer_sku_name": sku, "qty": qty}


def test_sku_changes_only_changed_items():
    ist = config.IST
    lines = pd.DataFrame([_row(1, "2026-11-19T02:00:00+00:00", 559), _row(1, "2026-11-19T02:00:00+00:00", 10, "Kiwi"),
                          _row(2, "2026-11-19T03:10:00+00:00", 600), _row(2, "2026-11-19T03:10:00+00:00", 10, "Kiwi")])
    ch = tracking.sku_changes(lines, "2026-11-19", datetime(2026, 11, 19, 8, 0, tzinfo=ist),
                              datetime(2026, 11, 19, 9, 0, tzinfo=ist))
    assert list(ch["Customer SKU Name"]) == ["2PC - Snacky Apple"]
    assert ch.iloc[0]["Before"] == "559" and ch.iloc[0]["Now"] == "600" and ch.iloc[0]["Change"] == "+41"


def test_half_hour_points():
    pts = tracking.points("2026-11-19", now=datetime(2026, 11, 19, 9, 10, tzinfo=config.IST))
    labels = [p[0] for p in pts]
    assert labels[:3] == ["8:00 AM", "8:30 AM", "9:00 AM"] and labels[-1] == "Now"
    assert pts[3][1] is None          # 9:30 still to come
