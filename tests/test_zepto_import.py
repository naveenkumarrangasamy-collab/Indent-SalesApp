import io

import openpyxl

from core import po_reader, zepto_import


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_read_and_match_zepto_file():
    data = _xlsx([["Product Name", "UOM", "EAN", "Pack Date", "Use Date", "HSK New Final", "HSK old Final",
                   "NLM Final", "Summation"],
                  ["Apple Queen Imported", "2 PIECE", 40020405, "17/11/2026", 22, 0, 7, 3, 10],
                  ["Litchi Imported (Longan)", "200 GRAM", 350000422, "17/11/2026", 19, 0, 469, 0, 469]])
    zf = zepto_import.read(data)
    assert zf.pack_date == "2026-11-17"
    assert zf.qty == {"HSK New Final": [0, 0], "HSK old Final": [7, 469], "NLM Final": [3, 0]}
    assert [(p.name, p.code, p.qty) for p in zf.products] == [
        ("Apple Queen Imported - 2 PIECE", "40020405", 10), ("Litchi Imported (Longan) - 200 GRAM", "350000422", 469)]
    po_reader.match(zf.products, ["2PC - Apple Queen Imported", "200gm - Litchi Imported (Longan)"])
    assert [p.sku for p in zf.products] == ["2PC - Apple Queen Imported", "200gm - Litchi Imported (Longan)"]
    stores = ["Zepto - Yalachanayakanapura", "Zepto - Nelamangala", "Zepto - Nelamgala (New)"]
    assert zepto_import.guess_store("HSK old Final", stores) == "Zepto - Yalachanayakanapura"
    assert zepto_import.guess_store("NLM Final", stores) == "Zepto - Nelamangala"
