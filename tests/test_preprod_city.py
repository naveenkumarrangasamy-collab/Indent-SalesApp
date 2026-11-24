import pandas as pd

from core import preprod_city as pc


def v(cust, parent, sku, var, lot, spec, ind, po, status):
    return {"City": "PTP Bangalore", "Customer": cust, "Delivery point": cust, "Parent SKU": parent,
            "Customer SKU Name": sku, "Variety": var, "Lot": lot, "Lot Size": "", "Spec": spec,
            "Indent qty": ind, "PO qty": po, "Difference": None, "Status": status}


VIEW = pd.DataFrame([
    v("Zepto", "Apple", "2PC - Apple Royal Gala Imported", "Gala", "Pcs", "120", 282, 282, "Match"),
    v("Zepto", "Apple", "2PC - Snacky Apple", "Gala", "Pcs", "163C, 175C", 806, 806, "Match"),
    v("Swiggy", "Apple", "1Kg - Nectr gala apple Large", "Gala", "Kg", "mapping not done (x)", 130, None,
      "No PO yet"),
    v("Zepto", "Apple", "2PC - Apple Queen Imported", "Queen", "Pcs", "120", 3, 3, "Match"),
    v("Flipkart", "Blueberry", "1Pc - Blueberry - FK", "", "Pcs", "16mm", 170, 170, "Match"),
    v("Zepto", "Blueberry", "125gm - Blueberry Imported", "", "Pack", "16mm", 78, 78, "Match"),
    v("Swiggy", "", "1PC - nectr Blueberry", "", "", "", 0, 173, "Not on indent"),
    v("Bigbasket", "Kiwi", "2Pc - Kiwi", "", "Pcs", "not in New tab (2Pc - Kiwi)", 1000, 500, "PO lower"),
    v("Swiggy", "Kiwi", "1Pc - Green Kiwi", "", "Pcs", "36", 300, 300, "Match"),
    v("Zepto", "Kiwi", "2PC - Gone Kiwi", "", "Pcs", "36", 10, None, "Not on PO"),
])


def rows():
    return {r["key"]: r for r in pc.demand(VIEW, lambda p: p == "Apple")}


def test_apple_per_variety_and_unit_blueberry_one_punnet_line():
    r = rows()
    assert r["Apple|Gala|pcs"]["need"] == 282 * 2 + 806 * 2
    assert r["Apple|Gala|kg"]["need"] == 130
    assert r["Apple|Queen|pcs"]["need"] == 6
    b = r["Blueberry||punnets"]
    assert b["need"] == 170 + 78 + 173 and b["customers"] == ["Flipkart", "Swiggy", "Zepto"]


def test_need_from_po_not_on_po_dropped_and_notes():
    k = rows()["Kiwi||pcs"]
    assert k["need"] == 500 * 2 + 300          # Bigbasket from the PO, the item not on the PO left out
    assert k["asked"] == {"spec not set": 1000, "36mm": 300}
    assert any("Bigbasket" in n for n in k["notes"])


def test_suggestion_from_asked_counts():
    g = rows()["Apple|Gala|pcs"]
    txt, lo, hi = pc.suggest(g, [])
    assert (lo, hi) == (5 + 10, 5 + 10) and "Box" in txt
    b = rows()["Blueberry||punnets"]
    assert pc.suggest(b, [])[0] == "36 Tray"


def test_options_labels_and_boxes():
    parent = pd.DataFrame([{"parent": "Apple", "grade": "Gala HG", "country": "New Zealand", "spec": "90, 100",
                            "lot": "18 kg", "box_kg": 18.0},
                           {"parent": "Apple", "grade": "Queen", "country": "NZ", "spec": "100",
                            "lot": "18 kg", "box_kg": 18.0}])
    o = pc.options(parent, "Apple", "Gala")
    assert [x["label"] for x in o] == ["New Zealand · Gala HG · 90C · 18 kg", "New Zealand · Gala HG · 100C · 18 kg"]
    took = {"New Zealand · Gala HG · 90C · 18 kg": 20, "New Zealand · Gala HG · 100C · 18 kg": 12}
    assert pc.in_boxes(took, o, "pcs", "Apple") == (3000.0, True)
    assert pc.in_boxes(took, o, "kg", "Apple") == (32 * 18.0, True)
    assert pc.status(3050, 3000, True, True) == "Short"


def test_taken_sums_rounds_for_the_city_group():
    df = pd.DataFrame([{"delivery_date": "2026-11-24", "city": "PTP Bangalore", "group": pc.CITY_GROUP,
                        "customer_sku_name": "Apple|Gala|pcs", "country": "A", "boxes": "3"},
                       {"delivery_date": "2026-11-24", "city": "PTP Bangalore", "group": pc.CITY_GROUP,
                        "customer_sku_name": "Apple|Gala|pcs", "country": "A", "boxes": "2"},
                       {"delivery_date": "2026-11-24", "city": "PTP Bangalore", "group": "Zepto",
                        "customer_sku_name": "Apple|Gala|pcs", "country": "A", "boxes": "9"}])
    assert pc.taken(df, "2026-11-24", "PTP Bangalore") == {"Apple|Gala|pcs": {"A": 5.0}}
