"""Exercises GoogleBackend against an in-memory fake of gspread."""
import re

import gspread
import pytest

from core import sheets


class FakeWS:
    def __init__(self, title, rows=1000, cols=8):
        self.title, self.grid, self.col_count = title, [], cols

    def _ensure(self, r, c):
        while len(self.grid) < r:
            self.grid.append([])
        row = self.grid[r - 1]
        while len(row) < c:
            row.append("")

    def update(self, values, range_name=None, **kw):
        m = re.match(r"([A-Z]+)(\d+)", range_name)
        r = int(m.group(2))
        for i, row in enumerate(values):
            self._ensure(r + i, len(row))
            self.grid[r + i - 1][:len(row)] = row

    def append_rows(self, rows, value_input_option=None, insert_data_option=None, table_range=None):
        first = len(self.grid) + 1
        self.grid.extend([list(r) for r in rows])
        return {"updates": {"updatedRange": f"'{self.title}'!A{first}:Z{first + len(rows) - 1}"}}

    def batch_update(self, data, value_input_option=None):
        for d in data:
            m = re.match(r"([A-Z]+)(\d+)", d["range"])
            c = ord(m.group(1)) - 64
            r = int(m.group(2))
            self._ensure(r, c)
            self.grid[r - 1][c - 1] = d["values"][0][0]

    def delete_rows(self, a, b):
        del self.grid[a - 1:b]

    def freeze(self, rows=None):
        pass

    def add_cols(self, n):
        self.col_count += n


class FakeSS:
    def __init__(self):
        self.sheets = {}
        self.calls = 0

    def worksheets(self):
        return list(self.sheets.values())

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWS(title, rows, cols)
        return self.sheets[title]

    def values_batch_get(self, ranges, params=None):
        self.calls += 1
        out = []
        for r in ranges:
            t = r.strip("'").replace("''", "'")
            out.append({"values": [list(x) for x in self.sheets[t].grid]})
        return {"valueRanges": out}


