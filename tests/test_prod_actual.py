import pandas as pd

from core import prod_actual as pa


def test_clean_size_and_count():
    assert pa.clean_size("30 C") == "30C"
    assert pa.clean_size("24c") == "24C"
    assert pa.clean_size("16 mm") == "16mm"
    assert pa.clean_size("22 mm+ dia") == "22mm+"
    assert pa.count_of("88 C") == 88
    assert pa.count_of("16mm") is None


def test_options_seed_parent_tab_and_saved_brand():
    parent_tab = pd.DataFrame([{"parent": "Apple", "grade": "Gala", "country": "NZ", "spec": "90, 100",
                                "lot": "18 Kg", "box_kg": 18.0}])
    saved = pd.DataFrame([{"parent_sku": "Apple", "origin": "NZ", "variety": "Gala", "brand": "Kiwi Crunch",
                           "size": "100C", "box_kg": "18", "pcs_per_box": "100"}])
    brand_tab = pd.DataFrame(pa.brand_rows_from_seed())
    df = pa.option_rows("Apple", parent_tab, saved, brand_tab)
    assert "NZ" in pa.choices(df, "origin")
    assert pa.brands(df, "NZ", "Gala", "30C") == ["Envy"]
    assert pa.brands(df, "NZ", "Gala", "100C") == ["Kiwi Crunch"]
    assert pa.brands(df, "Italy", "Gala", "90C") == []
    assert "90C" in pa.choices(df, "size", origin="NZ", variety="Gala")
    kg, pcs = pa.defaults(df, origin="NZ", variety="Gala", size="90C")
    assert (kg, pcs) == (18.0, 90)
    mand = pa.option_rows("mandrin", None, None, brand_tab)
    assert pa.brands(mand, "Australia", "", "80C") == ["Gold Fresh"]
    kiwi = pa.option_rows("Kiwi", None, None, brand_tab)
    assert pa.brands(kiwi, "NZ", "Gold", "") == ["Zespri"]      # blank origin / size in the row = any


def test_options_only_for_picked_country_and_variety():
    parent_tab = pd.DataFrame([
        {"parent": "Apple", "grade": "Gala", "country": "NZ", "spec": "90, 100", "lot": "", "box_kg": 18.0},
        {"parent": "Apple", "grade": "Gala", "country": "Italy", "spec": "80", "lot": "", "box_kg": 13.0},
        {"parent": "Apple", "grade": "Fuji", "country": "Italy", "spec": "110", "lot": "", "box_kg": 13.0}])
    df = pa.option_rows("Apple", parent_tab, None)
    assert pa.choices(df, "variety", origin="Italy") == ["Gala", "Fuji"]
    assert pa.choices(df, "size", origin="Italy", variety="Fuji") == ["110C"]
    assert pa.choices(df, "size", origin="NZ", variety="Gala") == ["30C", "90C", "100C"]
    assert pa.defaults(df, origin="Italy", variety="Gala", size="80C") == (13.0, 80)
    assert "Granny Smith" not in pa.choices(df, "variety", origin="NZ")


def test_entry_errors():
    ok = {"parent_sku": "Avocado", "size": "24C", "box_kg": 4, "table_no": "2", "boxes_moved": 3,
          "stock_type": "Returns"}
    assert pa.entry_errors(ok) == []
    assert pa.entry_errors({**ok, "boxes_moved": 0, "table_no": ""}) == ["Table", "Boxes"]


def test_defaults_with_missing_numbers():
    parent_tab = pd.DataFrame([{"parent": "Blueberry", "grade": "Blueberry", "country": "Peru", "spec": "18mm",
                                "lot": "", "box_kg": float("nan")}])
    df = pa.option_rows("Blueberry", parent_tab, None)
    kg, pcs = pa.defaults(df, origin="Peru", variety="Blueberry", size="18mm")
    assert (kg, pcs) == (None, None)     # nothing known for this size: left blank, no crash
    assert pa.defaults(pa.option_rows("Garlic", None, None), size="X") == (None, None)


def test_blueberry_box_only():
    assert pa.box_only("Blueberry") and pa.box_only("BB") and not pa.box_only("Apple")


def test_view_filters_and_kg():
    saved = pd.DataFrame([
        {"production_date": "2026-11-25", "city": "PTP Bangalore", "parent_sku": "Apple", "box_kg": "17.5",
         "boxes_moved": "10", "stock_type": "MT Ready Leftover"},
        {"production_date": "2026-11-24", "city": "PTP Bangalore", "parent_sku": "Avocado", "box_kg": "4",
         "boxes_moved": "50", "stock_type": "Returns"}])
    v = pa.view(saved, "2026-11-25", "PTP Bangalore")
    assert list(v["Fruit"]) == ["Apple"] and v["Kg on table"].iloc[0] == 175
    assert len(pa.view(saved)) == 2 and pa.view(None).empty


def test_new_brand_rows_only_once_per_sku():
    tab = pd.DataFrame(pa.brand_rows_from_seed())
    e = {"parent_sku": "Apple", "origin": "NZ", "variety": "Gala", "size": "30C", "brand": "Envy"}
    assert pa.new_brand_rows([e], tab, "me", "t") == []
    e2 = {**e, "size": "90C", "brand": "Jazz"}
    rows = pa.new_brand_rows([e2, e2], tab, "me", "t")
    assert len(rows) == 1 and rows[0]["Brand"] == "Jazz" and rows[0]["Size"] == "90C"


def test_newzealand_is_nz():
    parent_tab = pd.DataFrame([{"parent": "Apple", "grade": "Gala", "country": "NewZealand", "spec": "100",
                                "lot": "", "box_kg": 18.0}])
    df = pa.option_rows("Apple", parent_tab, None, pd.DataFrame(pa.brand_rows_from_seed()))
    origins = pa.choices(df, "origin")
    assert "NZ" in origins and "NewZealand" not in origins
    assert pa.choices(df, "size", origin="NZ", variety="Gala") == ["30C", "100C"]
