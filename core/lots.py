"""Lot auto-detection from the customer SKU name (spec section 5.4).

The first unit word found in the name wins. A unit word must stand on its
own (word boundaries), except that a digit may sit right before it, as in
"1PC", "200gm" or "2Kg".
"""
from __future__ import annotations

import re

# Longer spellings first so "gms" is not read as "gm" + "s".
_UNIT_TO_LOT = [
    (("kgs", "kg"), "Kg"),
    (("grams", "gram", "gms", "gm"), "Pack"),      # gram packs are shown as Pack
    (("packs", "pack"), "Pack"),
    (("pieces", "piece", "pcs", "pc"), "Pcs"),
    (("boxes", "box"), "Box"),
    (("trays", "tray"), "Tray"),
]

_WORD_TO_LOT = {w: lot for words, lot in _UNIT_TO_LOT for w in words}
_ALTERNATION = "|".join(sorted(_WORD_TO_LOT, key=len, reverse=True))
# Not preceded by a letter (a digit is fine), not followed by a letter or digit.
_PATTERN = re.compile(rf"(?<![A-Za-z])({_ALTERNATION})(?![A-Za-z0-9])", re.IGNORECASE)


# "17.5Kg Box", "18KG Box", "500 gm tray": the weight is the size of the
# box / tray, so the lot is Box / Tray.
_PACKED = re.compile(r"\d(?:[\d.,]*)\s*(?:kgs?|gms?|grams?)\s*[-–]?\s*(box(?:es)?|trays?)(?![A-Za-z0-9])",
                     re.IGNORECASE)


def detect_lot(sku_name: str | None) -> str | None:
    """Return 'Kg', 'Pack' (gm / pack), 'Pcs', 'Box' or 'Tray', or None if no unit word."""
    if not sku_name:
        return None
    packed = _PACKED.search(str(sku_name))
    first = _PATTERN.search(str(sku_name))
    if packed and first and packed.start() <= first.start():
        return "Box" if packed.group(1).lower().startswith("box") else "Tray"
    m = first
    if not m:
        return None
    return _WORD_TO_LOT[m.group(1).lower()]


# ---------------------------------------------------------------- lot size

_UNIT_LABEL = {"kg": "Kg", "kgs": "Kg",
               "gm": "gm", "gms": "gm", "gram": "gm", "grams": "gm",
               "pc": "Pcs", "pcs": "Pcs", "piece": "Pcs", "pieces": "Pcs",
               "box": "Box", "boxes": "Box", "tray": "Tray", "trays": "Tray",
               "pack": "Pack", "packs": "Pack"}
_NUM = r"\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?"
_SIZE = re.compile(
    rf"(?<![A-Za-z\d.])({_NUM})\s*-?\s*(kgs?|gms?|grams?|pieces?|pcs?|boxes|box|trays?|packs?)(?![A-Za-z0-9])"
    r"(?:\s*[-–]?\s*(box(?:es)?|trays?)(?![A-Za-z0-9]))?",
    re.IGNORECASE)


def lot_size(sku_name: str | None) -> str:
    """The pack size written in the SKU name, e.g.
    '2PC - Mini Avocado' -> '2 Pcs', '200gm - Litchi' -> '200 gm',
    '1Kg - Bulk Daily Apple' -> '1 Kg', '17.5Kg Box - ...' -> '17.5 Kg Box',
    '200-250gm - Mini Orange' -> '200-250 gm'. '' when no size is written."""
    if not sku_name:
        return ""
    m = _SIZE.search(str(sku_name))
    if not m:
        return ""
    num = re.sub(r"\s*-\s*", "-", m.group(1))
    unit = _UNIT_LABEL[m.group(2).lower()]
    box = m.group(3)
    return f"{num} {unit}" + (f" {_UNIT_LABEL[box.lower()]}" if box else "")


def normalize_lot(value: str | None) -> str:
    """Lot as stored -> current lot name ('gms' saved earlier -> 'Pack')."""
    from core.schema import LOTS
    v = str(value or "").strip()
    if v in LOTS:
        return v
    return detect_lot(v) or v
