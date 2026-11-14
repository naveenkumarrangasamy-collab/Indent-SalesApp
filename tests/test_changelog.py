from core.changelog import diff, has_changes, to_rows
from core.models import IndentHeader, IndentLine

H = IndentHeader("2026-11-15", "Bangalore", "Zepto", "Store A", "07:00")
HASS = IndentLine("Avocado", "1PC - Hass Avocado Imported", "", "Pcs", 30, 120)
BLUE = IndentLine("Blueberry", "1PC - Blueberry Imported", "", "Pcs", 10, 300)


def test_no_change():
    assert diff(H, [HASS], H, [IndentLine(**HASS.to_dict())]) == []
    assert not has_changes(H, [HASS], H, [HASS])


def test_qty_changed_spec_example():
    new = IndentLine(**{**HASS.to_dict(), "qty": 40})
    assert diff(H, [HASS], H, [new]) == [{
        "change_type": "line_changed", "customer_sku_name": "1PC - Hass Avocado Imported",
        "field": "qty", "old_value": "30", "new_value": "40"}]


def test_float_noise_is_not_a_change():
    new = IndentLine(**{**HASS.to_dict(), "qty": 30.0, "price": 120.0})
    assert diff(H, [HASS], H, [new]) == []


def test_added_removed_header():
    h2 = IndentHeader(**{**H.to_dict(), "store": "Store B"})
    changes = diff(H, [HASS], h2, [BLUE])
    types = [(c["change_type"], c["customer_sku_name"], c["field"]) for c in changes]
    assert ("header_changed", "", "store") in types
    assert ("line_removed", "1PC - Hass Avocado Imported", "") in types
    assert ("line_added", "1PC - Blueberry Imported", "") in types
    added = next(c for c in changes if c["change_type"] == "line_added")
    assert "qty=10" in added["new_value"] and "price=300" in added["new_value"]


def test_multiple_fields_on_one_line():
    new = IndentLine(**{**HASS.to_dict(), "lot": "Box", "price": 99.5})
    fields = {c["field"] for c in diff(H, [HASS], H, [new])}
    assert fields == {"lot", "price"}


def test_to_rows():
    rows = to_rows(diff(H, [HASS], H, []), indent_id="IND-1", from_version=1, to_version=2,
                   changed_by="a@b.com", changed_at="2026-11-14T18:20:05+05:30")
    assert rows[0]["indent_id"] == "IND-1" and rows[0]["to_version"] == 2
    assert rows[0]["change_type"] == "line_removed"
