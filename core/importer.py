"""One-time import of SKU_Map and Varieties from the team's existing tabs.

Sources in the current Google Sheet:
- "Mapping Whole": City, Customer, Parent SKU, Customer SKU Name,
  Spec-Origin, Spec-Size (one row per origin).
- "All Cux City": City, Customer, Parent SKU, Classification,
  Customer SKU Name. For Apple, Classification is the variety
  (Gala, Granny Smith, ...).

Nothing in the source tabs is changed. The owner runs this from the Access
page when SKU_Map / Varieties are still empty, then maintains SKU_Map.
"""
from __future__ import annotations

from core.schema import norm_header

MAPPING_WHOLE = "Mapping Whole"
ALL_CUX_CITY = "All Cux City"

# Origin currently being sourced, per parent (the yellow rows in the spec).
DEFAULT_ACTIVE_ORIGINS = {"avocado": "tanzania", "blueberry": "peru", "mandarin": "rsa"}


def _records(values: list[list]) -> list[dict]:
    """Rows as dicts keyed by normalised header; blank header cells skipped."""
    if not values:
        return []
    header = [norm_header(h) for h in values[0]]
    out = []
    for row in values[1:]:
        rec = {}
        for i, h in enumerate(header):
            if h and h not in rec:
                rec[h] = str(row[i]).strip() if i < len(row) and row[i] is not None else ""
        out.append(rec)
    return out


def _k(*parts: str) -> tuple:
    return tuple(" ".join(str(p).split()).casefold() for p in parts)


def build_sku_map(mapping_whole: list[list], all_cux_city: list[list],
                  active_origins: dict[str, str] | None = None) -> list[dict]:
    active_origins = DEFAULT_ACTIVE_ORIGINS if active_origins is None else active_origins
    rows: list[dict] = []
    seen: set[tuple] = set()

    # Default variety per (city, customer, name) from All Cux City.
    variety_by_name: dict[tuple, str] = {}
    for r in _records(all_cux_city):
        parent, cls, name = r.get("parentsku", ""), r.get("classification", ""), r.get("customerskuname", "")
        if parent and cls and name and cls.casefold() != parent.casefold():
            variety_by_name[_k(r.get("city", ""), r.get("customer", ""), name)] = cls

    def add(city, customer, parent, name, origin, size):
        name = " ".join(name.split())
        if not (city and customer and parent and name):
            return
        key = _k(city, customer, name, origin)
        if key in seen:
            return
        seen.add(key)
        rows.append({"City": city, "Customer": customer, "Parent SKU": parent,
                     "Customer SKU Name": name, "Spec-Origin": origin, "Spec-Size": size,
                     "Active": "", "Variety": variety_by_name.get(_k(city, customer, name), "")})

    for r in _records(mapping_whole):
        add(r.get("city", ""), r.get("customer", ""), r.get("parentsku", ""),
            r.get("customerskuname", ""), r.get("specorigin", ""), r.get("specsize", ""))

    named = {_k(x["City"], x["Customer"], x["Customer SKU Name"]) for x in rows}
    for r in _records(all_cux_city):
        key = _k(r.get("city", ""), r.get("customer", ""), " ".join(r.get("customerskuname", "").split()))
        if key in named:
            continue
        add(r.get("city", ""), r.get("customer", ""), r.get("parentsku", ""),
            r.get("customerskuname", ""), "", "")
        named.add(key)

    # Active flag: a single row is active; with several origins, the
    # configured origin for that parent is active and the rest are N.
    groups: dict[tuple, list[dict]] = {}
    for x in rows:
        groups.setdefault(_k(x["City"], x["Customer"], x["Customer SKU Name"]), []).append(x)
    for grp in groups.values():
        if len(grp) == 1:
            grp[0]["Active"] = "Y"
            continue
        want = active_origins.get(grp[0]["Parent SKU"].casefold())
        if want and any(x["Spec-Origin"].casefold() == want for x in grp):
            for x in grp:
                x["Active"] = "Y" if x["Spec-Origin"].casefold() == want else "N"
    return rows


def build_varieties(all_cux_city: list[list]) -> list[dict]:
    """(Parent SKU, Variety) pairs where Classification differs from the
    parent. Rows that only carry a Classification (a list of varieties under
    an Apple block) inherit the parent from the row above."""
    out: list[dict] = []
    seen: set[tuple] = set()
    last_parent = ""
    for r in _records(all_cux_city):
        if not any(r.values()):
            last_parent = ""
            continue
        parent = r.get("parentsku", "") or last_parent
        last_parent = parent
        cls = r.get("classification", "")
        if parent and cls and cls.casefold() != parent.casefold():
            key = _k(parent, cls)
            if key not in seen:
                seen.add(key)
                out.append({"Parent SKU": parent, "Variety": cls})
    return out
