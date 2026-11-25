"""24 Nov: a PO uploaded as Excel / CSV is read like a PDF PO (item + qty)."""
import io

import pandas as pd

from pages_src.indent_actions import read_sheet


def _xlsx(df):
    b = io.BytesIO()
    df.to_excel(b, index=False)
    return b.getvalue()


def test_excel_po_lines():
    df = pd.DataFrame({"Item Name": ["Kiwi Green - 3 pcs", "Avocado Hass - 1 pc"], "Qty": [40, 25]})
    r = read_sheet(_xlsx(df), "xlsx")
    assert [(x.name, x.qty) for x in r.lines] == [("Kiwi Green - 3 pcs", 40), ("Avocado Hass - 1 pc", 25)]


def test_csv_po_lines_and_bad_file():
    r = read_sheet(b"Product Name,Quantity\nBlueberry 125g,12\n", "csv")
    assert r.lines[0].qty == 12
    bad = read_sheet(b"not a sheet", "xlsx")
    assert not bad.lines and bad.checks


def test_po_progress_pending_done_extra():
    from types import SimpleNamespace as L
    from core import indents
    lines = [L(customer_sku_name="2PC - Kiwi", qty=10), L(customer_sku_name="1PC - Avocado", qty=5),
             L(customer_sku_name="125gm - Blueberry", qty=4)]
    earlier = [{"number": "MBF1", "at": "", "by": "", "qty": {"2PC - Kiwi": 6}},
               {"number": "MBF2", "at": "", "by": "", "qty": {"1PC - Avocado": 7, "1Kg - Plum": 2}}]
    rows = {r["name"]: r for r in indents.po_progress(lines, earlier, {"2PC - Kiwi": 4})}
    assert rows["2PC - Kiwi"]["pending"] == 0 and rows["2PC - Kiwi"]["pos"] == [6, None]
    assert rows["1PC - Avocado"]["pending"] == -2          # extra 2
    assert rows["125gm - Blueberry"]["pending"] == 4       # nothing yet
    assert rows["1Kg - Plum"]["indent"] is None            # only on a PO


def test_swiggy_bangalore_same_fruit_match():
    from types import SimpleNamespace as N
    from pages_src.indent_actions import fruit_match_on, same_fruit
    lines = [N(parent_sku="Avocado", customer_sku_name="1Pc - Imported Avocado", qty=186),
             N(parent_sku="Avocado", customer_sku_name="1PC - Nectar Avocado", qty=400),
             N(parent_sku="Blueberry", customer_sku_name="1Box - Imported Blueberry", qty=120)]
    assert fruit_match_on("Swiggy", "PTP Bangalore") and not fruit_match_on("Swiggy", "PTP Hyderabad")
    assert not fruit_match_on("Zepto", "PTP Bangalore")
    assert same_fruit("Bulk Semiripe Imported Avocado 1.00 Piece", lines, set()) == "1Pc - Imported Avocado"
    assert same_fruit("Unripe Avocado", lines, set()) == "1PC - Nectar Avocado"          # no word shared: biggest
    assert same_fruit("Unripe Avocado", lines, {"1pc - nectar avocado"}) == "1Pc - Imported Avocado"
    assert same_fruit("Longan 100 g", lines, set()) is None


def test_same_fruit_blueberry_plural():
    from types import SimpleNamespace as N
    from pages_src.indent_actions import same_fruit
    lines = [N(parent_sku="Blueberry", customer_sku_name="1Box - Imported Blueberry", qty=120)]
    assert same_fruit("Bulk PP Blueberry 1 Box", lines, set()) == "1Box - Imported Blueberry"
    assert same_fruit("Imported Blueberries 125 g", lines, set()) == "1Box - Imported Blueberry"


def test_same_fruit_variety_and_qty():
    """25 Nov: Swiggy BLR PO gives 'Fuji' (no 'Apple') or an apple name close to the Fuji qty."""
    from types import SimpleNamespace as N
    from pages_src.indent_actions import same_fruit
    lines = [N(parent_sku="Apple", customer_sku_name="1Pc - Apple Fuji", variety="Fuji", qty=232),
             N(parent_sku="Apple", customer_sku_name="1Kg - Nectr Royal Gala", variety="Gala", qty=600),
             N(parent_sku="Kiwi", customer_sku_name="1Pc - Green Kiwi", variety="", qty=300)]
    assert same_fruit("Fuji 1 Pc", lines, set()) == "1Pc - Apple Fuji"
    assert same_fruit("Bulk Imported Apple Fuji 1.00 Piece", lines, set(), 232) == "1Pc - Apple Fuji"
    assert same_fruit("Imported Apple 1 Piece", lines, set(), 230) == "1Pc - Apple Fuji"      # qty closest
    assert same_fruit("Imported Apple 1 Kg", lines, set(), 590) == "1Kg - Nectr Royal Gala"
    assert same_fruit("Longan 100 g", lines, set(), 232) is None
