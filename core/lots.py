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
    (("grams", "gram", "gms", "gm"), "gms"),
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
    """Return 'Kg', 'gms', 'Pcs', 'Box' or 'Tray', or None if no unit word."""
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
