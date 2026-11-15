import pandas as pd

from core.masters import masters_from_frames
from core.production_calc import batching, production, spec_mapping_list
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
    assert b["Qty"].sum() == production(df, _masters())["Qty"].sum() == 85


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


NEW_TAB = [["City", "Customer", "Parent SKU", "Customer SKU Name", "variety", "Spec-Repacking", "Spec-Size",
            "Spec-Origin"],
           ["Bangalore", "Zepto", "Avocado", "2PC - Hass Avocado", "Hass", "Punnet", "20C, 22C", "Tanzania"],
           ["Bangalore", "Swiggy", "Avocado", "2PC - Nectar Avocado", "Hass", "Punnet", "20C, 22C", "Tanzania"],
           ["Bangalore", "Swiggy", "Apple", "1Kg - nectr Royal Gala Apple", "Royal Gala", "Box", "80, 90", "Turkey"],
           ["Bangalore", "Zepto", "Apple", "2PC - Apple Queen Imported", "Queen", "Punnet", "90, 110", "Turkey"]]


def _base_masters():
    from core.importer import PROD_BASE, build_prod_base
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(NEW_TAB))
    assert m.has_prod_base and PROD_BASE == "New"
    return m


def test_production_from_new_tab_columns_and_club_total():
    """Columns from the New tab; Total clubs all customers per parent + repacking + size + lot size."""
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="2PC - Hass Avocado", lot="Pack", qty="10"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Avocado",
             customer_sku_name="2PC - Nectar Avocado", lot="Pack", qty="20"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Apple",
             customer_sku_name="1Kg - nectr Royal Gala Apple", lot="Kg", qty="700"),
        dict(BASE, indent_id="C", version="1", customer="Zepto", store="S2", parent_sku="Avocado",
             customer_sku_name="2PC - Hass Avocado", lot="Pack", qty="5", city="Chennai"),
    ])
    p = production(df, _base_masters())
    assert list(p.columns) == ["City", "Parent SKU", "Variety", "Spec-Origin", "Repacking", "Spec-Size",
                               "Lot Size", "Qty", "Total"]
    avo = p[(p["City"] == "Bangalore") & (p["Parent SKU"] == "Avocado")].iloc[0]
    assert (avo["Variety"], avo["Spec-Origin"], avo["Repacking"], avo["Spec-Size"], avo["Lot Size"]) == \
        ("Hass", "Tanzania", "Punnet", "20C, 22C", "2 Pcs")
    assert avo["Qty"] == 30 and avo["Total"] == "30 Punnet"
    apple = p[p["Parent SKU"] == "Apple"].iloc[0]
    assert apple["Repacking"] == "Box" and apple["Qty"] == 700 and apple["Total"] == "700 Box"
    chn = p[p["City"] == "Chennai"].iloc[0]      # not in the New tab for Chennai: kept apart
    assert chn["Spec-Size"].startswith("not in New tab") and chn["Qty"] == 5


def test_production_total_clubs_across_varieties_same_pack():
    """Different varieties keep their own rows; Total adds them when repacking, size and lot size match."""
    tab = NEW_TAB + [["Bangalore", "Zepto", "Apple", "2PC - Apple Gala Imported", "Gala", "Punnet", "90, 110",
                      "Turkey"]]
    from core.importer import build_prod_base
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(tab))
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Apple",
             customer_sku_name="2PC - Apple Queen Imported", lot="Pack", qty="12"),
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Apple",
             customer_sku_name="2PC - Apple Gala Imported", lot="Pack", qty="8"),
    ])
    p = production(df, m)
    assert len(p) == 2 and set(p["Qty"]) == {12, 8} and set(p["Total"]) == {"20 Punnet"}
    from core.production_calc import not_in_base
    assert not_in_base(df, m).empty


def test_not_in_new_tab_listed():
    from core.production_calc import not_in_base
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Kiwi",
                      customer_sku_name="2PC - Green Kiwi", qty="4")])
    gaps = not_in_base(df, _base_masters())
    assert list(gaps["Customer SKU Name"]) == ["2PC - Green Kiwi"]


def test_new_tab_read_from_sheet_values():
    from core.masters import frames_from_values, masters_from_frames
    frames, src = frames_from_values({"New": NEW_TAB})
    m = masters_from_frames(frames, src)
    info = m.prod_info("bangalore", "SWIGGY", "1kg - nectr  royal gala apple")
    assert info["Repacking"] == "Box" and info["Spec-Origin"] == "Turkey" and info["Variety"] == "Royal Gala"

