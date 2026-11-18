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
