"""24 Nov: variety from the New Mapping Combination tab, and the new name aliases."""
import pandas as pd

from core import config
from core.masters import combo_varieties, name_variety
from core.mapping_sheet import _k

APPLE = config.DEFAULT_APPLE_VARIETIES


def _vf(parent):
    return APPLE if parent == "Apple" else []


def test_one_variety_is_fixed_many_are_not():
    combos = pd.DataFrame([
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "2PC - Apple Queen", "parent": "Apple", "cust_variety": "Queen"},
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "2PC - Snacky Apple", "parent": "Apple",
         "cust_variety": "Gala, RD, Queen, Fuji, Jazz, Pink Lady"},
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "1Kg - Daily Apple", "parent": "Apple", "cust_variety": ""},
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "1PC - Hass Avocado", "parent": "Avocado", "cust_variety": "Hass"},
    ])
    got = combo_varieties(combos, _vf)
    assert got == {(_k("PTP Bangalore"), _k("Zepto"), _k("2PC - Apple Queen")): "Queen"}


def test_new_aliases():
    assert name_variety(APPLE, "18Kg Box - Apple Red Del Exf Box L") == "RD"
    assert name_variety(APPLE, "2PC - Red Delicious Apple") == "RD"
    assert name_variety(APPLE, "1PC - Honeycrisp Apple") == "Honey Crisp"
    assert name_variety(APPLE, "2PC - Snacky Apple") == ""


def test_parent_tab_varieties_for_mandarin_orange():
    from core.masters import parent_varieties
    par = pd.DataFrame({"parent": ["Mandarin", "Mandarin", "Orange", "Orange", "Avocado", "Apple"],
                        "grade": ["Xinyu", "Nova", "Valencia", "Navel", "Hass", "(no variety)"]})
    got = parent_varieties(par)
    assert got["mandarin"] == ["Xinyu", "Nova"]
    assert got["orange"] == ["Valencia", "Navel"]
    assert "apple" not in got


def test_estimate_uses_the_indent_variety():
    from core import mapping_sheet
    combos = pd.DataFrame([
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "2PC - Snacky Apple", "parent": "Apple",
         "cust_variety": "", "cust_spec": "", "country": "Brazil", "grade": "Gala", "spec": "90c, 100c",
         "box_kg": 18.0, "lot": "18 kg"},
        {"city": "PTP Bangalore", "customer": "Zepto", "our": "2PC - Snacky Apple", "parent": "Apple",
         "cust_variety": "", "cust_spec": "", "country": "Chile", "grade": "Queen HG", "spec": "150c",
         "box_kg": 18.0, "lot": "18 kg"},
    ])
    all_o = mapping_sheet.options(combos, None, "PTP Bangalore", "Zepto", "2PC - Snacky Apple", "Apple", "")
    gala = mapping_sheet.options(combos, None, "PTP Bangalore", "Zepto", "2PC - Snacky Apple", "Apple", "Gala")
    assert len(all_o) == 2 and list(gala) == ["Brazil · Gala"]
