"""Master data: SKU map, store map, varieties (and the Access tab).

`load_masters()` reads all four master tabs in one Sheets call and caches the
result for `master_refresh_minutes` (default 5 min). The query helpers below are
pure functions over the DataFrames so they are easy to test.
"""
from __future__ import annotations

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

    def store_index(self) -> dict[str, str]:
        """Every store name -> 'Customer · City' (for pickers)."""
        out: dict[str, str] = {}
        for city, customer, store in zip(self.stores["City"], self.stores["Customer"], self.stores["Store Name"]):
            store = " ".join(str(store).split())
            if store and store not in out:
                out[store] = f"{customer} · {city or 'all cities'}"
        return out

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

    def default_variety(self, city: str, customer: str, sku_name: str) -> str:
        parent = self.parent_of(city, customer, sku_name)
        if not self.varieties_for(parent):
            return ""
        fixed = self.variety_from_name(parent, sku_name)
        if fixed:
            return fixed
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        vals = [v for v in df.get("Variety", pd.Series(dtype=str)) if v]
        return vals[0] if vals else ""

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
            return []
        df = self.varieties
        df = df[df["Parent SKU"].map(_key) == _key(parent)]
        found = _unique_in_order(df["Variety"])
        if not found and _key(parent) == "apple":
            found = list(config.DEFAULT_APPLE_VARIETIES)
        return found

    def variety_from_name(self, parent: str, sku_name: str) -> str:
        """The variety written in an Apple SKU name ('Royal Gala' -> Gala,
        'Red Delicious' -> RD, 'Green Imported (Granny Smith)' -> Granny Smith).
        '' when the name does not say (Apple Snacky, Daily Apple) -> user picks."""
        varieties = self.varieties_for(parent)
        if not varieties or not sku_name:
            return ""
        import re as _re
        text = " ".join(str(sku_name).split()).casefold()
        aliases = {"royal gala": "Gala", "red delicious": "RD", "granny": "Granny Smith"}
        candidates = [(v.casefold(), v) for v in varieties]
        candidates += [(a, v) for a, v in aliases.items()
                       if v in varieties and a not in {c for c, _ in candidates}]
        best = None
        for phrase, variety in candidates:
            m = _re.search(r"(?<![a-z0-9])" + _re.escape(phrase) + r"(?![a-z0-9])", text)
            if m and (best is None or (m.start(), -len(phrase)) < (best[0], -best[1])):
                best = (m.start(), len(phrase), variety)
        return best[2] if best else ""

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
        frames[SKU_MAP] = pd.DataFrame(sku_rows, columns=TABS[SKU_MAP])
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


def load_masters() -> Masters:
    frames, source = _load_frames()
    return masters_from_frames(frames, source)


def clear_cache() -> None:
    _load_frames.clear()
