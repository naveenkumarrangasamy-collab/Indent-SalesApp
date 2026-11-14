"""Master data: SKU map, store map, varieties (and the Access tab).

`load_masters()` reads all four master tabs in one Sheets call and caches the
result for `master_cache_seconds` (default 60 s). The query helpers below are
pure functions over the DataFrames so they are easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from core import config
from core.schema import (ACCESS, DEFAULT_CUSTOMERS, MASTER_TABS, SKU_MAP,
                         STORE_MAP, VARIETIES)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if c != "_row":
            df[c] = df[c].astype(str).str.strip()
    return df


def _key(s: str) -> str:
    return str(s or "").strip().casefold()


@dataclass
class Masters:
    sku: pd.DataFrame
    stores: pd.DataFrame
    varieties: pd.DataFrame
    access: pd.DataFrame

    # ---------------- lookups used by the screens ----------------
    def _sku_for(self, city: str, customer: str) -> pd.DataFrame:
        df = self.sku
        return df[(df["City"].map(_key) == _key(city)) & (df["Customer"].map(_key) == _key(customer))
                  & (df["Customer SKU Name"] != "")]

    def cities(self) -> list[str]:
        vals = list(self.sku["City"]) + list(self.stores["City"])
        return _unique_sorted(vals)

    def customers(self, city: str) -> list[str]:
        """The five MT customers first, then any other customer mapped for the city."""
        found = [c for c in list(self.sku.loc[self.sku["City"].map(_key) == _key(city), "Customer"])
                 + list(self.stores.loc[self.stores["City"].map(_key) == _key(city), "Customer"]) if c]
        out = list(DEFAULT_CUSTOMERS)
        known = {_key(c) for c in out}
        for c in _unique_sorted(found):
            if _key(c) not in known:
                out.append(c)
                known.add(_key(c))
        return out

    def has_sku_mapping(self, city: str, customer: str) -> bool:
        return not self._sku_for(city, customer).empty

    def stores_for(self, city: str, customer: str) -> list[str]:
        df = self.stores
        df = df[(df["City"].map(_key) == _key(city)) & (df["Customer"].map(_key) == _key(customer))]
        return _unique_sorted(df["Store Name"])

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

    def default_variety(self, city: str, customer: str, sku_name: str) -> str:
        df = self._sku_for(city, customer)
        df = df[df["Customer SKU Name"].map(_key) == _key(sku_name)]
        vals = [v for v in df.get("Variety", pd.Series(dtype=str)) if v]
        return vals[0] if vals else ""

    def varieties_for(self, parent: str) -> list[str]:
        df = self.varieties
        df = df[df["Parent SKU"].map(_key) == _key(parent)]
        return _unique_in_order(df["Variety"])

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


def masters_from_frames(frames: dict[str, pd.DataFrame]) -> Masters:
    return Masters(
        sku=_clean(frames[SKU_MAP]),
        stores=_clean(frames[STORE_MAP]),
        varieties=_clean(frames[VARIETIES]),
        access=_clean(frames[ACCESS]),
    )


@st.cache_data(ttl=config.master_cache_seconds(), show_spinner="Loading master data…")
def _load_frames() -> dict[str, pd.DataFrame]:
    from core.sheets import get_backend

    return get_backend().read_many(MASTER_TABS)


def load_masters() -> Masters:
    return masters_from_frames(_load_frames())


def clear_cache() -> None:
    _load_frames.clear()
