"""Builds the SKU mapping live from the team's existing tabs.

Sources in the Google Sheet (read on every master-data refresh, never changed):

- "All Cux City" is the master list of customer SKU names:
  City, Customer, Parent SKU, Classification, Customer SKU Name.
  For Apple, Classification is the variety (Gala, Granny Smith, ...).
- "Mapping Whole" gives the spec per origin:
  City, Customer, Parent SKU, Customer SKU Name, Spec-Origin, Spec-Size.
  Its rows are matched to All Cux City by City + Customer + SKU name.

Optional columns the team can add (matched by header name, any position):
- "Lot" or "UOM" in either tab: fixes the lot for that SKU name
  (Kg, Pcs, Tray, Box, gms). Without it the lot comes from the SKU name.
- "Active" in Mapping Whole: Y for the origin being sourced. Without it,
  Tanzania (Avocado), Peru (Blueberry) and RSA (Mandarin) are active, and a
  SKU with a single origin row is active.

If "All Cux City" has no usable rows, the names from "Mapping Whole" are used.

- A column headed "Apple Variety" (or "<Parent> Variety") in All Cux City
  lists the varieties the user chooses from for that parent.

- "Customer List" gives the stores per customer: Customer List (the
  customer), Store names, and optionally City. A store with no City is
  offered for that customer in every city.
"""
from __future__ import annotations

from core.lots import detect_lot
from core.schema import norm_header

MAPPING_WHOLE = "Mapping Whole"
ALL_CUX_CITY = "All Cux City"
CUSTOMER_LIST = "Customer List"
LEGACY_TABS = [ALL_CUX_CITY, MAPPING_WHOLE, CUSTOMER_LIST]

# Origin currently being sourced, per parent (the yellow rows in the spec).
DEFAULT_ACTIVE_ORIGINS = {"avocado": "tanzania", "blueberry": "peru", "mandarin": "rsa"}

_LOT_HEADERS = ("lot", "uom", "lotuom", "unit")


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _records(values: list[list]) -> tuple[list[dict], set[str]]:
    """Rows as dicts keyed by normalised header (blank headers skipped),
    plus the set of headers present."""
    if not values:
        return [], set()
    header = [norm_header(h) for h in values[0]]
    out = []
    for row in values[1:]:
        rec = {}
        for i, h in enumerate(header):
            if h and h not in rec:
                rec[h] = _s(row[i]) if i < len(row) else ""
        out.append(rec)
    return out, {h for h in header if h}


def _k(*parts: str) -> tuple:
    return tuple(_s(p).casefold() for p in parts)


def _lot_of(rec: dict) -> str:
    for h in _LOT_HEADERS:
        if rec.get(h):
            return detect_lot(rec[h]) or ""
    return ""


def _valid(rec: dict) -> bool:
    return all(rec.get(f) for f in ("city", "customer", "parentsku", "customerskuname"))


def build_sku_map(mapping_whole: list[list], all_cux_city: list[list],
                  active_origins: dict[str, str] | None = None) -> list[dict]:
    active_origins = DEFAULT_ACTIVE_ORIGINS if active_origins is None else active_origins
    mw, mw_headers = _records(mapping_whole)
    ac, _ = _records(all_cux_city)
    has_active_col = "active" in mw_headers

    # Spec rows from Mapping Whole, by (city, customer, name).
    specs: dict[tuple, list[dict]] = {}
    for r in mw:
        if r.get("city") and r.get("customer") and r.get("customerskuname"):
            specs.setdefault(_k(r["city"], r["customer"], r["customerskuname"]), []).append(r)

    names = [r for r in ac if _valid(r)] or [r for r in mw if _valid(r)]

    rows: list[dict] = []
    seen: set[tuple] = set()
    for r in names:
        key = _k(r["city"], r["customer"], r["customerskuname"])
        if key in seen:
            continue
        seen.add(key)
        parent = r["parentsku"]
        cls = r.get("classification", "")
        variety = cls if cls and cls.casefold() != parent.casefold() else ""
        spec_rows = specs.get(key, [])
        lot = _lot_of(r) or next((_lot_of(x) for x in spec_rows if _lot_of(x)), "")
        origins_seen: set[str] = set()
        group: list[dict] = []
        for sr in spec_rows or [{}]:
            origin = sr.get("specorigin", "")
            if origin.casefold() in origins_seen:
                continue
            origins_seen.add(origin.casefold())
            active = ""
            if has_active_col and sr:
                active = "Y" if sr.get("active", "").strip().lower() in {"y", "yes", "true", "1"} else "N"
            group.append({"City": r["city"], "Customer": r["customer"], "Parent SKU": parent,
                          "Customer SKU Name": r["customerskuname"], "Spec-Origin": origin,
                          "Spec-Size": sr.get("specsize", ""), "Active": active,
                          "Variety": variety, "Lot": lot})
        _default_active(group, active_origins)
        rows.extend(group)
    return rows


def _default_active(group: list[dict], active_origins: dict[str, str]) -> None:
    """Fill Active only when the sheet does not say which origin is active."""
    if any(x["Active"] == "Y" for x in group):
        return
    if len(group) == 1:
        group[0]["Active"] = "Y"
        return
    want = active_origins.get(group[0]["Parent SKU"].casefold())
    if want and any(x["Spec-Origin"].casefold() == want for x in group):
        for x in group:
            x["Active"] = "Y" if x["Spec-Origin"].casefold() == want else "N"


def _variety_columns(values: list[list]) -> list[tuple[int, str]]:
    """Columns headed '<Parent> Variety' (e.g. 'Apple Variety'): (index, parent)."""
    if not values:
        return []
    out = []
    for i, h in enumerate(values[0]):
        text = _s(h)
        low = text.casefold()
        for suffix in (" varieties", " variety"):
            if low.endswith(suffix) and len(text) > len(suffix):
                out.append((i, text[: -len(suffix)].strip()))
                break
    return out


def build_varieties(all_cux_city: list[list]) -> list[dict]:
    """(Parent SKU, Variety) pairs.

    - A column headed '<Parent> Variety' (e.g. 'Apple Variety') lists the
      varieties of that parent, one per cell, anywhere down the column.
    - Also: Classification values that differ from the parent (rows that
      only carry a Classification inherit the parent from the row above).
    """
    out: list[dict] = []
    seen: set[tuple] = set()
    for idx, parent in _variety_columns(all_cux_city):
        for row in all_cux_city[1:]:
            v = _s(row[idx]) if idx < len(row) else ""
            if v and _k(parent, v) not in seen:
                seen.add(_k(parent, v))
                out.append({"Parent SKU": parent, "Variety": v})
    last_parent = ""
    recs, _ = _records(all_cux_city)
    for r in recs:
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


_CUSTOMER_HEADERS = ("customerlist", "customer", "customername")
_STORE_HEADERS = ("storenames", "storename", "store", "stores")


def build_store_map(customer_list: list[list]) -> list[dict]:
    """Store_Map rows from the 'Customer List' tab."""
    recs, headers = _records(customer_list)
    cust_h = next((h for h in _CUSTOMER_HEADERS if h in headers), None)
    store_h = next((h for h in _STORE_HEADERS if h in headers), None)
    if not cust_h or not store_h:
        return []
    out, seen = [], set()
    for r in recs:
        customer, store, city = r.get(cust_h, ""), r.get(store_h, ""), r.get("city", "")
        if not (customer and store):
            continue
        key = _k(city, customer, store)
        if key in seen:
            continue
        seen.add(key)
        out.append({"City": city, "Customer": customer, "Store Name": store})
    return out
