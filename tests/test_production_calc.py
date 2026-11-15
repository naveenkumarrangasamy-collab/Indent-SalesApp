import pandas as pd

from core.masters import masters_from_frames
from core.production_calc import batching, production, spec_mapping_list, unmapped
from core.schema import ACCESS, SKU_MAP, STORE_MAP, TABS, VARIETIES
from core import indents


def _masters():
    sku = pd.DataFrame([
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Tanzania", "20C, 22C", "Y", "", ""],
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Kenya", "20C, 22C", "N", "", ""],
        ["Bangalore", "Swiggy", "Avocado", "1PC - Nectar Avocado", "Tanzania", "20C, 22C", "Y", "", ""],
        ["Bangalore", "Zepto", "Kiwi", "2PC - Green Kiwi", "", "", "", "", ""],
        ["Bangalore", "Zepto", "Apple", "2PC - Apple Queen Imported", "", "", "Y", "Queen", ""],
        ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "China", "60", "", "", ""],
        ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "RSA", "2C", "", "", ""],
    ], columns=TABS[SKU_MAP])
    empty = {t: pd.DataFrame(columns=TABS[t]) for t in (STORE_MAP, VARIETIES, ACCESS)}
    return masters_from_frames({SKU_MAP: sku, **empty})


def _lines(rows):
    cols = TABS["Indent_Lines"]
    out = []
    for i, r in enumerate(rows):
        d = {c: "" for c in cols}
        d.update(r)
        d["_row"] = i + 2
        out.append(d)
    return indents.prepare(pd.DataFrame(out, columns=cols + ["_row"]))


BASE = dict(status="Submitted", delivery_date="2026-11-15", city="Bangalore", lot="Pcs", price="100")





def test_production_is_for_all_customers_one_row_per_sku_name():
    """All customers together, one line per customer SKU name (no customer names)."""
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="10"),           # other name, same spec
        dict(BASE, indent_id="C", version="1", customer="Zepto", store="S2", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="5", city="Chennai"),
    ])
    p = production(df, _masters())
    assert list(p.columns) == ["City", "Parent SKU", "Customer SKU Name", "Variety", "Lot", "Lot Size", "Spec",
                               "Total Qty"]
    blr = p[p["City"] == "Bangalore"]
    assert list(blr["Customer SKU Name"]) == ["1PC - Hass Avocado Imported", "1PC - Nectar Avocado"]
    assert list(blr["Total Qty"]) == [30, 10] and set(blr["Spec"]) == {"20C, 22C"}
    assert p[p["City"] == "Chennai"].iloc[0]["Total Qty"] == 5


def test_production_splits_by_lot_size_variety_and_spec_and_never_merges_unmapped():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Kiwi",
             customer_sku_name="2PC - Green Kiwi", qty="4"),                  # no spec mapped
        dict(BASE, indent_id="B", version="1", customer="Zepto", store="S2", parent_sku="Kiwi",
             customer_sku_name="3PC - Gold Kiwi", qty="6"),                   # no spec, other name
        dict(BASE, indent_id="B", version="1", customer="Zepto", store="S2", parent_sku="Apple",
             customer_sku_name="2PC - Apple Queen Imported", variety="Queen", qty="7"),
        dict(BASE, indent_id="B", version="1", customer="Zepto", store="S2", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="0"),       # qty 0 = nothing
    ])
    p = production(df, _masters()).set_index("Parent SKU")
    kiwi = p.loc["Kiwi"]
    assert len(kiwi) == 2 and all(s.startswith("spec not mapped") for s in kiwi["Spec"])
    assert p.loc["Apple", "Variety"] == "Queen" and p.loc["Avocado", "Total Qty"] == 30
    assert set(unmapped(df, _masters())["Customer SKU Name"]) == {"2PC - Green Kiwi", "3PC - Gold Kiwi",
                                                                  "2PC - Apple Queen Imported"}


def test_batching_per_delivery_point_adds_up_to_production():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Swiggy", store="WH1", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="40"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH2", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="15"),
        dict(BASE, indent_id="C", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
    ])
    b = batching(df, _masters())
    assert list(b["Delivery point"]) == ["WH1", "WH2", "S1"]
    assert list(b["Customer"]) == ["Swiggy", "Swiggy", "Zepto"] and list(b["Qty"]) == [40, 15, 30]
    assert b["Qty"].sum() == production(df, _masters())["Total Qty"].sum() == 85


def test_spec_mapping_list_shows_what_is_missing():
    lst = spec_mapping_list(_masters())
    hass = lst[(lst["Customer"] == "Zepto") & (lst["Customer SKU Name"] == "1PC - Hass Avocado Imported")].iloc[0]
    assert hass["Spec-Size"] == "20C, 22C" and hass["Active origin"] == "Tanzania"
    assert hass["To fill in"] == "Grade"
    kiwi = lst[lst["Customer SKU Name"] == "2PC - Green Kiwi"].iloc[0]
    assert kiwi["Spec used in production"] == "spec not mapped" and "Spec-Size" in kiwi["To fill in"]


def test_pdf_of_production_sheet():
    from core.pdf_report import table_pdf
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
                      customer_sku_name="1PC - Hass Avocado Imported", qty="30")])
    assert table_pdf("Production sheet", ["Delivery: → ₹"], production(df, _masters()))[:5] == b"%PDF-"
    assert table_pdf("Empty", [], production(_lines([]), _masters()))[:5] == b"%PDF-"
