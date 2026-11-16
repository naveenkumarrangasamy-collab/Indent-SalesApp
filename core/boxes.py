"""Pack sizes: what one lot of a SKU is, in pieces or kilos.

per_lot("Pcs", "2 Pcs") -> ("pcs", 2); per_lot("Kg", "1 Kg") -> ("kg", 1);
per_lot("Pack", "200 gm") -> ("kg", 0.2); per_lot("Box", "1 Box") -> ("box", 0).
Used by the production sheet and the make-ready list.
"""
from __future__ import annotations

import re


def per_lot(lot: str, size: str) -> tuple[str, float]:
    """What one lot is: ('pcs', n), ('kg', x), ('box', kg-or-0)."""
    s = str(size or "").strip().casefold()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    n = sum(nums) / len(nums) if nums else 1.0          # '150-180 gm' -> 165
    if "box" in s or str(lot).casefold() == "box":
        return "box", (n if "kg" in s else 0.0)
    if "kg" in s:
        return "kg", n
    if re.search(r"\bg(m|ms|rams?)?\b", s):
        return "kg", n / 1000
    return "pcs", n
