"""24 Nov: consolidated estimate — every customer clubbed, boxes per variety · country · count."""
import pandas as pd

from core import preprod


def _dem():
    rows = [
        # Zepto and Swiggy both want Gala apples (pcs) allowed at 90/100
        {"city": "PTP Bangalore", "group": "Zepto", "customer_sku_name": "2PC - Snacky Apple", "parent_sku": "Apple",
         "variety": "Gala", "unit": "pcs", "need": 900},
        {"city": "PTP Bangalore", "group": "Swiggy", "customer_sku_name": "1PC - Daily Apple", "parent_sku": "Apple",
         "variety": "Gala", "unit": "pcs", "need": 100},
        {"city": "PTP Bangalore", "group": "Swiggy", "customer_sku_name": "4PC - Snacky Apple", "parent_sku": "Apple",
         "variety": "", "unit": "pcs", "need": 40},
        {"city": "PTP Bangalore", "group": "Zepto", "customer_sku_name": "125gm - Blueberry", "parent_sku": "Blueberry",
         "variety": "", "unit": "punnets", "need": 30},
    ]
    return pd.DataFrame(rows)


def _opts(r):
    if r["parent_sku"] == "Apple":
        return {"NewZealand · Gala": {"spec": ["90", "100"], "unit": "Box", "box_kg": 18.0,
                                      "country": "NewZealand", "grade": "Gala"}}
    return {"Peru": {"spec": ["Any size"], "unit": "Tray", "box_kg": None, "country": "Peru", "grade": ""}}


def test_clubbed_per_count_and_variety_missing_apart():
    out = dict(preprod.consolidated(_dem(), _opts, lambda p: p == "Apple"))
    apple = out["Apple · PTP Bangalore"]
    gala = apple.iloc[0]
    assert gala["Variety · country"] == "Gala · NewZealand"
    assert gala["Boxes at each count"] == "90C · 6 | 100C · 5"     # 500 pcs at each count
    assert gala["Total"] == "11 Box" and gala["SKUs · customers"] == "2 · 2"
    assert apple.iloc[-1]["Variety · country"] == preprod.NO_VARIETY
    blue = out["Blueberry · PTP Bangalore"].iloc[0]
    assert blue["Total"] == "3 Tray"


def test_demand_by_variety_splits_rows():
    lines = pd.DataFrame([
        {"city": "PTP Bangalore", "customer": "Swiggy", "store": "Swiggy WH1", "customer_sku_name": "1PC - Daily Apple",
         "parent_sku": "Apple", "variety": "Gala", "lot": "Pcs", "qty": 10, "indent_id": "IN-1"},
        {"city": "PTP Bangalore", "customer": "Swiggy", "store": "Swiggy WH2", "customer_sku_name": "1PC - Daily Apple",
         "parent_sku": "Apple", "variety": "Queen", "lot": "Pcs", "qty": 5, "indent_id": "IN-2"},
    ])
    assert len(preprod.demand(lines)) == 1
    assert sorted(preprod.demand(lines, by_variety=True)["variety"]) == ["Gala", "Queen"]


def test_batching_indent_and_po_qty():
    from core.production_calc import merge_sheet, sheet_rows, with_po
    row = {"City": "PTP Bangalore", "Customer": "Zepto", "Delivery point": "S1", "Parent SKU": "Kiwi",
           "Variety": "", "Lot": "Pack", "Lot Size": "3 Pcs", "Spec": ""}
    bat = pd.DataFrame([
        {**row, "Customer SKU Name": "3PC - Green Kiwi", "Qty": 10, "Indent": "IN-1"},
        {**row, "Customer SKU Name": "2PC - Kiwi Sungold", "Qty": 5, "Indent": "IN-1"},
        {**row, "Customer SKU Name": "1PC - Avocado", "Qty": 8, "Indent": "IN-1"},
        {**row, "Customer SKU Name": "1PC - Hass", "Qty": 4, "Indent": "IN-1"},
        {**row, "Customer": "Swiggy", "Delivery point": "WH1", "Customer SKU Name": "3PC - Green Kiwi", "Qty": 7,
         "Indent": "IN-2"},
    ])
    po = {("IN-1", "3pc - green kiwi"): 12, ("IN-1", "2pc - kiwi sungold"): None, ("IN-1", "1pc - avocado"): 6,
          ("IN-1", "1pc - hass"): 4}
    extra = [{"City": "PTP Bangalore", "Customer": "Zepto", "Delivery point": "S1",
              "Customer SKU Name": "1Kg - Plum", "PO qty": 3}]
    v = with_po(bat, po, {"IN-1"}, extra)
    assert "Indent" not in v.columns and list(v.columns)[-4:] == ["Indent qty", "PO qty", "Difference", "Status"]
    st = dict(zip(v["Customer SKU Name"] + "|" + v["Customer"], v["Status"]))
    assert st["3PC - Green Kiwi|Zepto"] == "PO higher" and st["2PC - Kiwi Sungold|Zepto"] == "Not on PO"
    assert st["1PC - Avocado|Zepto"] == "PO lower" and st["1PC - Hass|Zepto"] == "Match"
    assert st["3PC - Green Kiwi|Swiggy"] == "No PO yet" and st["1Kg - Plum|Zepto"] == "Not on indent"
    rows = sheet_rows(v, "2026-11-25", "now")
    hi = next(r for r in rows if r[5] == "3PC - Green Kiwi" and r[2] == "Zepto")
    assert hi[10:14] == [10, 12, 2, "PO higher"]
    assert next(r for r in rows if r[13] == "No PO yet")[11] == ""
    merged = merge_sheet([["old title"]], rows, "2026-11-25", {"PTP Bangalore"})
    assert len(merged) == 7
    assert len(merge_sheet(merged, rows[:1], "2026-11-25", {"PTP Bangalore"})) == 2
    assert len(merge_sheet(merged, [], "2026-11-26", {"PTP Bangalore"})) == 7
