"""19 Nov: name links (PO_Item_Map), PO-only items in the tracker, and the
Indent_vs_PO / Indent_Changes tabs."""
from datetime import datetime

import pandas as pd

from core import config, indents, po_reader, sheet_views, tracking
from core.models import IndentLine
from core.schema import PO_ITEM_MAP

FK = ["1Pc - Avocado - FK", "1Pc - Blueberry - FK", "1Pc - Avocado Jumbo - FK"]


def test_suggest_spelling_but_not_other_products():
    assert po_reader.suggest("Avocada Jumbo (PCS) - FK - Grade A", FK) == "1Pc - Avocado Jumbo - FK"
    # Bloom must agree; a new variety is not a spelling
    assert po_reader.suggest("250gm - Bloom Grapes Red globe",
                             ["250gm - Grapes Red Globe Imported", "200gm - Grapes Crimson Red Imported"]) == ""
    assert po_reader.suggest("Apple Fuji", ["1Kg - Apple Royal Gala"]) == ""


def test_po_line_matches_a_misspelt_indent_item():
    lines = po_reader.match([po_reader.POLine("Avocada Jumbo (PCS) - FK - Grade A", 18)], FK, {}, prefer=FK)
    assert lines[0].sku == "1Pc - Avocado Jumbo - FK" and lines[0].how == "guess"


def _ln(name, qty):
    return IndentLine("Avocado", name, "", "Pcs", qty, 1)


def test_po_vs_indent_uses_the_approved_link():
    lines = [_ln("1Pc - Avocado - FK", 454), _ln("1Pc - Avocado Jumbo - FK", 18)]
    info = {"qty": {"1Pc - Avocado - FK": 454.0, "Avocada Jumbo (PCS) - FK - Grade A": 18.0}}
    links = {"avocada jumbo (pcs) - fk - grade a": "1Pc - Avocado Jumbo - FK"}
    rows = indents.po_vs_indent(lines, info, links)
    assert len(rows) == 2 and all(r["ok"] for r in rows)


def test_item_map_by_customer():
    df = pd.DataFrame([{"Customer": "Flipkart", "PO Item Code": "", "PO Item Name": "Avocada  Jumbo",
                        "Customer SKU Name": "1Pc - Avocado Jumbo - FK"}])
    assert sheet_views.item_map(df) == {"flipkart": {"avocada jumbo": "1Pc - Avocado Jumbo - FK"}}


def _r(v, at, sku, qty, status="Submitted"):
    return {"indent_id": "IN-016", "version": v, "status": status, "submitted_at": f"2026-11-19T{at}:00+05:30",
            "submitted_by": "a@x.com", "delivery_date": "2026-11-19", "city": "PTP Bangalore",
            "customer": "Zepto", "store": "Y", "expected_time": "10:00", "parent_sku": "Grapes",
            "customer_sku_name": sku, "variety": "", "lot": "Pack", "lot_size": "", "qty": qty,
            "price": 1, "amount": qty, "change_note": ""}


LINES = pd.DataFrame([_r(1, "08:10", "2PC - Apple Snacky", 559),
                      _r(2, "12:07", "2PC - Apple Snacky", 559, "Frozen")]).assign(_row=[2, 3])
PO = pd.DataFrame([{"indent_id": "IN-016", "version": 2, "po_customer": "Zepto", "kind": "po",
                    "po_number": "P6299502", "confirmed_at": "2026-11-19T12:07:28+05:30",
                    "po_qty_json": '{"2PC - Apple Snacky": 559, "250gm - Bloom Grapes Red globe": 52}'}])


def test_tracker_shows_po_only_items_in_red():
    pts = [("12:30", datetime(2026, 11, 19, 12, 30, tzinfo=config.IST))]
    rows = tracking.grid(indents.prepare(LINES), PO, "2026-11-19", pts)[0]["rows"]
    last = rows[-1]
    assert last["name"] == "250gm - Bloom Grapes Red globe" and last["po_only"] and last["po_kind"] == "bad"
    assert last["po"] == "Not on indent · PO 52" and last["cells"] == [("52", "(PO +52)", "up")]   # 26 Nov


def test_indent_vs_po_rows():
    rows = sheet_views.vs_rows(indents.prepare(LINES), PO, {})
    got = {r["Customer SKU Name"]: r for r in rows}
    assert got["2PC - Apple Snacky"]["Result"] == "Match"
    b = got["250gm - Bloom Grapes Red globe"]
    assert b["Result"] == "Not on indent" and b["PO qty"] == "52" and b["Diff"] == "+52"
    assert b["PO no"] == "P6299502" and b["PO at"] == "19-Nov 12:07" and b["Delivery"] == "19-Nov-2026"


def test_change_rows_only_item_changes_newest_first():
    log = pd.DataFrame([
        {"changed_at": "2026-11-19T09:35:58+05:30", "indent_id": "IN-016", "changed_by": "manoj_kumar@x.com",
         "change_type": "line_changed", "customer_sku_name": "2PC - Apple Snacky", "field": "qty",
         "old_value": "600", "new_value": "559"},
        {"changed_at": "2026-11-19T09:53:46+05:30", "indent_id": "IN-016", "changed_by": "v@x.com",
         "change_type": "line_added", "customer_sku_name": "1Pc - BLUEBERRY EA", "field": "",
         "old_value": "", "new_value": "parent=Blueberry; lot=Pcs; qty=80; price=1"},
        {"changed_at": "2026-11-19T12:07:28+05:30", "indent_id": "IN-016", "changed_by": "v@x.com",
         "change_type": "header_changed", "customer_sku_name": "", "field": "status",
         "old_value": "Submitted", "new_value": "Frozen"}])
    rows = sheet_views.change_rows(indents.prepare(LINES), log)
    assert [r["Change"] for r in rows] == ["added 80", "600 → 559"]
    assert rows[1]["By"] == "manoj_kumar" and rows[1]["Time"] == "19-Nov 09:35" and rows[1]["Customer"] == "Zepto"


def test_saves_rebuild_the_tabs(tmp_path, monkeypatch):
    from core.sheets import LocalBackend
    b = LocalBackend(tmp_path)
    b.ensure_tabs()
    monkeypatch.setattr(indents, "get_backend", lambda: b)
    b.append_dicts(PO_ITEM_MAP, [{"Customer": "Zepto", "PO Item Name": "x", "Customer SKU Name": "y"}])
    from core.models import IndentHeader
    from datetime import timedelta
    day = (config.now_ist().date() + timedelta(days=1)).isoformat()
    iid = indents.submit_new(IndentHeader(day, "B", "Zepto", "S", "10:30"), [_ln("1Pc - Hass", 5)], "a@x.com")
    vs = b.read(sheet_views.VS_TAB)
    assert list(vs["Indent"]) == [iid] and list(vs["Result"]) == ["No PO yet"]
    assert sheet_views.CHANGES_TAB in b.list_tabs()
