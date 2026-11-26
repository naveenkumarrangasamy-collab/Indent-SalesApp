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
    assert labels[-2] == "7:00 PM"    # 26 Nov: till 7 PM


def test_points_till_7pm_and_tomorrow_on_todays_clock():
    late = datetime(2026, 11, 26, 17, 40, tzinfo=config.IST)
    pts = tracking.points("2026-11-26", now=late)
    done = [p[0] for p in pts if p[1] is not None]
    assert done[-2:] == ["5:30 PM", "Now"] and "2:30 PM" in done
    tom = tracking.points("2026-11-27", now=late)
    assert tom[0][1] == datetime(2026, 11, 26, 8, 0, tzinfo=config.IST)   # tomorrow's orders tracked today
    after = tracking.points("2026-11-26", now=datetime(2026, 11, 26, 20, 5, tzinfo=config.IST))
    assert after[-1][0] == "7:00 PM" and after[-1][1] is not None


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


def _po(iid, at, qty, cust, kind="po"):
    import json
    return {"indent_id": iid, "version": 1, "po_customer": cust, "po_store": "", "confirmed_at":
            f"2026-11-19T{at}:00+05:30", "po_number": f"P{at}", "kind": kind,
            "po_qty_json": json.dumps(qty) if qty is not None else ""}


def test_grid_shows_po_qty_and_difference(monkeypatch):
    """26 Nov (user): a PO shows in the half hour it came, with its difference, like an edit."""
    from core import indents
    monkeypatch.setattr(indents, "read_po_item_map", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(indents, "_item_map_for", lambda *a, **k: {}, raising=False)
    ist = config.IST
    lines = pd.DataFrame([
        _r("IN-073", 1, "08:10", "1Kg - Apple RD", 50, cust="Trent", store="Trent"),
        _r("IN-073", 1, "08:10", "1Pc Blueberry Pack", 400, cust="Trent", store="Trent"),
        _r("IN-073", 1, "08:10", "1Tray - Mandarin", 25, cust="Trent", store="Trent"),
        _r("IN-073", 2, "09:16", "1Kg - Apple RD", 50, "Frozen", cust="Trent", store="Trent"),
        _r("IN-073", 2, "09:16", "1Pc Blueberry Pack", 400, "Frozen", cust="Trent", store="Trent"),
        _r("IN-073", 2, "09:16", "1Tray - Mandarin", 25, "Frozen", cust="Trent", store="Trent"),
        _r("IN-076", 1, "08:05", "1Pc - Imported Avocado", 211, cust="Swiggy", store="WH2"),
        _r("IN-076", 1, "08:05", "1Pc - Green Kiwi", 300, cust="Swiggy", store="WH2"),
    ])
    lines["_row"] = range(len(lines))
    for c, v in (("parent_sku", "Apple"), ("variety", ""), ("lot", "Pcs"), ("lot_size", ""), ("price", 1),
                 ("amount", 0), ("expected_time", "10:00"), ("submitted_by", "x"), ("change_note", "")):
        lines[c] = v
    po = pd.DataFrame([
        _po("IN-073", "09:16", {"1Kg - Apple RD": 990, "1Pc Blueberry Pack": 400, "Grapes X": 40}, "Trent"),
        _po("IN-076", "09:40", {"1Pc - Imported Avocado": 161, "250gm - Imported Red Globe Grapes": 40}, "Swiggy"),
    ])
    pts = [(f"{h}:{m:02d}", datetime(2026, 11, 19, h, m, tzinfo=ist)) for h, m in
           ((8, 30), (9, 0), (9, 30), (10, 0))]
    blocks = {b["indent"]: b for b in tracking.grid(lines, po, "2026-11-19", pts)}
    trent = {r["name"]: r["cells"] for r in blocks["IN-073"]["rows"]}
    assert trent["1Kg - Apple RD"][1] == ("50", "", "")
    assert trent["1Kg - Apple RD"][2] == ("990", "(PO +940)", "up")          # PO at 9:16
    assert trent["1Kg - Apple RD"][3] == ("990", "", "yellow")
    assert trent["1Pc Blueberry Pack"][2] == ("400", "", "")                  # PO = indent: plain
    assert trent["1Tray - Mandarin"][2] == ("—", "(PO −25)", "down")          # not on the PO
    assert trent["Grapes X"][1] == ("·", "", "") and trent["Grapes X"][2] == ("40", "(PO +40)", "up")
    sw = {r["name"]: r["cells"] for r in blocks["IN-076"]["rows"]}
    assert sw["1Pc - Imported Avocado"][3] == ("161", "(PO −50)", "down")     # Swiggy PO at 9:40
    assert sw["1Pc - Green Kiwi"][3] == ("300", "", "")                       # more POs coming: indent kept
    new = [r for r in blocks["IN-076"]["rows"] if r.get("po_only")][0]          # new item on a Swiggy PO
    assert new["name"] == "250gm - Imported Red Globe Grapes" and new["cells"][2] == ("·", "", "")
    assert new["cells"][3] == ("40", "(PO +40)", "up") and new["po"].startswith("Not on indent · PO 40")
