from core import dispatch_sync as ds


def row(day, cust, point, sku, ind, po, diff, status, var=""):
    vals = [day, "PTP Bangalore", "PTP_Cheemchandra", cust, point, "Kiwi", sku, var, "Pcs", "2 Pcs", "33mm", ind, po, diff]
    return {"key": ds.key(day, cust, point, sku, var), "values": vals, "status": status}


def test_new_rows_go_under_last_used_and_existing_only_update():
    d = ds.serial("2026-11-24")
    existing = ds.widen([[d, "PTP Bangalore", "Swiggy", "Swiggy WH2", "Kiwi", "2PC - Kiwi", "", "Pcs", "2 Pcs", "33mm", 10, "", ""],
                [d, "PTP Bangalore", "Zepto", "Zepto - A", "Kiwi", "1Pack - Kiwi", "", "Pcs", "2 Pcs", "33mm", 5, 5, 0],
                ["", "", "", "", "", "", "", "", "", "", "", "", ""]])
    new = [row("2026-11-24", "Swiggy", "Swiggy WH2", "2PC - Kiwi", 10, 8, -2, "PO lower"),
           row("2026-11-24", "Zepto", "Zepto - A", "1Pack - Kiwi", 5, 5, 0, "Match"),
           row("2026-11-24", "Trent", "Trent", "1Pc Blueberry Pack", 375, "", "", "No PO yet")]
    p = ds.plan(existing, new, {d}, {"ptp bangalore"})
    assert [(r, s) for r, _, s in p["update"]] == [(2, "PO lower"), (3, "Match")]   # facility filled in
    assert p["append_at"] == 4 and len(p["append"]) == 1
    assert p["append"][0][0][3] == "Trent"


def test_item_gone_from_indent_keeps_row_with_zero():
    d = ds.serial("2026-11-24")
    existing = ds.widen([[d, "PTP Bangalore", "More", "More_BLR", "Kiwi", "2PC - Kiwi", "", "Pcs", "2 Pcs", "33mm", 10, "", ""]])
    p = ds.plan(existing, [], {d}, {"ptp bangalore"})
    (r, vals, status), = p["update"]
    assert r == 2 and vals[11] == 0 and vals[13] == "" and status == ""
    assert not p["append"]


def test_other_days_and_cities_untouched():
    d = ds.serial("2026-11-20")
    existing = ds.widen([[d, "PTP Bangalore", "More", "More_BLR", "Kiwi", "2PC - Kiwi", "", "Pcs", "2 Pcs", "33mm", 10, "", ""]])
    p = ds.plan(existing, [], {ds.serial("2026-11-24")}, {"ptp bangalore"})
    assert not p["update"] and not p["append"]


def test_serial_reads_iso_and_numbers():
    assert ds.serial("2026-11-24") == ds.serial(46350) or ds.serial("2026-11-24") > 46000
    assert ds.serial(46350.0) == 46350


def test_facility_column_layouts():
    assert ds.has_facility(["Date", "City", "Facility", "Customer"]) and not ds.has_facility(["Date", "City", "Customer"])
    assert ds.widen([[1, "PTP Bangalore", "More", "x"]]) == [[1, "PTP Bangalore", "", "More", "x"]]
