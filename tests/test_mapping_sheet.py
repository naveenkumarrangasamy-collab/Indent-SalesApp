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
PARENT = ms.parent_from(pd.DataFrame([["Blueberry", "Blueberry", "Peru", "14mm", "12 pcs tray"],
                                      ["Avocado", "Hass", "Kenya", "18, 20", "4 kg"],
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


def test_lot_in_pieces_is_not_a_box_weight():
    b = ms.options(_combos([]), PARENT, "PTP Bangalore", "Zepto", "125GM - Blueberry", "Blueberry")
    assert list(b) == ["Peru"] and b["Peru"]["box_kg"] is None and b["Peru"]["spec"] == ["14mm"]


def test_customer_sku_name_column_wins():
    cols = COMBO_COLS[:5] + ["Customer SKU Name"] + COMBO_COLS[5:]
    row = ["Bangalore", "Flipkart Brigade_Cheemasandra", "1", "Blueberry", "Blueberry (125 gm Pack) (PCS) - FK",
           "1PC - Blueberry - FK", "125 g", "Blueberry", "", "Peru", "Peru", "Blueberry", "14mm", "12 pcs tray", ""]
    c = ms.combos_from(pd.DataFrame([row], columns=cols))
    assert list(c["our"]) == ["1PC - Blueberry - FK"]
    o = ms.options(c, PARENT, "PTP Bangalore", "Flipkart", "1Pc - Blueberry - FK", "Blueberry")
    assert list(o) == ["Peru"] and "same name" in o["Peru"]["source"]


def test_counts_are_customer_spec_and_country_spec():
    rows = [
        ["Bangalore", "Flipkart X", "9", "Avocado", "Avocado - FK", "1 pc", "Hass", "18, 20, 22", "Tanzania, Kenya",
         "Tanzania", "Hass", "12C, 14C, 16C, 18C, 20C, 22C, 24C", "4 kg", ""],
        ["Bangalore", "Flipkart X", "9", "Avocado", "Avocado - FK", "1 pc", "Hass", "18, 20, 22", "Tanzania, Kenya",
         "Kenya", "Fuerte", "26C, 28C", "4 kg", ""],
        ["Bangalore", "Zepto (KWPL)", "8", "Mandarin", "Mini Orange - 200-250 g", "200-250 g", "", "3C, 50mm, 100C, 113C",
         "", "Australia", "Afourer", "88C, 100C, 113C", "9 kg", ""],
        ["Bangalore", "Zepto (KWPL)", "8", "Mandarin", "Mini Orange - 200-250 g", "200-250 g", "", "3C, 50mm, 100C, 113C",
         "", "China", "Mandarin", "50mm, 55mm", "10 kg", ""],
    ]
    c = _combos(rows)
    fk = ms.options(c, None, "PTP Bangalore", "Flipkart", "1PC - Avocado - FK", "Avocado")
    assert list(fk) == ["Tanzania · Hass"] and fk["Tanzania · Hass"]["spec"] == ["18", "20", "22"]   # Kenya has none of them
    mo = ms.options(c, None, "PTP Bangalore", "Zepto", "250GM - Mini Orange", "Mandarin")
    specs = {v["country"]: v["spec"] for v in mo.values()}
    assert specs == {"Australia": ["100", "113"], "China": ["50mm"]}
    assert ms.allowed(["20", "22"], []) == ["20", "22"] and ms.allowed([], ["18"]) == ["18"]


def test_sku_rows_add_each_new_name_once():
    old = pd.DataFrame([{"City": "PTP Bangalore", "Customer": "Zepto", "Parent SKU": "Kiwi",
                         "Customer SKU Name": "2PC - Kiwi Sungold", "Spec-Origin": "Chile", "Spec-Size": "",
                         "Active": "Y", "Variety": "", "Lot": "", "_row": 2}])
    c = _combos(ROWS)
    out = ms.sku_rows(c, old)
    z = out[(out["Customer"] == "Zepto")]
    assert sorted(z["Customer SKU Name"]) == ["2PC - Apple Royal Gala Imported", "2PC - Kiwi Sungold"]
    assert len(out) == 3 and list(out.columns) == list(old.columns)      # Swiggy's Gala added too
    assert ms.sku_rows(c.iloc[0:0], old) is old


def test_box_range():
    from core import preprod
    o = {"T": {"spec": ["18", "20", "22"], "unit": "Tray", "box_kg": 4.0}}
    assert preprod.box_range(300, "pcs", o) == "≈ 14–17 Tray"
    assert preprod.box_range(40, "kg", o) == "≈ 10 Tray"
    assert preprod.box_range(119, "packs", {}, "Blueberry") == "≈ 10 Tray"
    assert preprod.box_range(10, "packs", o) == "-"
