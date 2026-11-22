import pandas as pd

from core import mapping_sheet as ms

COMBO_COLS = ["City", "Customer", "Code", "Parent SKU", "SKU Name", "Packaging", "Customer Variety", "Customer Spec",
              "Customer Country", "Country", "Variety (Parent tab)", "Country Spec", "Origin Lot", "Note"]


def _combos(rows):
    return ms.combos_from(pd.DataFrame(rows, columns=COMBO_COLS))


def test_our_name_and_customers():
    assert ms.our_name("Apple Queen Imported - 2 pcs (250 - 300 g)", "2 pcs (250 - 300 g)") == "2PC - Apple Queen Imported"
    assert ms.our_name("Red Globe Grapes Imported - 200 g", "200 g") == "200GM - Red Globe Grapes Imported"
    assert ms.our_name("Bulk Royal Gala Apple 1.0 Piece", "1 Piece") == "1PC - Bulk Royal Gala Apple"
    assert ms.our_name("KIWI EA", "EA") == "1PC - KIWI"
    assert ms.our_name("ORANGE MANDARIN", "KG") == "1KG - ORANGE MANDARIN"
    assert ms.app_customer("Zepto (KWPL)") == "Zepto"
    assert ms.app_customer("Hyperpure CPC-BLR9") == "Zomato"
    assert ms.app_customer("Swiggy - Moksh Enterprises (MOKS)") == "Swiggy"
    assert ms.app_customer("Metro (Reliance Cash & Carry)") == "Metro"
    assert ms.ptp_city("Mumbai") == "PTP Mumbai" and ms.ptp_city("PTP Mumbai") == "PTP Mumbai"


ROWS = [
    ["Bangalore", "Zepto (KWPL)", "1", "Apple", "Apple Royal Gala Imported - 2 pcs", "2 pcs", "Gala", "110, 120",
     "Any country", "NewZealand", "Gala HG", "80c, 90c, 100c", "17.5 kg", ""],
    ["Bangalore", "Zepto (KWPL)", "1", "Apple", "Apple Royal Gala Imported - 2 pcs", "2 pcs", "Gala", "110, 120",
     "Any country", "Kashmir", "Gala PR", "60c", "8.5 kg", ""],
    ["Bangalore", "Zepto (KWPL)", "1", "Apple", "Apple Royal Gala Imported - 2 pcs", "2 pcs", "Gala", "110, 120",
     "Any country", "Kashmir", "Gala PR", "105c", "12.8 kg", ""],
    ["Bangalore", "Swiggy - Moksh Enterprises (MOKS)", "2", "Apple", "Apple Royal Gala Imported - 2 pcs", "2 pcs",
     "Gala", "", "Italy", "Italy", "Gala", "100c, 113c", "18 kg", ""],
    ["Bangalore", "Zepto (KWPL)", "3", "Kiwi", "Kiwi Sungold - 2 pcs", "2 pcs", "Kiwi", "", "Chile", "Chile",
     "Gold", "27mm, 30mm", "10 kg", ""],
]
PARENT = ms.parent_from(pd.DataFrame([["Avocado", "Hass", "Kenya", "18, 20", "4 kg"],
                                      ["Avocado", "Hass", "Tanzania", "20, 22", "4 kg"]],
                                     columns=["Parent SKU", "Variety", "Origin", "Spec", "Origin Lot"]))


def test_match_same_name_only_within_the_customer():
    c = _combos(ROWS)
    o = ms.options(c, PARENT, "PTP Bangalore", "Zepto", "2PC - Apple Royal Gala Imported", "Apple")
    assert list(o) == ["NewZealand · Gala HG", "Kashmir · Gala PR · 8.5 kg", "Kashmir · Gala PR · 12.8 kg"]
    assert o["NewZealand · Gala HG"]["spec"] == ["80", "90", "100"] and o["NewZealand · Gala HG"]["box_kg"] == 17.5
    assert o["Kashmir · Gala PR · 8.5 kg"]["spec"] == ["60"]
    assert "same name" in o["NewZealand · Gala HG"]["source"]
    s = ms.options(c, PARENT, "PTP Bangalore", "Swiggy", "2pc - apple royal gala imported", "Apple")
    assert list(s) == ["Italy · Gala"]                   # Swiggy's own rows, never Zepto's
    assert ms.options(c, PARENT, "PTP Mumbai", "Zepto", "2PC - Apple Royal Gala Imported", "Apple") == {}


def test_close_name_same_pack_and_parent_fallback():
    c = _combos(ROWS)
    o = ms.options(c, PARENT, "PTP Bangalore", "Zepto", "2PC - Sungold Kiwi", "Kiwi")
    assert list(o) == ["Chile · Gold"] and "close name" in o["Chile · Gold"]["source"]
    assert ms.options(c, PARENT, "PTP Bangalore", "Zepto", "3PC - Sungold Kiwi", "Kiwi") == {}   # other pack
    a = ms.options(c, PARENT, "PTP Bangalore", "Zepto", "1PC - Hass Avocado", "Avocado", "", "Tray")
    assert list(a) == ["Kenya · Hass", "Tanzania · Hass"] and a["Kenya · Hass"]["unit"] == "Tray"
    assert a["Kenya · Hass"]["source"].startswith("Parent tab")
