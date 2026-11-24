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
