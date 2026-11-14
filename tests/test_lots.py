import pytest

from core.lots import detect_lot


@pytest.mark.parametrize("name,lot", [
    # spec section 9
    ("1PC - Snacky Avocado Imported", "Pcs"),
    ("5 Kg Tray Mix", "Kg"),
    ("Mixed Box 2Kg", "Box"),
    ("Avocado Imported", None),
    # names from the team's sheet
    ("2PC - Mini Avocado Imported", "Pcs"),
    ("3PC - Baby Orange Imported", "Pcs"),
    ("200gm - Snacky Apple", "gms"),
    ("250gm - Bloom Grapes Red globe", "gms"),
    ("1PC - Bloom Grapefruit (250-300 g)", "Pcs"),
    ("Blueberry Imported - 125gm", "gms"),
    ("Bulk Nectr Royal Gala 1Kg", "Kg"),
    ("Daily Apple 6Pcs", "Pcs"),
    ("1-Pc (Std)", "Pcs"),
    ("Apple Royal Gala - PTP STD Lot", None),
    ("kiwi sungold 1pack", None),
    # spellings and boundaries
    ("Grapes 500 grams", "gms"),
    ("Grapes 1 gram", "gms"),
    ("Onion 2 KGS", "Kg"),
    ("Eggs 6 pieces", "Pcs"),
    ("Strawberry 2 trays", "Tray"),
    ("Mango boxes", "Box"),
    ("Boxer Shorts", None),
    ("Spcs fruit", None),
    ("", None),
    (None, None),
])
def test_detect_lot(name, lot):
    assert detect_lot(name) == lot


def test_first_unit_wins():
    assert detect_lot("Tray of 2 kg") == "Tray"
    assert detect_lot("2kg tray") == "Kg"
