import io

import openpyxl

from core import master_add, order_reader


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_generic_excel_with_total():
    r = order_reader.read("o.xlsx", _xlsx([["Item", "UOM", "Qty"], ["Apple Fuji Imported", "2 PIECE", 8],
                                          ["Mango", "1 PIECE", 5], ["Total", "", 13]]))
    assert [(x.name, x.qty) for x in r.lines] == [("Apple Fuji Imported - 2 PIECE", 8), ("Mango - 1 PIECE", 5)]
    assert r.total == 13 and r.read_total == 13


def test_zepto_excel_uses_the_store_column():
    data = _xlsx([["Product Name", "UOM", "EAN", "HSK old Final", "NLM Final", "Summation"],
                  ["Kiwi Green", "3 PIECE", 1, 140, 10, 150]])
    r = order_reader.read("z.xlsx", data, store="Zepto - Yalachanayakanapura")
    assert [(x.name, x.qty) for x in r.lines] == [("Kiwi Green - 3 PIECE", 140)]


def test_new_items_parent_and_name():
    parents = ["Apple", "Avocado", "Kiwi", "Garlic"]
    assert master_add.guess_parent("Apple Fuji Imported - 2 PIECE", parents) == "Apple"
    assert master_add.guess_parent("Garlic Peeled - 200 GRAM", parents) == "Garlic"
    assert master_add.guess_parent("Mango Imported - 1 PIECE", parents) == ""      # new parent: not added
    assert master_add.new_sku_name("Apple Fuji Imported - 2 PIECE") == "2PC - Apple Fuji Imported"
    assert master_add.new_sku_name("Garlic Peeled - 200 GRAM") == "200gm - Garlic Peeled"


def test_zepto_po_column_format_with_packsize_and_unlabelled_total():
    data = _xlsx([[None, None, "ZEPTO INDENT"], [None, "PRODUCT NAME", "PO", "UOM", "GRAMS", "packsize"],
                  [None, "Kiwi Sungold", 44, "PIECE", 225, 2], [None, "Blueberry Imported", 47, "GRAM", 125, 125],
                  [None, "Bloom Grapefruit", 0, "PIECE", 400, 1], [None, None, 91]])
    r = order_reader.read("z.xlsx", data)
    assert [(x.name, x.qty) for x in r.lines] == [("Kiwi Sungold - 2 PIECE", 44), ("Blueberry Imported - 125 GRAM", 47)]
    assert r.total == 91


def test_new_sku_name_swiggy_style():
    from core.master_add import new_sku_name
    assert new_sku_name("Longan 100.0 g") == "100gm - Longan"
    assert new_sku_name("Bulk Semiripe Imported Avocado 1.0 Piece") == "1PC - Bulk Semiripe Imported Avocado"
    assert new_sku_name("Bulk PP Royal Gala Apple 1.0 kg") == "1Kg - Bulk PP Royal Gala Apple"
    assert new_sku_name("BULK GREEN KIWI 1.0 Pack") == "1Pack - BULK GREEN KIWI"
