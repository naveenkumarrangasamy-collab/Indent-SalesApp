"""Master data: SKU map, store map, varieties (and the Access tab).

`load_masters()` reads all four master tabs in one Sheets call and caches the
result for `master_refresh_minutes` (default 5 min). The query helpers below are
pure functions over the DataFrames so they are easy to test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from core import config, importer
from core.lots import detect_lot
from core.schema import (ACCESS, DEFAULT_CUSTOMERS, MASTER_TABS, SKU_MAP,
                         STORE_MAP, TABS, VARIETIES)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c != "_row":
            df[c] = df[c].astype(str).str.strip()
    return df


def _key(s: str) -> str:
    """Matching key: case-insensitive, extra spaces ignored."""
    return " ".join(str(s or "").split()).casefold()


@dataclass
class Masters:
    sku: pd.DataFrame
    stores: pd.DataFrame
    varieties: pd.DataFrame
    access: pd.DataFrame
    sku_source: str = "SKU_Map tab"
    prod_base: pd.DataFrame | None = None   # the 'New' tab (production base)
    combo_variety: dict | None = None       # 24 Nov: New Mapping Combination customer variety, one per SKU
    parent_varieties: dict | None = None    # 24 Nov: {parent key: [varieties]} from the New Mapping Parent tab

    def prod_info(self, city: str, customer: str, sku_name: str) -> dict | None:
        """The 'New' tab row for this SKU name (city + customer + name), else None.
        A row with no City matches every city."""
        df = self.prod_base
        if df is None or df.empty:
            return None
        hit = df[(df["Customer"].map(_key) == _key(customer))
                 & (df["Customer SKU Name"].map(_key) == _key(sku_name))]
        if hit.empty:
            return None
        exact = hit[hit["City"].map(_key) == _key(city)]
        hit = exact if not exact.empty else hit[hit["City"].map(_key) == ""]
        return None if hit.empty else hit.iloc[0].to_dict()

    @property
    def has_prod_base(self) -> bool:
        return self.prod_base is not None and not self.prod_base.empty

    # ---------------- lookups used by the screens ----------------
    def _sku_for(self, city: str, customer: str) -> pd.DataFrame:
        df = self.sku
        return df[(df["City"].map(_key) == _key(city)) & (df["Customer"].map(_key) == _key(customer))
                  & (df["Customer SKU Name"] != "")]

    def cities(self) -> list[str]:
        """Cities in the order they appear in the sheet (stores first)."""
        return _unique_in_order(list(self.stores["City"]) + list(self.sku["City"]))

    def customers(self, city: str) -> list[str]:
        """Customers mapped for the city in the sheet (Customer List first,
        then All Cux City), in sheet order. Only if the sheet has none for the
        city are the five MT customers offered."""
        found = (list(self.stores.loc[self._city_match(self.stores, city), "Customer"])
                 + list(self.sku.loc[self.sku["City"].map(_key) == _key(city), "Customer"]))
        return _unique_in_order(found) or list(DEFAULT_CUSTOMERS)


    def has_sku_mapping(self, city: str, customer: str) -> bool:
        return not self._sku_for(city, customer).empty

    def _city_match(self, df: pd.DataFrame, city: str) -> pd.Series:
        """Store rows for this city; a store with no city applies to every city."""
        c = df["City"].map(_key)
        return (c == _key(city)) | (c == "")

    def stores_for(self, city: str, customer: str) -> list[str]:
        df = self.stores
        df = df[self._city_match(df, city) & (df["Customer"].map(_key) == _key(customer))]
        return _unique_in_order(df["Store Name"])

    def parents(self, city: str, customer: str) -> list[str]:
        return _unique_sorted(self._sku_for(city, customer)["Parent SKU"])

    def sku_names(self, city: str, customer: str, parent: str) -> list[str]:
        df = self._sku_for(city, customer)
        df = df[df["Parent SKU"].map(_key) == _key(parent)]
        return _unique_in_order(df["Customer SKU Name"])

    def parent_of(self, city: str, customer: str, sku_name: str) -> str:
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        return df["Parent SKU"].iloc[0] if not df.empty else ""

    def active_rows(self, city: str, customer: str, sku_name: str) -> pd.DataFrame:
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        return df[df["Active"].map(_is_yes)]

    def spec(self, city: str, customer: str, sku_name: str) -> tuple[str, str]:
        """(origin, size) from the Active row. Falls back to the only row if
        the SKU has a single row and nothing is marked Active."""
        rows = self.active_rows(city, customer, sku_name)
        if rows.empty:
            df = self._sku_for(city, customer)
            df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
            if len(df) == 1:
                rows = df
        if rows.empty:
            return "", ""
        r = rows.iloc[0]
        return r.get("Spec-Origin", ""), r.get("Spec-Size", "")

    def spec_size(self, city: str, customer: str, sku_name: str) -> str:
        """Spec-Size from Mapping Whole: the Active origin's size; when no row
        is Active but every origin has the same size, that size."""
        size = self.spec(city, customer, sku_name)[1]
        if size:
            return size
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        sizes = {str(v).strip() for v in df["Spec-Size"] if str(v).strip()}
        return sizes.pop() if len(sizes) == 1 else ""

    def spec_grade(self, city: str, customer: str, sku_name: str) -> str:
        rows = self.active_rows(city, customer, sku_name)
        if rows.empty:
            df = self._sku_for(city, customer)
            rows = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        vals = {str(v).strip() for v in rows.get("Spec-Grade", pd.Series(dtype=str)) if str(v).strip()}
        return sorted(vals)[0] if vals else ""


    def spec_label(self, city: str, customer: str, sku_name: str) -> str:
        """The agreed spec used to club production: size + grade,
        e.g. '20C, 22C - Regular imported'. '' when not mapped."""
        size, grade = self.spec_size(city, customer, sku_name), self.spec_grade(city, customer, sku_name)
        return " - ".join(x for x in (size, grade) if x)

    def mapped_variety(self, city: str, customer: str, sku_name: str) -> str:
        """Variety written in the mapping (Classification different from the
        parent, e.g. Hass for Avocado), or taken from the name for apples."""
        parent = self.parent_of(city, customer, sku_name)
        fixed = (self.variety_from_name(parent, sku_name) or self.combo_variety_for(city, customer, sku_name)) \
            if parent else ""
        if fixed:
            return fixed
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        vals = [v for v in df.get("Variety", pd.Series(dtype=str)) if v]
        if vals:
            return vals[0]
        info = self.prod_info(city, customer, sku_name)            # the New tab's variety column
        v = str((info or {}).get("Variety", "") or "").strip()
        return v if v in self.varieties_for(parent) else ""

    def combo_variety_for(self, city: str, customer: str, sku_name: str) -> str:
        """24 Nov: the one variety the New Mapping Combination tab gives this SKU ('' when it lists
        none or several, e.g. Snacky / Daily Apple = all varieties -> the user picks)."""
        if not self.combo_variety:
            return ""
        from core.mapping_sheet import _k as mk
        parent = self.parent_of(city, customer, sku_name)
        v = self.combo_variety.get((mk(city), mk(customer), mk(sku_name)), "")
        return next((x for x in self.varieties_for(parent) if _key(x) == _key(v)), "") if v else ""

    def new_tab_variety(self, city: str, customer: str, sku_name: str) -> str:
        """The variety written in the New tab for this SKU (when it is a known variety)."""
        parent = self.parent_of(city, customer, sku_name)
        info = self.prod_info(city, customer, sku_name)
        v = str((info or {}).get("Variety", "") or "").strip()
        return next((x for x in self.varieties_for(parent) if _key(x) == _key(v)), "") if v else ""

    def default_variety(self, city: str, customer: str, sku_name: str) -> str:
        """21 Nov: the name wins when it names a variety (Apple Queen -> Queen, Apple Green ->
        Granny Smith); else the New tab; else All Cux City. '' = the user picks."""
        parent = self.parent_of(city, customer, sku_name)
        if not self.varieties_for(parent):
            return ""
        fixed = self.variety_from_name(parent, sku_name) or self.combo_variety_for(city, customer, sku_name)
        if fixed:
            return fixed
        nt = self.new_tab_variety(city, customer, sku_name)
        if nt:
            return nt
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        vals = [v for v in df.get("Variety", pd.Series(dtype=str)) if v]
        known = {_key(x): x for x in self.varieties_for(parent)}
        return next((known[_key(v)] for v in vals if _key(v) in known), "")

    def lot_for(self, city: str, customer: str, sku_name: str) -> str:
        """The fixed lot for a SKU name: the Lot/UOM column of the mapping if
        filled, otherwise the unit word in the name. '' if neither."""
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        for v in df.get("Lot", pd.Series(dtype=str)):
            lot = detect_lot(v) if v else None
            if lot:
                return lot
        return detect_lot(sku_name) or ""

    def varieties_for(self, parent: str) -> list[str]:
        """Varieties only for the variety parents (Apple); none for anything else.
        Apple uses the sheet's list ('Apple Varity' tab etc.), or the default list
        when the sheet has none."""
        if _key(parent) not in {_key(p) for p in config.variety_parents()}:
            if _key(parent) in {_key(p) for p in config.ask_variety_parents()}:
                return list((self.parent_varieties or {}).get(_key(parent), []))   # Mandarin, Orange
            return []
        df = self.varieties
        df = df[df["Parent SKU"].map(_key) == _key(parent)]
        found = _unique_in_order(df["Variety"])
        if _key(parent) == "apple":       # 21 Nov: the sheet's list plus the full built-in list
            have = {_key(v) for v in found}
            found = found + [v for v in config.DEFAULT_APPLE_VARIETIES if _key(v) not in have]
        return found

    def variety_from_name(self, parent: str, sku_name: str) -> str:
        """The variety written in an Apple SKU name ('Royal Gala' -> Gala, 'Red Delicious' -> RD,
        'Apple Green Imported (Granny Smith)' / 'Green apple' -> Granny Smith, 'Apple Queen' -> Queen).
        '' when the name does not say (Apple Snacky, Daily Apple) -> New tab / user picks."""
        return name_variety(self.varieties_for(parent), sku_name)

    def needs_variety(self, parent: str) -> bool:
        return bool(self.varieties_for(parent))

    def active_warnings(self) -> pd.DataFrame:
        """SKU names with zero or more than one Active row (for the owner)."""
        df = self.sku[self.sku["Customer SKU Name"] != ""].copy()
        if df.empty:
            return pd.DataFrame(columns=["City", "Customer", "Customer SKU Name", "Rows", "Active rows"])
        df["_active"] = df["Active"].map(_is_yes)
        g = (df.groupby(["City", "Customer", "Customer SKU Name"], dropna=False)
               .agg(Rows=("_active", "size"), **{"Active rows": ("_active", "sum")})
               .reset_index())
        # A single row with nothing marked Active is fine (nothing to choose).
        bad = g[(g["Active rows"] > 1) | ((g["Active rows"] == 0) & (g["Rows"] > 1))]
        return bad.sort_values(["City", "Customer", "Customer SKU Name"]).reset_index(drop=True)


VARIETY_ALIASES = {"royal gala": "Gala", "red delicious": "RD", "red del": "RD", "granny": "Granny Smith",
                   "green": "Granny Smith", "honeycrisp": "Honey Crisp", "cripps pink": "Pink Lady"}


def name_variety(varieties: list[str], sku_name: str) -> str:
    """The first variety (or alias) written in the name; a longer phrase wins at the same place."""
    import re as _re
    if not varieties or not sku_name:
        return ""
    text = " ".join(str(sku_name).split()).casefold()
    by_key = {v.casefold(): v for v in varieties}
    candidates = [(v.casefold(), v) for v in varieties]
    candidates += [(a, by_key[v.casefold()]) for a, v in VARIETY_ALIASES.items()
                   if v.casefold() in by_key and a not in by_key]
    best = None
    for phrase, variety in candidates:
        m = _re.search(r"(?<![a-z0-9])" + _re.escape(phrase) + r"(?![a-z0-9])", text)
        if m and (best is None or (m.start(), -len(phrase)) < (best[0], -best[1])):
            best = (m.start(), len(phrase), variety)
    return best[2] if best else ""


def _is_yes(v) -> bool:
    return str(v or "").strip().lower() in {"y", "yes", "true", "1", "active"}


def _unique_sorted(vals) -> list[str]:
    seen: dict[str, str] = {}
    for v in vals:
        v = str(v or "").strip()
        if v and _key(v) not in seen:
            seen[_key(v)] = v
    return sorted(seen.values(), key=str.casefold)


def _unique_in_order(vals) -> list[str]:
    seen: set[str] = set()
    out = []
    for v in vals:
        v = str(v or "").strip()
        if v and _key(v) not in seen:
            seen.add(_key(v))
            out.append(v)
    return out


def masters_from_frames(frames: dict[str, pd.DataFrame], sku_source: str = "SKU_Map tab") -> Masters:
    return Masters(
        sku=_clean(frames[SKU_MAP]),
        stores=_clean(frames[STORE_MAP]),
        varieties=_clean(frames[VARIETIES]),
        access=_clean(frames[ACCESS]),
        sku_source=sku_source,
        prod_base=frames.get(importer.PROD_BASE),
    )


def frames_from_values(raw: dict[str, list[list]]) -> tuple[dict[str, pd.DataFrame], str]:
    """Master frames from raw tab values. When the sheet has an
    'All Cux City' tab, the SKU mapping and varieties are built live from it
    (plus 'Mapping Whole' for origin and size) instead of the SKU_Map tab."""
    from core.sheets import frame_from_values

    frames = {t: frame_from_values(t, raw.get(t, [])) for t in MASTER_TABS}
    source = "SKU_Map tab"
    if any(any(str(c).strip() for c in row) for row in raw.get(importer.ALL_CUX_CITY, [])[1:]):
        sku_rows = importer.build_sku_map(raw.get(importer.MAPPING_WHOLE, []),
                                          raw[importer.ALL_CUX_CITY])
        frames[SKU_MAP] = pd.DataFrame(sku_rows, columns=TABS[SKU_MAP] + ["Spec-Grade", "Box-Kg"])
        frames[SKU_MAP]["_row"] = 0
        var = pd.DataFrame(importer.build_varieties(raw[importer.ALL_CUX_CITY]),
                           columns=TABS[VARIETIES])
        merged = pd.concat([frames[VARIETIES][TABS[VARIETIES]], var], ignore_index=True)
        frames[VARIETIES] = merged[merged["Variety"].astype(str).str.strip() != ""].drop_duplicates()
        frames[VARIETIES]["_row"] = 0
        source = f"live from '{importer.ALL_CUX_CITY}' + '{importer.MAPPING_WHOLE}'"
    extra_var = []
    for tab, values in raw.items():
        parent = importer.variety_tab_parent(tab)
        if parent:
            extra_var += importer.build_varieties_from_tab(parent, values)
    if extra_var:
        merged = pd.concat([frames[VARIETIES][TABS[VARIETIES]],
                            pd.DataFrame(extra_var, columns=TABS[VARIETIES])], ignore_index=True)
        merged["_k"] = merged["Parent SKU"].map(_key) + "|" + merged["Variety"].map(_key)
        frames[VARIETIES] = merged.drop_duplicates("_k").drop(columns="_k").reset_index(drop=True)
        frames[VARIETIES]["_row"] = 0
    base = importer.build_prod_base(raw.get(importer.PROD_BASE, []))
    if base:
        frames[importer.PROD_BASE] = pd.DataFrame(base)
    stores = importer.build_store_map(raw.get(importer.CUSTOMER_LIST, []))
    if stores:
        live = pd.DataFrame(stores, columns=TABS[STORE_MAP])
        merged = pd.concat([live, frames[STORE_MAP][TABS[STORE_MAP]]], ignore_index=True)
        merged["_k"] = merged.apply(lambda r: (_key(r["City"]), _key(r["Customer"]), _key(r["Store Name"])), axis=1)
        frames[STORE_MAP] = merged.drop_duplicates("_k").drop(columns="_k").reset_index(drop=True)
        frames[STORE_MAP]["_row"] = 0
    return frames, source


@st.cache_data(ttl=config.master_cache_seconds(), show_spinner="Loading master data…")
def _load_frames() -> tuple[dict[str, pd.DataFrame], str]:
    from core.sheets import get_backend

    backend = get_backend()
    present = set(backend.list_tabs())
    tabs = MASTER_TABS + [t for t in present
                          if t in importer.LEGACY_TABS or importer.variety_tab_parent(t)]
    return frames_from_values(backend.read_values_many(tabs))


@st.cache_data(ttl=config.master_cache_seconds(), show_spinner=False)
def _new_mapping_sku() -> pd.DataFrame | None:
    """Old SKU map + Combination 1 names (New Mapping sheet), or None when it cannot be read."""
    from core import mapping_sheet
    try:
        combos, _ = mapping_sheet.load()
    except Exception:  # noqa: BLE001 - the old sheet keeps working when the new one cannot be read
        return None
    frames, _ = _load_frames()
    old = _clean(frames[SKU_MAP])
    cities = {mapping_sheet._k(c) for c in list(old["City"]) + list(_clean(frames[STORE_MAP])["City"]) if str(c).strip()}
    return mapping_sheet.sku_rows(combos, old, cities)


def _parent_varieties() -> dict:
    from core import mapping_sheet
    try:
        _, parent = mapping_sheet.load()
    except Exception:  # noqa: BLE001
        return {}
    return parent_varieties(parent)


def parent_varieties(parent: pd.DataFrame) -> dict:
    """{parent key: varieties in sheet order} ('Mandarin' -> Xinyu, Wogan, …); the fruit's own name and
    '(no variety)' are left out."""
    out: dict[str, list[str]] = {}
    if parent is None or parent.empty:
        return out
    for p, g in zip(parent["parent"], parent["grade"]):
        g = " ".join(str(g or "").split())
        if not g or _key(g) in (_key(p), "novariety") or g.startswith("("):
            continue
        lst = out.setdefault(_key(p), [])
        if g not in lst:
            lst.append(g)
    return out


def _combo_varieties(m: Masters) -> dict:
    """{(city, customer, our name) keys: variety} for SKUs whose Combination 'Customer Variety' names exactly
    one known variety. Several ('Gala, RD, Queen, …' for Snacky / Daily Apple) or none -> left out."""
    from core import mapping_sheet
    try:
        combos, _ = mapping_sheet.load()
    except Exception:  # noqa: BLE001 - without the new sheet the old rules still apply
        return {}
    return combo_varieties(combos, m.varieties_for)


def combo_varieties(combos: pd.DataFrame, varieties_for) -> dict:
    from core.mapping_sheet import _k as mk
    found: dict[tuple, set] = {}
    for r in combos.to_dict("records"):
        vs = varieties_for(r.get("parent", ""))
        if not vs:
            continue
        key = (mk(r["city"]), mk(r["customer"]), mk(r["our"]))
        got = found.setdefault(key, set())
        for part in re.split(r"[,/]", str(r.get("cust_variety") or "")):
            v = next((x for x in vs if _key(x) == _key(part)), "") or name_variety(vs, part)
            if v:
                got.add(v)
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1}


def load_masters() -> Masters:
    from core import mapping_sheet
    frames, source = _load_frames()
    m = masters_from_frames(frames, source)
    if mapping_sheet.use_new():
        sku = _new_mapping_sku()
        m.parent_varieties = _parent_varieties()
        m.combo_variety = _combo_varieties(m)
        if sku is not None:
            m.sku = sku
            m.sku_source = f"{source} + New Mapping (Combination 1)"
    return m


def clear_cache() -> None:
    from core import mapping_sheet
    _load_frames.clear()
    _new_mapping_sku.clear()
    mapping_sheet.clear_cache()