@pytest.fixture
def gb(monkeypatch):
    ss = FakeSS()
    ss.add_worksheet("Mapping Whole", 10, 7).grid = [
        ["City", "Customer", "Parent SKU", "Customer SKU Name", "Spec-Origin", "Spec-Size", "Box Kgs"],
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Tanzania", "20C, 22C", "4Kg"]]

    class Client:
        def open_by_key(self, key):
            return ss
    monkeypatch.setattr(gspread, "authorize", lambda creds: Client())
    monkeypatch.setattr("google.oauth2.service_account.Credentials.from_service_account_info",
                        lambda info, scopes: object())
    b = sheets.GoogleBackend("sheet123", {"client_email": "sa@x.iam.gserviceaccount.com"})
    return b, ss


def test_ensure_tabs_and_round_trip(gb):
    b, ss = gb
    created = b.ensure_tabs()
    assert "Indent_Lines" in created and "Mapping Whole" not in created
    assert ss.sheets["Access"].grid[0][:3] == ["Email", "Name", "Role"]
    first, last = b.append_dicts("Access", [{"Email": "a@x.com", "Role": "sales", "Status": "active"}])
    assert (first, last) == (2, 2)
    df = b.read("Access")
    assert df.iloc[0]["Email"] == "a@x.com" and df.iloc[0]["_row"] == 2
    b.update_cells("Access", 2, {"Status": "revoked"})
    assert b.read("Access").iloc[0]["Status"] == "revoked"
    frames = b.read_many(["SKU_Map", "Store_Map", "Varieties", "Access"])
    assert set(frames) == {"SKU_Map", "Store_Map", "Varieties", "Access"}
    assert b.read_values("Mapping Whole")[1][4] == "Tanzania"


def test_numbers_come_back_as_text(gb):
    b, ss = gb
    b.ensure_tabs(["Indent_Lines"])
    b.append_dicts("Indent_Lines", [{"indent_id": "IND-1", "version": 1, "qty": 40.0, "price": 12.5}])
    r = b.read("Indent_Lines").iloc[0]
    assert (r["version"], r["qty"], r["price"]) == ("1", "40", "12.5")


def test_retry_then_friendly_error(gb, monkeypatch):
    b, ss = gb
    monkeypatch.setattr(sheets, "_RETRY_DELAYS", [0, 0])
    calls = {"n": 0}

    class Resp:
        status_code = 429
        text = "quota"

        def json(self):
            return {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}

    def flaky(*a, **k):
        calls["n"] += 1
        raise gspread.exceptions.APIError(Resp())
    with pytest.raises(sheets.SheetError, match="busy"):
        b._call(flaky)
    assert calls["n"] == 3  # first try + 2 retries


def test_stale_cached_backend_is_rebuilt(monkeypatch, tmp_path):
    """After a redeploy Streamlit may hand back an object of the old class."""
    class OldBackend:  # stands in for the pre-update class: no read_values_many
        pass

    calls = {"n": 0}

    def fake_make():
        calls["n"] += 1
        return OldBackend() if calls["n"] == 1 else sheets.LocalBackend(tmp_path)

    monkeypatch.setattr(sheets, "make_backend", fake_make)
    sheets._cached_backend.clear()
    b = sheets.get_backend()
    assert isinstance(b, sheets.LocalBackend) and hasattr(b, "read_values_many")
    assert sheets.get_backend() is b  # cached afterwards
    sheets._cached_backend.clear()


def test_bad_key_falls_back_with_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(sheets.config, "google_status", lambda: (True, ""))
    monkeypatch.setattr(sheets.config, "sheet_id", lambda: "abc")
    monkeypatch.setattr(sheets.config, "service_account_info",
                        lambda: {"client_email": "x", "private_key": "-----BEGIN PRIVATE KEY-----\nbad"})
    monkeypatch.setattr(sheets, "LOCAL_DATA_DIR", tmp_path)
    b = sheets.make_backend()
    assert b.mode == "local" and "could not be used" in sheets.CONNECT_ERROR["reason"]
    sheets.CONNECT_ERROR["reason"] = ""


def test_google_status_reasons(monkeypatch):
    from core import config
    monkeypatch.setattr(config, "_secrets", lambda: {})
    assert "sheet_id" in config.google_status()[1]
    monkeypatch.setattr(config, "_secrets", lambda: {"sheet_id": "x", "gcp_service_account": {"type": "service_account"}})
    assert "missing: project_id, private_key, client_email, token_uri" in config.google_status()[1]


def test_service_account_as_pasted_json(monkeypatch):
    import json
    from core import config
    key = {"type": "service_account", "project_id": "p", "client_email": "a@p.iam.gserviceaccount.com",
           "private_key": "-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n",
           "token_uri": "https://oauth2.googleapis.com/token"}
    monkeypatch.setattr(config, "_secrets", lambda: {"sheet_id": "s", "gcp_service_account_json": json.dumps(key)})
    assert config.google_status() == (True, "") and config.service_account_info()["client_email"] == key["client_email"]
    monkeypatch.setattr(config, "_secrets", lambda: {"sheet_id": "s", "gcp_service_account_json": "{oops"})
    assert "not valid JSON" in config.google_status()[1]


def test_local_mode_refreshes_stale_input_tabs(monkeypatch, tmp_path):
    """The server kept test data from the first deploy; inputs must refresh, outputs stay."""
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "Customer List.csv").write_text("City,Customer List,Store names\nPTP Bangalore,Zepto,Zepto - A\n")
    (seed / "Indent_Lines.csv").write_text("indent_id\n")
    (tmp_path / "Store_Map.csv").write_text("City,Customer,Store Name\nBangalore,Zepto,Zepto Sample Store 1 (local demo)\n")
    (tmp_path / "Customer List.csv").write_text("City,Customer List,Store names\nBangalore,Zepto,old\n")
    (tmp_path / "Indent_Lines.csv").write_text("indent_id\nIND-KEEP\n")
    monkeypatch.setattr(sheets, "LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(sheets.config, "google_status", lambda: (False, "no key"))
    sheets.make_backend()
    assert "Zepto - A" in (tmp_path / "Customer List.csv").read_text()
    assert not (tmp_path / "Store_Map.csv").exists()          # stale demo stores gone
    assert "IND-KEEP" in (tmp_path / "Indent_Lines.csv").read_text()  # saved indents kept
