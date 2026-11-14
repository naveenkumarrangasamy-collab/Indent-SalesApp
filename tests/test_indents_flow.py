"""Submit / update / freeze against the local CSV back end (section 9)."""
import pandas as pd
import pytest

from core import indents
from core.masters import masters_from_frames
from core.models import IndentHeader, IndentLine
from core.schema import CHANGE_LOG, INDENT_LINES, PO_FREEZE, SKU_MAP, STORE_MAP, TABS, VARIETIES, ACCESS
from core.sheets import LocalBackend


@pytest.fixture
def backend(tmp_path, monkeypatch):
    b = LocalBackend(tmp_path)
    b.ensure_tabs()
    monkeypatch.setattr(indents, "get_backend", lambda: b)
    return b


from datetime import datetime, timedelta

from core import config

TOMORROW = (config.now_ist().date() + timedelta(days=1)).isoformat()
H = IndentHeader(TOMORROW, "Bangalore", "Zepto", "Store A", "07:00")
HASS = IndentLine("Avocado", "1PC - Hass Avocado Imported", "", "Pcs", 30, 120)
BLUE = IndentLine("Blueberry", "1PC - Blueberry Imported", "", "Pcs", 10, 300)


def test_submit_writes_version_1(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "s@x.com")
    assert iid.startswith("IND-") and iid.endswith("-BAN-0001")
    df = indents.read_lines(fresh=True)
    assert len(df) == 2 and set(df["version"]) == {1} and set(df["status"]) == {"Submitted"}
    assert df["amount"].tolist() == [3600, 3000]
    assert df["submitted_at"].iloc[0].endswith("+05:30")
    assert indents.submit_new(H, [HASS], "s@x.com").endswith("-0002")


def test_update_appends_version_and_change_log(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "s@x.com")
    hass40 = IndentLine(**{**HASS.to_dict(), "qty": 40})
    h2 = IndentHeader(**{**H.to_dict(), "expected_time": "08:00"})
    kiwi = IndentLine("Kiwi", "2PC - Green Kiwi", "", "Pcs", 5, 50)
    v, log_ok = indents.submit_update(iid, 1, h2, [hass40, kiwi], "o@x.com")
    assert v == 2 and log_ok
    df = indents.read_lines(fresh=True)
    assert len(df) == 4  # v1 (2 lines) kept, v2 (2 lines) appended
    cur = indents.snapshot(df, iid)
    assert cur.version == 2 and [x.customer_sku_name for x in cur.lines] == [
        "1PC - Hass Avocado Imported", "2PC - Green Kiwi"]
    log = backend.read(CHANGE_LOG)
    kinds = sorted(zip(log["change_type"], log["field"]))
    assert ("header_changed", "expected_time") in kinds
    assert ("line_changed", "qty") in kinds
    assert ("line_added", "") in kinds and ("line_removed", "") in kinds
    assert set(log["changed_by"]) == {"o@x.com"}


def test_stale_base_version_is_a_conflict(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 31})], "a@x.com")
    with pytest.raises(indents.ConflictError):
        indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 99})], "b@x.com")


