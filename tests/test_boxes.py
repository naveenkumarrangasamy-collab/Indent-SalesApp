"""Box conversion of production quantities."""
import pandas as pd

from core import boxes


def test_per_lot_reads_lot_sizes():
    assert boxes.per_lot("Pcs", "2 Pcs") == ("pcs", 2)
    assert boxes.per_lot("Pack", "200 gm") == ("kg", 0.2)
    assert boxes.per_lot("Pack", "150-180 gm") == ("kg", 0.165)
    assert boxes.per_lot("Kg", "1 Kg") == ("kg", 1)
    assert boxes.per_lot("Box", "17.5 Kg Box") == ("box", 17.5)


def test_avocado_counts_default_to_4kg_and_10kg_boxes():
    # 22C: 22 pieces in a 4 kg box -> 440 pcs = 20 boxes
    assert boxes.convert("Avocado", "22C", 440, 0, 0, None, []) == ("440 pcs", "4 kg box (22 pcs)", "20")
    # 65C: 65 pieces in a 10 kg box
    units, box, n = boxes.convert("Avocado", "65C", 650, 0, 0, None, [])
    assert box == "10 kg box (65 pcs)" and n == "10"
    # two counts -> a range; the grade words after ' - ' are ignored
    units, box, n = boxes.convert("Avocado", "20C, 22C - Regular imported", 1800, 0, 0, None, [])
    assert box == "4 kg box (20–22 pcs)" and n == "81.8–90"


def test_box_kgs_from_mapping_and_tab_rules_win():
    rules = boxes.parse_rules(pd.DataFrame([
        {"Parent SKU": "Avocado", "Spec": "22C", "Box": "Tray", "Pcs per box": 24, "Kg per box": "4Kg"},
        {"Parent SKU": "Grapes", "Spec": "", "Box": "Crate", "Pcs per box": "", "Kg per box": 9},
    ]))
    assert boxes.convert("Avocado", "22C", 480, 0, 0, None, rules)[1:] == ("Tray (22 pcs)", "20")
    assert boxes.convert("Grapes", "", 0, 18, 0, None, rules) == ("18 kg", "Crate", "2")
    # Mapping Whole 'Box Kgs' for kg lots without a rule
    assert boxes.convert("Mandarin", "60, 65", 0, 20, 0, 10.0, []) == ("20 kg", "10 kg box", "2")
    # nothing known -> not mapped, no number invented
    assert boxes.convert("Blueberry", "14mm, 16mm", 100, 0, 0, None, []) == ("100 pcs", "not mapped", "")
    # lots that already are boxes
    assert boxes.convert("Mango", "", 0, 0, 3, None, [])[2] == "3"


def test_production_has_box_columns():
    from tests.test_production_calc import BASE, _lines, _masters
    from core.production_calc import production
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
                      customer_sku_name="1PC - Hass Avocado Imported", qty="440")])
    p = production(df, _masters(), box_rules=[])
    r = p.iloc[0]
    assert r["Units"] == "440 pcs" and r["Box"] == "4 kg box (20–22 pcs)" and r["Boxes"] == "20–22"
    assert "Units" not in production(df, _masters()).columns


def test_nan_box_kg_is_ignored():
    assert boxes.convert("Avocado", "22C", 440, 0, 0, float("nan"), [])[1] == "4 kg box (22 pcs)"
    assert boxes.convert("Grapes", "", 0, 20, 0, float("nan"), [])[1:] == ("not mapped", "")
