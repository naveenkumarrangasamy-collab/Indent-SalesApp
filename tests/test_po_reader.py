from core import po_reader as r

ZEPTO_TABLE = [
    ["Sr.", "Material Code", "Item Description", None, "SKU Code", "Quantity", "MRP/RSP", "Unit Base\nCost",
     "Taxable\nValue INR"],
    [None, None, None, None, None, None, None, None, None],
    ["1", "412245", "Litchi Imported (Longan) - 200 g", None, "x", "464", "110.00", "50.00", "23200.00"],
    ["2", "110975", "Avocado Hass Imported - 1 pc (160 - 200\ng)", None, "y", "152", "90.00", "53.90", "8192.80"],
    ["3", "115122", "Blueberry Imported - 120 - 130 g", None, "z", "82", "363.00", "195.00", "15990.00"],
    ["4", "189585", "Snacky Avocado Regular - 1 pc (120 - 150 g)", None, "w", "247", "40", "49.30", "12177.10"],
    ["Total Taxable Amount (INR)", None, None, None, None, None, None, None, "59559.90"],
]
OURS = ["200gm - Litchi Imported (Longan)", "1PC - Hass Avocado Imported", "1PC - Blueberry Imported",
        "1PC - Bloom Blueberry Imported", "2PC - Bloom Kiwi Sungold Imported (New Zealand)",
        "3PC - Bloom Kiwi Sungold Imported (New Zealand)", "1PC - Snacky Avocado Imported"]


def test_table_lines_exact_numbers():
    lines = r._table_lines(ZEPTO_TABLE)
    assert [(x.code, x.qty, x.value) for x in lines] == [
        ("412245", 464, 23200.0), ("110975", 152, 8192.8), ("115122", 82, 15990.0), ("189585", 247, 12177.1)]


def test_match_by_name_pack_and_map():
    lines = r.match(r._table_lines(ZEPTO_TABLE), OURS, {"189585": "1PC - Snacky Avocado Imported"})
    got = {x.code: (x.sku, x.how) for x in lines}
    assert got["412245"] == ("200gm - Litchi Imported (Longan)", "name")
    assert got["110975"] == ("1PC - Hass Avocado Imported", "name")         # word order differs
    assert got["115122"] == ("1PC - Blueberry Imported", "name")            # weight range is not a pack
    assert got["189585"] == ("1PC - Snacky Avocado Imported", "map")


def test_pack_picks_right_count():
    x = r.POLine("Bloom Kiwi Sungold Imported (New Zealand) - 3 pcs (200 - 250 g)", 5)
    assert r.match([x], OURS)[0].sku == "3PC - Bloom Kiwi Sungold Imported (New Zealand)"


def test_flipkart_style_table_and_store_hint():
    lines = r._table_lines([["ITEM", "QUANTITY", "UNIT PRICE", "SUB-TOTAL"],
                            ["Avocado Pcs - FK - Grade A", "523.00 Pcs", "Rs. 65.00", "Rs. 33995.00"]])
    assert lines[0].qty == 523 and lines[0].unit_cost == 65 and lines[0].value == 33995
    pre = {"Swiggy WH1": "M", "Swiggy WH2": "B"}
    assert r.store_hint("MBFPO177755", pre) == "Swiggy WH1" and r.store_hint("BBFPO1", pre) == "Swiggy WH2"
    assert r._po_number("PO No : MBFPO177755\nPO Date") == "MBFPO177755"
