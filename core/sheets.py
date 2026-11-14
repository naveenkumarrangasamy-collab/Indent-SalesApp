"""Google Sheets access (gspread + service account) with a local CSV fallback.

Everything is read and written by header name. Both back ends expose the
same small API:

    read(tab) / read_many(tabs)      -> pandas DataFrame(s), all values str,
                                        plus a `_row` column (sheet row number)
    append_dicts(tab, dicts)         -> (first_row, last_row) written
    update_cells(tab, row, {col: v}) -> update some cells of one row
    delete_rows(tab, first, last)    -> only used to undo the app's own
                                        just-written rows after a clash
    ensure_tabs()                    -> create missing tabs with headers
"""
from __future__ import annotations

import csv
import os
import re
import threading
import time
from pathlib import Path

import pandas as pd

from core import config
from core.schema import TABS, norm_header


class SheetError(Exception):
    """A problem talking to the sheet, with a message fit to show users."""


# --------------------------------------------------------------------------
# Helpers shared by both back ends
# --------------------------------------------------------------------------

def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def _to_cell(v):
    """Python value -> value written to the sheet (RAW)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _canonical_for(tab: str, header_cell: str) -> str | None:
    key = norm_header(header_cell)
    if not key:
        return None
    for canon in TABS.get(tab, []):
        if norm_header(canon) == key:
            return canon
    return None


def frame_from_values(tab: str, values: list[list]) -> pd.DataFrame:
    """Turn raw cell values (row 1 = header) into a DataFrame.

    Columns are renamed to their canonical names when they match ignoring
    case, spaces, '-' and '_'. Missing canonical columns are added empty.
    Blank rows are dropped. `_row` keeps the 1-based sheet row number.
    """
    canon_cols = TABS.get(tab, [])
    if not values:
        return pd.DataFrame(columns=canon_cols + ["_row"])
    header = [_cell_str(h).strip() for h in values[0]]
    keep: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i, h in enumerate(header):
        if not h:
            continue
        name = _canonical_for(tab, h) or h
        if name in seen:
            continue
        seen.add(name)
        keep.append((i, name))
    records = []
    for r_idx, row in enumerate(values[1:], start=2):
        rec = {name: (_cell_str(row[i]).strip() if i < len(row) else "") for i, name in keep}
        if not any(rec.values()):
            continue
        rec["_row"] = r_idx
        records.append(rec)
    df = pd.DataFrame(records, columns=[n for _, n in keep] + ["_row"])
    for c in canon_cols:
        if c not in df.columns:
            df[c] = ""
    return df


def _parse_updated_range(rng: str) -> tuple[int, int]:
    m = re.search(r"![A-Z]+(\d+)(?::[A-Z]+(\d+))?$", rng or "")
    if not m:
        raise SheetError("Saved, but could not read back where the rows were written.")
    first = int(m.group(1))
    last = int(m.group(2) or first)
    return first, last


class _Base:
    mode = "base"

    def __init__(self):
        self._headers: dict[str, list[str]] = {}

    # raw operations implemented by subclasses ----------------------------
    def list_tabs(self) -> list[str]: raise NotImplementedError
    def _get_values(self, tabs: list[str]) -> dict[str, list[list]]: raise NotImplementedError
    def _append_raw(self, tab: str, rows: list[list]) -> tuple[int, int]: raise NotImplementedError
    def _update_raw(self, tab: str, row: int, cells: dict[int, object]) -> None: raise NotImplementedError
    def _delete_raw(self, tab: str, first: int, last: int) -> None: raise NotImplementedError
    def _create_tab(self, tab: str, header: list[str]) -> None: raise NotImplementedError
    def _set_header(self, tab: str, header: list[str]) -> None: raise NotImplementedError

    # public API ----------------------------------------------------------
    def read_values(self, tab: str) -> list[list]:
        """Raw values of any tab (used for the team's own mapping tabs)."""
        return self._get_values([tab]).get(tab, [])

    def read_values_many(self, tabs: list[str]) -> dict[str, list[list]]:
        """Raw values of several tabs in one call; missing tabs give []."""
        return self._get_values(tabs)

    def read_many(self, tabs: list[str]) -> dict[str, pd.DataFrame]:
        raw = self._get_values(tabs)
        out = {}
        for tab in tabs:
            values = raw.get(tab, [])
            self._headers[tab] = [_cell_str(h).strip() for h in values[0]] if values else []
            out[tab] = frame_from_values(tab, values)
        return out

    def read(self, tab: str) -> pd.DataFrame:
        return self.read_many([tab])[tab]

    def _header(self, tab: str) -> list[str]:
        """Current header of a tab; creates the tab or adds missing columns."""
        header = self._headers.get(tab)
        if header is None:
            values = self._get_values([tab]).get(tab, [])
            header = [_cell_str(h).strip() for h in values[0]] if values else []
        if tab not in self.list_tabs():
            header = list(TABS.get(tab, []))
            self._create_tab(tab, header)
        elif not any(header):
            header = list(TABS.get(tab, []))
            self._set_header(tab, header)
        present = {_canonical_for(tab, h) for h in header}
        missing = [c for c in TABS.get(tab, []) if c not in present]
        if missing:
            header = header + missing
            self._set_header(tab, header)
        self._headers[tab] = header
        return header

    def _row_from_dict(self, tab: str, header: list[str], d: dict) -> list:
        row = []
        for h in header:
            canon = _canonical_for(tab, h) or h
            row.append(_to_cell(d.get(canon, "")))
        return row

    def append_dicts(self, tab: str, dicts: list[dict]) -> tuple[int, int]:
        if not dicts:
            return (0, -1)
        header = self._header(tab)
        rows = [self._row_from_dict(tab, header, d) for d in dicts]
        return self._append_raw(tab, rows)

    def update_cells(self, tab: str, row_number: int, values: dict) -> None:
        header = self._header(tab)
        cells: dict[int, object] = {}
        for col_idx, h in enumerate(header):
            canon = _canonical_for(tab, h) or h
            if canon in values:
                cells[col_idx] = _to_cell(values[canon])
        if cells:
            self._update_raw(tab, row_number, cells)

    def delete_rows(self, tab: str, first: int, last: int) -> None:
        if last >= first >= 2:
            self._delete_raw(tab, first, last)

    def ensure_tabs(self, tabs: list[str] | None = None) -> list[str]:
        """Create any missing app tabs (header row only). Returns created names."""
        created = []
        existing = set(self.list_tabs())
        for tab in tabs or list(TABS):
            if tab not in existing:
                self._create_tab(tab, list(TABS[tab]))
                created.append(tab)
            else:
                self._header(tab)  # adds missing header columns, if any
        return created


# --------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------

_RETRY_DELAYS = [1, 2, 4, 8, 16]
_RETRY_CODES = {429, 500, 502, 503, 504}


def _friendly(code: int | None, err: Exception) -> str:
    if code == 429:
        return ("Google Sheets is busy (too many requests this minute). "
                "Nothing was lost; please try again in a minute.")
    if code == 403:
        return ("The app's service account cannot open the sheet. Share the sheet "
                "with the service account email as Editor.")
    if code == 404:
        return "The Google Sheet was not found. Check `sheet_id` in the app secrets."
    if code and code >= 500:
        return "Google Sheets is temporarily unavailable. Please try again shortly."
    return f"Could not reach Google Sheets ({err})."


class GoogleBackend(_Base):
    mode = "gsheets"

    def __init__(self, sheet_id: str, sa_info: dict):
        super().__init__()
        import gspread
        from google.oauth2.service_account import Credentials

        self._gspread = gspread
        creds = Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.client = gspread.authorize(creds)
        self.sheet_id = sheet_id
        self.service_email = sa_info.get("client_email", "")
        self._ss = None
        self._ws: dict[str, object] = {}
        self._tabs_cache: tuple[float, list[str]] | None = None

    def _call(self, fn, *args, **kwargs):
        import requests

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                return fn(*args, **kwargs)
            except self._gspread.exceptions.APIError as e:
                resp = getattr(e, "response", None)
                code = getattr(resp, "status_code", None)
                if code in _RETRY_CODES and attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise SheetError(_friendly(code, e)) from e
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise SheetError(_friendly(None, e)) from e
            except self._gspread.exceptions.SpreadsheetNotFound as e:
                raise SheetError(_friendly(404, e)) from e

    @property
    def ss(self):
        if self._ss is None:
            self._ss = self._call(self.client.open_by_key, self.sheet_id)
        return self._ss

    def list_tabs(self) -> list[str]:
        if self._tabs_cache and time.time() - self._tabs_cache[0] < 300:
            return self._tabs_cache[1]
        sheets = self._call(self.ss.worksheets)
        self._ws = {w.title: w for w in sheets}
        names = [w.title for w in sheets]
        self._tabs_cache = (time.time(), names)
        return names

    def _worksheet(self, tab: str):
        if tab not in self._ws:
            self._tabs_cache = None
            self.list_tabs()
        if tab not in self._ws:
            raise SheetError(f"The tab '{tab}' does not exist in the sheet.")
        return self._ws[tab]

    def _get_values(self, tabs: list[str]) -> dict[str, list[list]]:
        existing = set(self.list_tabs())
        wanted = [t for t in tabs if t in existing]
        out: dict[str, list[list]] = {t: [] for t in tabs}
        if not wanted:
            return out
        ranges = ["'" + t.replace("'", "''") + "'" for t in wanted]
        resp = self._call(self.ss.values_batch_get, ranges,
                          params={"valueRenderOption": "UNFORMATTED_VALUE",
                                  "dateTimeRenderOption": "FORMATTED_STRING"})
        for tab, vr in zip(wanted, resp.get("valueRanges", [])):
            out[tab] = vr.get("values", [])
        return out

    def _append_raw(self, tab, rows):
        ws = self._worksheet(tab)
        resp = self._call(ws.append_rows, rows, value_input_option="RAW",
                          insert_data_option="INSERT_ROWS", table_range="A1")
        return _parse_updated_range(((resp or {}).get("updates") or {}).get("updatedRange", ""))

    def _update_raw(self, tab, row, cells):
        from gspread.utils import rowcol_to_a1

        ws = self._worksheet(tab)
        data = [{"range": rowcol_to_a1(row, c + 1), "values": [[v]]} for c, v in cells.items()]
        self._call(ws.batch_update, data, value_input_option="RAW")

    def _delete_raw(self, tab, first, last):
        ws = self._worksheet(tab)
        self._call(ws.delete_rows, first, last)

    def _create_tab(self, tab, header):
        ws = self._call(self.ss.add_worksheet, title=tab, rows=1000, cols=max(len(header), 8))
        self._call(ws.update, range_name="A1", values=[header], value_input_option="RAW")
        try:
            self._call(ws.freeze, rows=1)
        except SheetError:
            pass
        self._ws[tab] = ws
        self._tabs_cache = None
        self._headers[tab] = list(header)

    def _set_header(self, tab, header):
        ws = self._worksheet(tab)
        if ws.col_count < len(header):
            self._call(ws.add_cols, len(header) - ws.col_count)
        self._call(ws.update, range_name="A1", values=[header], value_input_option="RAW")
        self._headers[tab] = list(header)

    def sheet_url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit"


# --------------------------------------------------------------------------
# Local CSV files (development without Google credentials)
# --------------------------------------------------------------------------

class LocalBackend(_Base):
    mode = "local"
    service_email = "(local mode, no service account)"

    def __init__(self, folder: str | os.PathLike):
        super().__init__()
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, tab: str) -> Path:
        return self.folder / f"{tab}.csv"

    def _read_file(self, tab: str) -> list[list[str]]:
        p = self._path(tab)
        if not p.exists():
            return []
        with p.open(newline="", encoding="utf-8") as f:
            return [row for row in csv.reader(f)]

    def _write_file(self, tab: str, values: list[list]) -> None:
        p = self._path(tab)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([[_cell_str(v) for v in row] for row in values])
        tmp.replace(p)

    def list_tabs(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.csv"))

    def _get_values(self, tabs):
        with self._lock:
            return {t: self._read_file(t) for t in tabs}

    def _append_raw(self, tab, rows):
        with self._lock:
            values = self._read_file(tab)
            first = len(values) + 1
            values.extend(rows)
            self._write_file(tab, values)
            return first, first + len(rows) - 1

    def _update_raw(self, tab, row, cells):
        with self._lock:
            values = self._read_file(tab)
            if row > len(values):
                raise SheetError(f"Row {row} not found in {tab}.")
            r = values[row - 1]
            for c, v in cells.items():
                while len(r) <= c:
                    r.append("")
                r[c] = _cell_str(v)
            self._write_file(tab, values)

    def _delete_raw(self, tab, first, last):
        with self._lock:
            values = self._read_file(tab)
            del values[first - 1:last]
            self._write_file(tab, values)

    def _create_tab(self, tab, header):
        with self._lock:
            self._write_file(tab, [header])
            self._headers[tab] = list(header)

    def _set_header(self, tab, header):
        with self._lock:
            values = self._read_file(tab) or [[]]
            values[0] = header
            self._write_file(tab, values)
            self._headers[tab] = list(header)

    def sheet_url(self) -> str:
        return str(self.folder.resolve())


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

LOCAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


CONNECT_ERROR = {"reason": ""}


def make_backend():
    ok, reason = config.google_status()
    CONNECT_ERROR["reason"] = reason
    if ok:
        try:
            return GoogleBackend(config.sheet_id(), config.service_account_info())
        except Exception as e:  # bad key etc.: fall back, and say why on every page
            CONNECT_ERROR["reason"] = f"The service account key could not be used ({type(e).__name__}: {e})."
    # Local mode: start from the committed seed files on first run.
    seed = LOCAL_DATA_DIR / "seed"
    if seed.is_dir() and not any(LOCAL_DATA_DIR.glob("*.csv")):
        import shutil
        for f in seed.glob("*.csv"):
            shutil.copy(f, LOCAL_DATA_DIR / f.name)
    return LocalBackend(LOCAL_DATA_DIR)


import streamlit as st  # noqa: E402  (kept here so the pure helpers above import fast)


@st.cache_resource(show_spinner=False)
def _cached_backend():
    return make_backend()


def get_backend():
    """One back end per server process, shared by all sessions.

    Streamlit keeps cached objects across code updates. After a redeploy the
    cached object can be an instance of the *old* class (missing new
    methods), so it is rebuilt whenever its class is not the current one.
    """
    backend = _cached_backend()
    if type(backend) not in (GoogleBackend, LocalBackend):
        _cached_backend.clear()
        backend = _cached_backend()
    return backend
