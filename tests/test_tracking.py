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


def _r(iid, v, at, sku, qty, status="Submitted", cust="More", store="EK"):
    return {"indent_id": iid, "version": v, "status": status, "submitted_at": f"2026-11-19T{at}:00+05:30",
            "delivery_date": "2026-11-19", "city": "B", "customer": cust, "store": store,
            "customer_sku_name": sku, "qty": qty}


def test_grid_today_like_cases():
    ist = config.IST
    lines = pd.DataFrame([
        # More: entered 9:31 (413), raised 9:37 (459), item added 9:52
        _r("IN-021", 1, "09:31", "Hass", 413), _r("IN-021", 2, "09:37", "Hass", 459),
        _r("IN-021", 3, "09:52", "Hass", 459), _r("IN-021", 3, "09:52", "Loose", 10),
        # Swiggy WH1: entered 8:46, grapefruit cleared 9:35, then PO 10:05
        _r("IN-018", 1, "08:46", "Grapefruit", 4, cust="Swiggy", store="WH1"),
        _r("IN-018", 1, "08:46", "Kiwi", 300, cust="Swiggy", store="WH1"),
        _r("IN-018", 2, "09:35", "Grapefruit", 0, cust="Swiggy", store="WH1"),
        _r("IN-018", 2, "09:35", "Kiwi", 300, cust="Swiggy", store="WH1"),
        _r("IN-018", 3, "10:05", "Grapefruit", 0, "Frozen", cust="Swiggy", store="WH1"),
        _r("IN-018", 3, "10:05", "Kiwi", 300, "Frozen", cust="Swiggy", store="WH1"),
        # Zepto: swing inside one half hour (50 -> 0 between 9:00 and 9:30)
        _r("IN-016", 1, "07:00", "Snacky", 0, cust="Zepto", store="Y"),
        _r("IN-016", 2, "09:05", "Snacky", 50, cust="Zepto", store="Y"),
        _r("IN-016", 3, "09:09", "Snacky", 0, cust="Zepto", store="Y"),
    ])
    pts = [(f"{h}:{m:02d}", datetime(2026, 11, 19, h, m, tzinfo=ist)) for h, m in
           ((8, 30), (9, 0), (9, 30), (10, 0), (10, 30))]
    blocks = {b["indent"]: b for b in tracking.grid(lines, None, "2026-11-19", pts)}
    assert [b["customer"] for b in tracking.grid(lines, None, "2026-11-19", pts)] == ["More", "Swiggy", "Zepto"]
    more = {r["name"]: r["cells"] for r in blocks["IN-021"]["rows"]}
    assert more["Hass"][2] == ("·", "", "") and more["Hass"][3] == ("459", "(+46)", "up")
    assert more["Hass"][4] == ("459", "", "yellow")
    assert more["Loose"][3] == ("10", "(+10)", "up")
    wh1 = {r["name"]: r["cells"] for r in blocks["IN-018"]["rows"]}
    assert wh1["Grapefruit"][1] == ("4", "", "") and wh1["Grapefruit"][3] == ("0", "(−4)", "down")
    assert wh1["Grapefruit"][4] == ("0", "", "")          # PO at 10:05: plain from then on
    assert wh1["Kiwi"][2] == ("300", "", "")
    z = blocks["IN-016"]["rows"][0]["cells"]
    assert z[2] == ("0", "(±)", "swing")
    assert blocks["IN-021"]["changes"] == 2 and blocks["IN-016"]["changes"] == 1
