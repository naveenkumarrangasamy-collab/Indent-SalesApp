"""25 Nov: city-level Batching plan (MT / GT / Dump) and Actual dispatch."""
import pandas as pd

from core import batch_city as bc

ROW = {"key": "apple|gala|pcs", "parent": "Apple", "variety": "Gala", "unit": "pcs", "need": 2376.0}
OPTS = [{"label": "Turkey · Gala · 120C · 18 kg", "count": "120", "box_kg": 18.0},
        {"label": "NZ · Gala HG · 175C", "count": "175", "box_kg": None}]


def test_grade_rows_left_and_status():
    took = {OPTS[0]["label"]: 6, OPTS[1]["label"]: 10}
    saved = {(ROW["key"], OPTS[0]["label"]): {"mt": 690.0, "gt": 22.0, "dump": 8.0}}
    lines = bc.grade_rows(ROW, took, OPTS, saved)
    assert [x["fruit"] for x in lines] == [720, 1750]
    assert lines[0]["left"] == 0 and lines[1]["left"] == 1750
    assert bc.grade_status(lines) == "Part graded"
    lines[1].update(mt=1690.0, gt=45.0, dump=15.0, graded=True, left=0)
    assert bc.grade_status(lines) == "Graded"
    lines[1].update(mt=1800.0, left=-110)
    assert bc.grade_status(lines) == "Over"
    assert bc.grade_status([]) == "Not graded"


def test_unit_word_and_check():
    assert bc.unit_word("pcs", 2) == "packs of 2 pcs" and bc.unit_word("pcs", 1) == "pcs"
    assert bc.unit_word("kg", 1) == "kg" and bc.unit_word("punnets", 1) == "punnets"
    assert bc.check(342, 342, 10, False) == ("ok", "Same")
    assert bc.check(342, 336, 10, False)[0] == "warn"
    assert bc.check(342, 370, 10, False)[0] == "bad"          # extra needs the tick
    assert bc.check(342, 370, 10, True) == ("ok", "+28 extra")
    assert bc.check(342, 400, 10, True)[0] == "bad"           # over the 10 % limit
    assert bc.check(5, 6, 10, True)[0] == "ok"                # one more pack on a small line is fine


def test_indent_lines_po_first_and_units():
    lines = pd.DataFrame([
        {"indent_id": "IN-1", "customer": "Zepto", "store": "Z1", "city": "PTP Bangalore", "parent_sku": "Apple",
         "customer_sku_name": "2PC - Apple Royal Gala", "variety": "Gala", "lot": "Pcs", "qty": 342, "price": 1},
        {"indent_id": "IN-1", "customer": "Zepto", "store": "Z1", "city": "PTP Bangalore", "parent_sku": "Kiwi",
         "customer_sku_name": "1Pc - Green Kiwi", "variety": "", "lot": "Pcs", "qty": 50, "price": 1},
        {"indent_id": "IN-2", "customer": "Trent", "store": "Trent", "city": "PTP Bangalore", "parent_sku": "Apple",
         "customer_sku_name": "1Kg - Apple Red Delicious", "variety": "RD", "lot": "Kg", "qty": 1000, "price": 1}])
    po = {("IN-1", "2pc - apple royal gala"): 300.0, ("IN-1", "1pc - green kiwi"): None}
    out = bc.indent_lines(lines, po, {"IN-1"}, [], lambda p: p == "Apple")
    a = out["IN-1"]["lines"]
    assert [x["name"] for x in a] == ["2PC - Apple Royal Gala"]          # not on the PO = left out
    assert a[0]["asked"] == 300 and a[0]["per"] == 2 and a[0]["word"] == "packs of 2 pcs"
    assert a[0]["key"] == "Apple|Gala|pcs"
    t = out["IN-2"]["lines"][0]
    assert t["asked"] == 1000 and t["unit"] == "kg"


def test_mt_used_and_day_check():
    ddf = pd.DataFrame([
        {"doc_no": "DO-IN1-1", "indent_id": "IN-1", "delivery_date": "2026-11-25", "city": "PTP Bangalore",
         "customer_sku_name": "2PC - X", "club_key": ROW["key"], "from_mt": 600},
        {"doc_no": "DO-IN1-2", "indent_id": "IN-1", "delivery_date": "2026-11-25", "city": "PTP Bangalore",
         "customer_sku_name": "2PC - X", "club_key": ROW["key"], "from_mt": 684},      # replaces -1
        {"doc_no": "DO-IN2-1", "indent_id": "IN-2", "delivery_date": "2026-11-25", "city": "PTP Bangalore",
         "customer_sku_name": "2PC - Y", "club_key": ROW["key"], "from_mt": 1800}])
    used = bc.mt_used(ddf, "2026-11-25", "PTP Bangalore")
    assert used == {ROW["key"]: 2484}
    assert bc.mt_used(ddf, "2026-11-25", "PTP Bangalore", skip="IN-2") == {ROW["key"]: 684}
    tot = {ROW["key"]: {"boxes": 16, "fruit": 2470, "mt": 2380, "gt": 67, "dump": 23}}
    chk = bc.day_check([ROW], tot, used)[0]
    assert not chk["ok"] and chk["mt_left"] == -104 and "more than MT graded" in chk["notes"][0]
    chk = bc.day_check([ROW], tot, {ROW["key"]: 2380})[0]
    assert chk["ok"] and chk["not_graded"] == 0


def test_locks_and_state():
    ddf = pd.DataFrame([{"doc_no": "DO-IN1-1", "indent_id": "IN-1", "customer_sku_name": "A", "saved_by": "x",
                         "saved_at": "t"}])
    assert bc.dispatch_state(ddf, {}, "IN-1")["locked"]
    unl = bc.locks(pd.DataFrame([{"indent_id": "IN-1", "doc_no": "DO-IN1-1", "action": "unlock"}]))
    assert not bc.dispatch_state(ddf, unl, "IN-1")["locked"]
    assert bc.dispatch_state(ddf, unl, "IN-9") == {}
