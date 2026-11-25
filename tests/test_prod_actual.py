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
    df = pa.option_rows("Apple", parent_tab, saved)
    assert "NZ" in pa.choices(df, "origin")
    assert {"Envy", "Kiwi Crunch"} <= set(pa.brands(df, "Gala"))
    assert "90C" in pa.choices(df, "size", origin="NZ", variety="Gala")
    kg, pcs = pa.defaults(df, origin="NZ", variety="Gala", size="90C")
    assert (kg, pcs) == (18.0, 90)
    assert pa.choices(pa.option_rows("mandrin", None, None), "brand") == ["Gold Fresh"]


def test_entry_errors():
    ok = {"parent_sku": "Avocado", "size": "24C", "box_kg": 4, "table_no": "2", "boxes_moved": 3,
          "stock_type": "Returns"}
    assert pa.entry_errors(ok) == []
    assert pa.entry_errors({**ok, "boxes_moved": 0, "table_no": ""}) == ["Table", "Boxes"]
