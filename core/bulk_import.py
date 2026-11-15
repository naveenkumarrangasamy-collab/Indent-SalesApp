"""Owner tool: create many indents at once from an Excel sheet.

One row per item: Delivery date, City, Customer, Store, Parent SKU,
Customer SKU name (the "Item (pack size - name)" column), Qty and optionally
Price/Rate. Rows are grouped by delivery date + city + customer + store; each
group becomes one indent, saved with the same code as the Create indent page.

Items and stores that are not in the master yet can be added first: SKU names
go to 'All Cux City' (or the SKU_Map tab when the sheet has no All Cux City)
and stores to 'Customer List' (or Store_Map), written under the tab's own
headers.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

from core import importer
from core.lots import detect_lot
from core.masters import Masters, _key
from core.models import IndentHeader, IndentLine
from core.schema import SKU_MAP, STORE_MAP, norm_header

# Accepted headers (normalised: lower case, letters and digits only).
_COLS = {
    "delivery_date": ("deliverydate", "date"),
    "city": ("city",),
    "customer": ("customer", "customername", "customerlist"),
    "store": ("storedeliverypoint", "store", "storename", "deliverypoint", "storenames"),
    "parent": ("parentsku", "parent"),
    "item": ("itempacksizename", "customerskuname", "item", "skuname", "customersku"),
    "qty": ("qty", "quantity"),
    "price": ("price", "rate", "ratersperlot"),
}
_REQUIRED = ("delivery_date", "customer", "store", "item", "qty")


class ImportFileError(ValueError):
    pass


def _s(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return " ".join(str(v).split())


def _num(v) -> float | None:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        x = float(str(v).replace(",", ""))
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None


def _date(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or _s(v) == "":
        return ""
    try:
        return pd.Timestamp(v).date().isoformat()
    except (TypeError, ValueError):
        try:
            return pd.to_datetime(_s(v), dayfirst=True).date().isoformat()
        except (TypeError, ValueError):
            return ""


def _map_header(row: list) -> dict[str, int]:
    found: dict[str, int] = {}
    heads = [norm_header(h) for h in row]
    for field_name, names in _COLS.items():
        for name in names:
            if name in heads:
                found[field_name] = heads.index(name)
                break
    return found


def _rows_from_values(values: list[list], name: str) -> pd.DataFrame | None:
    for h in range(min(10, len(values))):
        cols = _map_header(values[h])
        if all(c in cols for c in _REQUIRED):
            out = []
            for i, row in enumerate(values[h + 1:], start=h + 2):
                get = lambda f: row[cols[f]] if f in cols and cols[f] < len(row) else None  # noqa: E731
                rec = {
                    "row": i, "sheet": name,
                    "delivery_date": _date(get("delivery_date")),
                    "city": _s(get("city")), "customer": _s(get("customer")),
                    "store": _s(get("store")), "parent": _s(get("parent")),
                    "item": _s(get("item")), "qty": _num(get("qty")),
                    "price": _num(get("price")),
                }
                if rec["customer"] and rec["item"] and rec["qty"] is not None:
                    out.append(rec)
            return pd.DataFrame(out, columns=["row", "sheet", "delivery_date", "city", "customer",
                                              "store", "parent", "item", "qty", "price"])
    return None


def _missing_cols() -> ImportFileError:
    need = ", ".join(n.replace("_", " ").title() for n in _REQUIRED)
    return ImportFileError(f"No sheet has the columns {need} (Item may be 'Item (pack size - name)' "
                           "or 'Customer SKU Name').")


def read_rows(data: bytes) -> pd.DataFrame:
    """Item rows from the first sheet that has the needed headers (first 10 rows
    are searched for the header row). Rows without customer, item or qty
    (totals, notes) are skipped."""
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        raise ImportFileError(f"Could not read the Excel file ({e}).") from e
    for name, raw in sheets.items():
        df = _rows_from_values(raw.values.tolist(), name)
        if df is not None:
            return df
    raise _missing_cols()


def read_pasted(text: str) -> pd.DataFrame:
    """Rows copied from Excel and pasted as text (tab, | or comma separated, header first)."""
    lines = [ln for ln in str(text or "").replace("\r\n", "\n").split("\n") if ln.strip()]
    sep = "\t" if lines and "\t" in lines[0] else ("|" if lines and "|" in lines[0] else ",")
    values = [ln.split(sep) for ln in lines]
    df = _rows_from_values(values, "pasted")
    if df is None:
        raise _missing_cols()
    return df


@dataclass
class Group:
    header: IndentHeader
    lines: list[IndentLine]
    new_skus: list[dict] = field(default_factory=list)   # rows to add to the master
    new_store: bool = False
    errors: list[str] = field(default_factory=list)
    dup: str = ""                                   # indent already placed

    @property
    def label(self) -> str:
        return f"{self.header.customer} · {self.header.store} · {self.header.delivery_date}"


def _canon(options: list[str], value: str) -> str:
    """The master's spelling of value when it is there (case/spaces ignored)."""
    for o in options:
        if _key(o) == _key(value):
            return o
    return value


