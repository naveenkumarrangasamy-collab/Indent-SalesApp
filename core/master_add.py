"""New items read from an order file that are not in the master yet.

Rules (agreed 18 Nov):
- an item whose Parent SKU already exists (Apple, Avocado, Kiwi, Garlic once it is
  in the master, ...) is added automatically to All Cux City and the New tab when
  the indent is submitted; the New-tab cells still to fill (Spec-Repacking,
  Spec-Size, Spec-Origin, variety for Apple) are coloured yellow (no status text);
- an item whose parent is not in the master (e.g. Mango) is never added: it needs
  real attention, so the line stays red until it is handled by hand.
Until the specs are filled, production shows the item as "mapping not done".
"""
from __future__ import annotations

import re

from core import importer
from core.bulk_import import _aligned
from core.lots import detect_lot
from core.models import fmt_num
from core.po_reader import po_key
from core.schema import norm_header

YELLOW = (1.0, 0.92, 0.55)
NEW_TAB_COLS = ["City", "Customer", "Parent SKU", "Customer SKU Name", "variety", "Spec-Repacking",
                "Spec-Size", "Spec-Origin"]
TO_FILL = ["Spec-Repacking", "Spec-Size", "Spec-Origin"]


def guess_parent(name: str, parents: list[str]) -> str:
    """The existing Parent SKU whose name is a word of the item ('Apple Fuji
    Imported' -> 'Apple'); '' when none (a new parent: not added)."""
    words = set(re.findall(r"[a-z]+", name.casefold()))
    words |= {w[:-3] + "y" for w in words if w.endswith("ies")} | {w[:-1] for w in words if w.endswith("s")}
    hits = [p for p in parents if p and set(re.findall(r"[a-z]+", p.casefold())) <= words]
    return max(hits, key=len) if hits else ""


def new_sku_name(read_name: str) -> str:
    """Our style for a new SKU name: 'Pear Packham Imported - 2 PIECE' ->
    '2PC - Pear Packham Imported', '... - 250 GRAM' -> '250gm - ...'."""
    z = re.fullmatch(r"(.+?),\s*\(?([\d.]+)\)?\s*(g|gm|gram|grams|kg|kgs|piece|pieces|pc|pcs|pack|packs)\.?\s*(\(.*\))?",
                     read_name.strip(), flags=re.I)
    if z:                                      # Zomato style: 'BH - Green Kiwi, 3 pieces' -> '3PC - BH - Green Kiwi'
        n, u = fmt_num(float(z.group(2))), z.group(3).casefold()
        unit = ("gm" if u.startswith("g") else "Kg" if u.startswith("k")
                else "Pack" if u.startswith("pack") else "PC")
        extra = f" {z.group(4)}" if z.group(4) else ""
        return f"{n}{unit} - {' '.join(z.group(1).split())}{extra}"
    parts = re.split(r"\s+-\s+(?=\d)", read_name.strip(), maxsplit=1)
    core = " ".join(parts[0].split())
    tail = re.fullmatch(r"(.+?)\s+([\d.]+)\s*(g|gm|gram|grams|kg|kgs|piece|pieces|pc|pcs|pack|packs)\.?",
                        core, flags=re.I)
    if len(parts) == 1 and tail:               # Swiggy style: 'Longan 100.0 g' -> '100gm - Longan'
        n = fmt_num(float(tail.group(2)))
        u = tail.group(3).casefold()
        unit = ("gm" if u.startswith("g") else "Kg" if u.startswith("k")
                else "Pack" if u.startswith("pack") else "PC")
        return f"{n}{unit} - {' '.join(tail.group(1).split())}"
    _, pack = po_key(read_name)
    m = re.fullmatch(r"([\d.]+)(pc|g|kg)", pack or "")
    if not m:
        return core
    n, unit = fmt_num(float(m.group(1))), m.group(2)
    prefix = {"pc": f"{n}PC", "g": f"{n}gm", "kg": f"{n}Kg"}[unit]
    return f"{prefix} - {core}"


def lot_of(sku_name: str) -> str:
    return detect_lot(sku_name) or "Pcs"


COUNTRIES = ["New Zealand", "South Africa", "Tanzania", "Kenya", "Peru", "Chile", "USA", "Egypt", "Spain",
             "Australia", "Iran", "Italy", "Turkey", "China", "Morocco", "Colombia", "Mexico", "India", "RSA",
             "Washington", "Zimbabwe", "Brazil", "Poland", "Serbia", "Greece", "Thailand", "Vietnam"]


def origin_in(name: str, known: list[str] = ()) -> str:
    """A country written in the name ('BH-Avocado Hass - Tanzania' -> 'Tanzania'), else ''."""
    low = name.casefold()
    for c in list(known) + COUNTRIES:
        if c and re.search(r"\b" + re.escape(c.casefold()) + r"\b", low):
            return c
    return ""


def add_items(backend, city: str, customer: str, items: list[dict], user: str) -> list[str]:
    """items: [{'Parent SKU', 'Customer SKU Name', 'Variety', 'Lot'}]. Appends them
    to All Cux City and the New tab (cells to fill in yellow). Returns notes."""
    if not items:
        return []
    notes = []
    tabs = set(backend.list_tabs())
    if importer.ALL_CUX_CITY in tabs:
        head = (backend.read_values(importer.ALL_CUX_CITY) or [[]])[0]
        heads = {norm_header(h) for h in head}
        lot_key = "lot" if "lot" in heads else ("uom" if "uom" in heads else "")
        rows = []
        for r in items:
            vals = {"city": city, "customer": customer, "parentsku": r["Parent SKU"],
                    "classification": r.get("Variety") or r["Parent SKU"],
                    "customerskuname": r["Customer SKU Name"]}
            if lot_key:
                vals[lot_key] = r.get("Lot", "")
            rows.append(_aligned(head, vals))
        backend._append_raw(importer.ALL_CUX_CITY, rows)
        notes.append(f"{len(rows)} added to {importer.ALL_CUX_CITY}")
    tab = importer.PROD_BASE
    if tab in tabs:
        values = backend.read_values(tab) or []
        head = list(values[0]) if values else []
        if not head:
            head = list(NEW_TAB_COLS)
            backend._append_raw(tab, [head])
        rows = []
        for r in items:
            origins = [o.strip() for o in str(r.get("Origin") or "").split(",") if o.strip()] or [""]
            for o in origins:                  # one row per origin; the first one is the one in use
                vals = {"city": city, "customer": customer, "parentsku": r["Parent SKU"],
                        "customerskuname": r["Customer SKU Name"], "variety": r.get("Variety", ""),
                        "specorigin": o}
                rows.append(_aligned(head, vals))
        first, last = backend._append_raw(tab, rows)
        normed = [norm_header(h) for h in head]
        cols = [normed.index(norm_header(c)) for c in TO_FILL if norm_header(c) in normed]
        if any(not r.get("Variety") and r.get("needs_variety") for r in items) and "variety" in normed:
            cols.append(normed.index("variety"))
        try:
            backend.highlight(tab, first, last, cols, YELLOW)
        except Exception:  # noqa: BLE001 - colour is a help, never block the indent
            pass
        notes.append(f"{len(rows)} added to the {tab} tab (spec to fill, in yellow)")
    return notes
