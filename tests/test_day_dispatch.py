import json
import sys
from unittest.mock import MagicMock

import pandas as pd

try:
    import streamlit  # noqa: F401
except ModuleNotFoundError:          # machines without Streamlit: core.indents only needs the cache decorator
    _st = MagicMock()
    _st.cache_data = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))
    sys.modules["streamlit"] = _st

from core import day_dispatch as dd
from core import processed2 as p2

DAY, CITY = "2026-11-27", "PTP Bangalore"


def _line(iid, cust, sku, parent, variety, lot, size, qty):
    return {"indent_id": iid, "version": 1, "status": "Submitted", "delivery_date": DAY, "city": CITY,
            "customer": cust, "store": "S1", "parent_sku": parent, "customer_sku_name": sku, "variety": variety,
            "lot": lot, "lot_size": size, "qty": qty, "price": 1}


LINES = pd.DataFrame([
    _line("IN-1", "Zepto", "2PC - Apple Royal Gala", "Apple", "Gala", "Pcs", "2 Pcs", 400),
    _line("IN-1", "Zepto", "1Kg - Apple Royal Gala", "Apple", "Gala", "Kg", "1 Kg", 50),
    _line("IN-1", "Zepto", "1Pc - Avocado", "Avocado", "", "Pcs", "1 Pcs", 30),
    _line("IN-2", "More", "1Pc - Avocado Hass", "Avocado", "", "Pcs", "1 Pcs", 20)])
PO = pd.DataFrame([{"indent_id": "IN-1", "kind": "po", "po_customer": "Zepto", "po_number": "P9",
                    "po_qty_json": json.dumps({"2PC - Apple Royal Gala": 400, "1Kg - Apple Royal Gala": 40})}])


def test_asked_is_po_when_there_is_one_else_indent():
    a = {(x["indent_id"], x["customer_sku_name"]): x for x in dd.asked(LINES, PO, DAY, CITY, {})}
    assert a[("IN-1", "2PC - Apple Royal Gala")]["asked"] == 400 and a[("IN-1", "2PC - Apple Royal Gala")]["basis"] == "PO"
    assert a[("IN-1", "1Kg - Apple Royal Gala")]["asked"] == 40          # PO is final, not the indent's 50
    assert a[("IN-1", "1Pc - Avocado")]["asked"] == 0 and a[("IN-1", "1Pc - Avocado")]["po_qty"] is None
    assert a[("IN-2", "1Pc - Avocado Hass")]["asked"] == 20 and a[("IN-2", "1Pc - Avocado Hass")]["basis"] == "Indent"
    assert a[("IN-1", "2PC - Apple Royal Gala")]["pool_key"] == "apple|gala|2pc"
    assert a[("IN-1", "1Kg - Apple Royal Gala")]["pool_key"] == "apple|gala|kg"
    assert a[("IN-2", "1Pc - Avocado Hass")]["pool_key"] == "avocado||1pc"   # variety only for Apple


def test_pool_from_production_detail_and_grade_words():
    lots = pd.DataFrame([{"entry_id": "a", "production_date": DAY, "city": CITY, "parent_sku": "Apple",
                          "variety": "Gala HG", "size": "100C", "origin": "NZ", "brand": "", "table_no": "1",
                          "box_kg": "18", "pcs_per_box": "100", "boxes_moved": "10", "executive": "Ravi"}])
    it = list(p2.items(lots).values())[0]
    saved = pd.DataFrame(p2.snapshot(it, [{"pack": "2PC", "mt_packs": 150}, {"pack": "1Kg", "mt_loose_kg": 60}],
                                     {}, "", "draft", DAY, CITY, "me"))
    assert dd.mt_made(lots, saved, DAY, CITY) == {"apple|gala|2pc": 150, "apple|gala|kg": 60}
    assert dd.pool_of("Blueberry", "", "Pack", "125 gm") == ("blueberry||125gm", "packs", 1.0)
    assert dd.pool_of("Grapes", "", "Pack", "250 gm")[0] == "grapes||250gm" and dd.pool_label("grapes||250gm") == "Grapes · 250gm"
    g = pd.DataFrame([{"entry_id": "g", "production_date": DAY, "city": CITY, "parent_sku": "Grapes", "variety": "Red Globe",
                       "size": "22mm+", "origin": "China", "brand": "", "table_no": "4", "box_kg": "6.5",
                       "pcs_per_box": "", "boxes_moved": "4", "executive": "A"}])
    gi = list(p2.items(g).values())[0]
    gs = pd.DataFrame(p2.snapshot(gi, [{"pack": "250gm", "mt_packs": 85}], {}, "", "draft", DAY, CITY, "me"))
    assert dd.mt_made(g, gs, DAY, CITY) == {"grapes||250gm": 85}


def test_rounds_add_up_and_full_check():
    items = [x for x in dd.asked(LINES, PO, DAY, CITY, {}) if x["indent_id"] == "IN-1"]
    r1 = dd.dispatch_rows(items, {"2PC - Apple Royal Gala": 150}, DAY, CITY, "me")
    r2 = dd.dispatch_rows(items, {"2PC - Apple Royal Gala": 300, "1Kg - Apple Royal Gala": 40}, DAY, CITY, "me")
    disp = pd.DataFrame(r1 + r2)
    sent = dd.totals(disp, DAY, CITY, "dispatch_qty")
    assert sent[("IN-1", "2pc - apple royal gala")] == 450 and len(dd.rounds(disp, DAY, CITY, "dispatch_id")["IN-1"]) == 2
    assert dd.pool_used(disp, DAY, CITY) == {"apple|gala|2pc": 450, "apple|gala|kg": 40}
    ret = pd.DataFrame(dd.return_rows(items, {"2PC - Apple Royal Gala": 30}, {"2PC - Apple Royal Gala": "Damaged"},
                                      DAY, CITY, "me"))
    back = dd.totals(ret, DAY, CITY, "returned_qty")
    rows = {r["Item"]: r for r in dd.check_rows(items, sent, back, dd.rounds(ret, DAY, CITY, "return_id"))}
    g = rows["2PC - Apple Royal Gala"]            # PO 400, sent 450 (50 extra), 30 back -> 420 kept, 400 billed
    assert (g["Extra sent"], g["With customer"], g["Billed"], g["Status"]) == (50, 420, 400, "20 over PO with customer")
    assert rows["1Kg - Apple Royal Gala"]["Status"] == "Billed as PO" and rows["1Kg - Apple Royal Gala"]["Returned"] == 0
    stock = {r["MT stock"]: r for r in dd.stock_rows({"apple|gala|2pc": 500}, items, sent, back)}
    s = stock["Apple · Gala · 2 PC"]
    assert (s["MT made"], s["Dispatched"], s["MT left"], s["Returned"], round(s["Sold of MT"], 2)) == (500, 450, 50, 30, .84)


def test_check_states():
    assert dd.check(400, 150, 0, False)["status"] == "Returns pending"
    assert dd.check(400, 150, 0, True)["status"] == "Short 250" and dd.check(400, 150, 0, True)["billed"] == 150
    assert dd.check(400, 0, 0, False)["status"] == "Not sent"
    assert dd.check(400, 440, 40, True)["status"] == "Billed as PO"
    assert dd.check(10, 10, 12, True)["status"] == "Returned more than sent"
