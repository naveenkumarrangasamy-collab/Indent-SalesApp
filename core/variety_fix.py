"""Apple variety vs the name, across the master tabs (21 Nov).

When a SKU name says its variety (Apple Queen, Green apple, Royal Gala), the variety
column of New / All Cux City / Mapping Whole must say the same. `plan` lists the rows
that don't; `apply` writes the name's variety into them.
"""
from __future__ import annotations

from core import importer
from core.masters import name_variety
from core.schema import norm_header

TABS = (importer.PROD_BASE, importer.ALL_CUX_CITY, importer.MAPPING_WHOLE)
VARIETY_HEADS = ("variety", "applevariety", "classification")


def _s(v) -> str:
    return " ".join(str(v or "").split())


def _cols(head: list[str]) -> tuple[int, int, int] | None:
    h = [norm_header(x) for x in head]
    try:
        parent, name = h.index("parentsku"), h.index("customerskuname")
    except ValueError:
        return None
    var = next((h.index(k) for k in VARIETY_HEADS if k in h), -1)
    return (parent, name, var) if var >= 0 else None


def plan(values_by_tab: dict[str, list[list]], varieties: list[str]) -> list[dict]:
    """Apple rows whose variety column differs from (or misses) the variety in the name."""
    out = []
    for tab, values in values_by_tab.items():
        if not values:
            continue
        cols = _cols(values[0])
        if not cols:
            continue
        pc, nc, vc = cols
        for i, row in enumerate(values[1:], start=2):
            cell = lambda j: _s(row[j]) if j < len(row) else ""   # noqa: E731
            if cell(pc).casefold() != "apple":
                continue
            want = name_variety(varieties, cell(nc))
            have = cell(vc)
            if want and have.casefold() != want.casefold():
                out.append({"Tab": tab, "Row": i, "Customer SKU Name": cell(nc),
                            "Now": have or "(empty)", "Change to": want, "_col": vc})
    return out


def apply(backend, rows: list[dict]) -> int:
    for r in rows:
        backend._update_raw(r["Tab"], int(r["Row"]), {int(r["_col"]): r["Change to"]})
    return len(rows)


def read(backend) -> dict[str, list[list]]:
    have = set(backend.list_tabs())
    return {t: backend.read_values(t) or [] for t in TABS if t in have}