def test_nothing_changed(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    with pytest.raises(indents.NothingChangedError):
        indents.submit_update(iid, 1, H, [HASS], "s@x.com")


def test_freeze_blocks_edits(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    v = indents.freeze(iid, 1, "PO-123.pdf", "s@x.com")
    assert v == 2
    df = indents.read_lines(fresh=True)
    assert indents.snapshot(df, iid).status == "Frozen"
    po = backend.read(PO_FREEZE)
    assert po.iloc[0]["po_file_name"] == "PO-123.pdf" and po.iloc[0]["po_store"] == "Store A"
    with pytest.raises(indents.FrozenError):
        indents.submit_update(iid, 2, H, [IndentLine(**{**HASS.to_dict(), "qty": 1})], "s@x.com")


def test_lost_race_removes_own_rows_and_retries(backend, monkeypatch):
    """Another user writes the same id between our read and our append."""
    real_append = backend.append_dicts
    state = {"done": False}

    def racing_append(tab, dicts):
        if tab == INDENT_LINES and not state["done"]:
            state["done"] = True
            other = [dict(d, submitted_by="other@x.com", submitted_at="2026-11-14T10:00:00+05:30")
                     for d in dicts]
            real_append(tab, other)
        return real_append(tab, dicts)

    monkeypatch.setattr(backend, "append_dicts", racing_append)
    iid = indents.submit_new(H, [HASS], "me@x.com")
    df = indents.read_lines(fresh=True)
    assert iid.endswith("-0002")
    assert df.groupby(["indent_id", "version"]).size().max() == 1  # no duplicates left
    assert set(df["submitted_by"]) == {"other@x.com", "me@x.com"}


def test_versions_and_summary(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    for q in range(31, 44):
        cur = indents.snapshot(indents.read_lines(fresh=True), iid)
        indents.submit_update(iid, cur.version, H, [IndentLine(**{**HASS.to_dict(), "qty": q})], "s@x.com")
    df = indents.read_lines(fresh=True)
    vers = indents.versions(df, iid)
    assert len(vers) == 14 and vers.iloc[0]["version"] == 14  # UI shows head(10)
    s = indents.summary(df)
    assert s.iloc[0]["version"] == 14 and s.iloc[0]["created_by"] == "s@x.com"


def _masters():
    sku = pd.DataFrame([
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Tanzania", "20C", "Y", "", ""],
        ["Bangalore", "Zepto", "Apple", "2PC - Apple Queen Imported", "", "", "Y", "Queen", ""],
    ], columns=TABS[SKU_MAP])
    stores = pd.DataFrame([["Bangalore", "Zepto", "Store A"], ["Bangalore", "Swiggy", "Store S"]],
                          columns=TABS[STORE_MAP])
    var = pd.DataFrame([["Apple", "Queen"], ["Apple", "Gala"]], columns=TABS[VARIETIES])
    return masters_from_frames({SKU_MAP: sku, STORE_MAP: stores, VARIETIES: var,
                                ACCESS: pd.DataFrame(columns=TABS[ACCESS])})


def test_validate_rules():
    m = _masters()
    assert indents.validate(H, [HASS], m) == []
    apple = IndentLine("Apple", "2PC - Apple Queen Imported", "", "Pcs", 1, 1)
    assert any("variety" in e for e in indents.validate(H, [apple], m))
    assert indents.validate(H, [IndentLine(**{**apple.to_dict(), "variety": "Queen"})], m) == []
    errs = indents.validate(H, [HASS, HASS], m)
    assert any("more than once" in e for e in errs)
    bad = IndentLine(**{**HASS.to_dict(), "qty": 0, "price": -1, "lot": ""})
    errs = indents.validate(H, [bad], m)
    assert len(errs) == 3
    other_store = IndentHeader(**{**H.to_dict(), "store": "Store S"})
    assert any("not mapped" in e for e in indents.validate(other_store, [HASS], m))
    assert indents.validate(H, [], m) == ["Add at least one item."]


def test_store_and_customer_lists():
    m = _masters()
    assert m.stores_for("Bangalore", "Zepto") == ["Store A"]
    assert m.stores_for("bangalore", "swiggy") == ["Store S"]
    assert m.customers("Bangalore") == ["Zepto", "Swiggy"]  # from the sheet, in sheet order
    assert m.needs_variety("Apple") and not m.needs_variety("Avocado")
    assert m.default_variety("Bangalore", "Zepto", "2PC - Apple Queen Imported") == "Queen"



def test_edit_deadline_is_next_day_noon():
    d = indents.edit_deadline("2026-11-14T18:20:05+05:30")
    assert d.isoformat() == "2026-11-15T12:00:00+05:30"
    ist = config.IST
    assert indents.can_edit("2026-11-14T18:20:05+05:30", datetime(2026, 11, 15, 11, 59, tzinfo=ist))
    assert not indents.can_edit("2026-11-14T18:20:05+05:30", datetime(2026, 11, 15, 12, 0, tzinfo=ist))
    assert indents.can_edit("2026-11-14T00:05:00+05:30", datetime(2026, 11, 14, 23, 0, tzinfo=ist))


def test_update_blocked_after_cutoff(backend, monkeypatch):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    later = config.now_ist() + timedelta(days=2)
    monkeypatch.setattr(indents.config, "now_ist", lambda: later)
    with pytest.raises(indents.CutoffError, match="edit window closed"):
        indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 99})], "s@x.com")


def test_delivery_date_must_be_after_today(backend):
    today = config.now_ist().date().isoformat()
    with pytest.raises(indents.SheetError, match="after today"):
        indents.submit_new(IndentHeader(**{**H.to_dict(), "delivery_date": today}), [HASS], "s@x.com")
    m = _masters()
    errs = indents.validate(IndentHeader(**{**H.to_dict(), "delivery_date": today}), [HASS], m,
                            min_date=indents.min_delivery_date())
    assert any("Delivery date must be on or after" in e for e in errs)
    assert indents.min_delivery_date("2026-11-14T18:00:00+05:30").isoformat() == "2026-11-15"


def test_summary_marks_editable(backend):
    indents.submit_new(H, [HASS], "s@x.com")
    s = indents.summary(indents.read_lines(fresh=True))
    assert bool(s.iloc[0]["can_edit"]) is True
