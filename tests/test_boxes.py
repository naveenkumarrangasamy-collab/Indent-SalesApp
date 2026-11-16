"""Box conversion of production quantities."""

from core import boxes


def test_per_lot_reads_lot_sizes():
    assert boxes.per_lot("Pcs", "2 Pcs") == ("pcs", 2)
    assert boxes.per_lot("Pack", "200 gm") == ("kg", 0.2)
    assert boxes.per_lot("Pack", "150-180 gm") == ("kg", 0.165)
    assert boxes.per_lot("Kg", "1 Kg") == ("kg", 1)
    assert boxes.per_lot("Box", "17.5 Kg Box") == ("box", 17.5)


def test_production_has_no_box_columns():
    """Box conversion was removed from the production sheet (16 Nov call)."""
    from tests.test_production_calc import BASE, _lines, _masters
    from core.production_calc import production
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
                      customer_sku_name="1PC - Hass Avocado Imported", qty="440")])
    p = production(df, _masters())
    assert not {"Units", "Box", "Boxes"} & set(p.columns) and p.iloc[0]["Qty"] == 440

