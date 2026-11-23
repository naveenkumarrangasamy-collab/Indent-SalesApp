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
