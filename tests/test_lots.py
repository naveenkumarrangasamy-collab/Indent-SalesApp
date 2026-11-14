import pytest

from core.lots import detect_lot


@pytest.mark.parametrize("name,lot", [
    # spec section 9
    ("1PC - Snacky Avocado Imported", "Pcs"),
    ("5 Kg Mix Tray", "Kg"),
    ("5 Kg Tray Mix", "Tray"),           # a 5 kg tray
    ("18KG Box", "Box"),
    ("17.5Kg Box - Nz Apple Royal Gala Exf135c", "Box"),
    ("9.5Kg Box - Mandarin Imp", "Box"),
    ("1Kg - Bulk Daily Apple", "Kg"),
    ("200-250gm - BH-Mini Orange (Imported)", "gms"),
    ("2 PC - BH-Royal Gala Apple - Imported", "Pcs"),
    ("1Pack - Bulk Green Kiwi", None),
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
    assert detect_lot("2kg of fruit, tray") == "Kg"


from core.lots import lot_size  # noqa: E402


@pytest.mark.parametrize("name,size", [
    ("2PC - Mini Avocado Imported", "2 Pcs"),
    ("1PC - Bloom Grapefruit (250-300 g)", "1 Pcs"),
    ("200gm - Litchi Imported (Longan)", "200 gm"),
    ("1Kg - Bulk Daily Apple", "1 Kg"),
    ("17.5Kg Box - Nz Apple Royal Gala Exf135c", "17.5 Kg Box"),
    ("18KG Box", "18 Kg Box"),
    ("200 - 250gm - BH- Premium Mini Orange", "200-250 gm"),
    ("2 PC - BH-Royal Gala Apple - Imported", "2 Pcs"),
    ("1-Pc (Std)", "1 Pcs"),
    ("1Pack - Bulk Green Kiwi", ""),
    ("Apple Royal Gala - PTP STD Lot", ""),
])
def test_lot_size(name, size):
    assert lot_size(name) == size