def plan(rows: pd.DataFrame, m: Masters, city: str = "", price: float | None = 1.0,
         expected_time: str = "10:00") -> list[Group]:
    """Group the rows into indents. city: one city for every row ('' = the
    file's City). price: one price for every line (None = the file's price)."""
    groups: dict[tuple, Group] = {}
    for r in rows.to_dict("records"):
        c = city or r["city"]
        c = _canon(m.cities(), c)
        customer = _canon(m.customers(c), r["customer"])
        known = m.stores_for(c, customer)
        store = _canon(known, r["store"])
        if len(known) == 1 and _key(store) != _key(known[0]):
            store = known[0]          # the customer's only store in the master
        key = (r["delivery_date"], _key(c), _key(customer), _key(store))
        g = groups.get(key)
        if g is None:
            g = Group(IndentHeader(delivery_date=r["delivery_date"], city=c, customer=customer,
                                   store=store, expected_time=expected_time), [])
            g.new_store = bool(store) and _key(store) not in {_key(s) for s in m.stores_for(c, customer)}
            if not r["delivery_date"]:
                g.errors.append(f"Row {r['row']}: no delivery date.")
            if not c:
                g.errors.append(f"Row {r['row']}: no city.")
            if not store:
                g.errors.append(f"Row {r['row']}: no store.")
            groups[key] = g
        item = r["item"]
        mapped_parent = m.parent_of(c, customer, item)
        if mapped_parent:
            item = _canon(m.sku_names(c, customer, mapped_parent), item)
        parent = mapped_parent or r["parent"]
        if not parent:
            g.errors.append(f"Row {r['row']}: '{item}' has no Parent SKU.")
            continue
        lot = m.lot_for(c, customer, item) if mapped_parent else (detect_lot(item) or "")
        if not lot:
            g.errors.append(f"Row {r['row']}: no lot (Kg, Pcs, Pack, Box, Tray) in the name '{item}'.")
            continue
        qty = float(r["qty"] or 0)
        if qty <= 0:
            continue
        if not qty.is_integer():
            g.errors.append(f"Row {r['row']}: qty {qty:g} for '{item}' is not a whole number.")
            continue
        p = price if price is not None else (_num(r["price"]) or 0)
        if not p or p <= 0:
            g.errors.append(f"Row {r['row']}: no price for '{item}'.")
            continue
        variety = ""
        if m.needs_variety(parent):
            variety = m.variety_from_name(parent, item) or (m.default_variety(c, customer, item)
                                                            if mapped_parent else "")
        same = next((x for x in g.lines if _key(x.customer_sku_name) == _key(item)), None)
        if same:
            same.qty = float(same.qty) + qty
            continue
        g.lines.append(IndentLine(parent_sku=parent, customer_sku_name=item, variety=variety,
                                  lot=lot, qty=qty, price=float(p)))
        if not mapped_parent:
            g.new_skus.append({"City": c, "Customer": customer, "Parent SKU": parent,
                               "Customer SKU Name": item, "Lot": lot})
    out = list(groups.values())
    for g in out:
        if not g.lines and not g.errors:
            g.errors.append("No item with a qty above 0.")
    return out


def master_additions(groups: list[Group]) -> tuple[list[dict], list[dict]]:
    """(SKU rows, store rows) still missing from the master, without repeats."""
    skus, stores, seen_s, seen_t = [], [], set(), set()
    for g in groups:
        for r in g.new_skus:
            k = (_key(r["City"]), _key(r["Customer"]), _key(r["Customer SKU Name"]))
            if k not in seen_s:
                seen_s.add(k)
                skus.append(r)
        if g.new_store:
            h = g.header
            k = (_key(h.city), _key(h.customer), _key(h.store))
            if k not in seen_t:
                seen_t.add(k)
                stores.append({"City": h.city, "Customer": h.customer, "Store Name": h.store})
    return skus, stores


def _aligned(header: list, values: dict[str, str]) -> list:
    """A row for a tab whose header is `header`; values keyed by normalised name."""
    row = []
    for h in header:
        row.append(values.get(norm_header(h), ""))
    return row


def add_to_master(backend, skus: list[dict], stores: list[dict]) -> list[str]:
    """Append the missing SKU names and stores to the master tabs.
    Returns a short note per tab written."""
    notes = []
    tabs = set(backend.list_tabs())
    if skus:
        cux = backend.read_values(importer.ALL_CUX_CITY) if importer.ALL_CUX_CITY in tabs else []
        if cux and cux[0] and any(str(c).strip() for c in cux[0]):
            head = cux[0]
            heads = {norm_header(h) for h in head}
            lot_key = "lot" if "lot" in heads else ("uom" if "uom" in heads else "")
            rows = []
            for r in skus:
                vals = {"city": r["City"], "customer": r["Customer"], "parentsku": r["Parent SKU"],
                        "classification": r["Parent SKU"], "customerskuname": r["Customer SKU Name"]}
                if lot_key:
                    vals[lot_key] = r["Lot"]
                rows.append(_aligned(head, vals))
            backend._append_raw(importer.ALL_CUX_CITY, rows)
            notes.append(f"{len(rows)} SKU names added to '{importer.ALL_CUX_CITY}'")
        else:
            backend.append_dicts(SKU_MAP, [{"City": r["City"], "Customer": r["Customer"],
                                            "Parent SKU": r["Parent SKU"],
                                            "Customer SKU Name": r["Customer SKU Name"],
                                            "Active": "Y", "Lot": r["Lot"]} for r in skus])
            notes.append(f"{len(skus)} SKU names added to '{SKU_MAP}'")
    if stores:
        cl = backend.read_values(importer.CUSTOMER_LIST) if importer.CUSTOMER_LIST in tabs else []
        head = cl[0] if cl else []
        heads = [norm_header(h) for h in head]
        cust_h = next((h for h in importer._CUSTOMER_HEADERS if h in heads), None)
        store_h = next((h for h in importer._STORE_HEADERS if h in heads), None)
        if cust_h and store_h:
            rows = [_aligned(head, {cust_h: s["Customer"], store_h: s["Store Name"], "city": s["City"]})
                    for s in stores]
            backend._append_raw(importer.CUSTOMER_LIST, rows)
            notes.append(f"{len(rows)} stores added to '{importer.CUSTOMER_LIST}'")
        else:
            backend.append_dicts(STORE_MAP, stores)
            notes.append(f"{len(stores)} stores added to '{STORE_MAP}'")
    return notes
