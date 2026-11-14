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
H = IndentHeader(TOMORROW, "Bangalore", "Zepto", "Store A", "10:30")
HASS = IndentLine("Avocado", "1PC - Hass Avocado Imported", "", "Pcs", 30, 120)
BLUE = IndentLine("Blueberry", "1PC - Blueberry Imported", "", "Pcs", 10, 300)


def test_submit_writes_version_1(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "s@x.com")
    assert iid.startswith("IND-") and iid.endswith("-BAN-0001")
    df = indents.read_lines(fresh=True)
    assert len(df) == 2 and set(df["version"]) == {1} and set(df["status"]) == {"Submitted"}
    assert df["amount"].tolist() == [3600, 3000]
    assert df["submitted_at"].iloc[0].endswith("+05:30")
    with pytest.raises(indents.DuplicateError):  # same store + date
        indents.submit_new(H, [HASS], "s@x.com")
    other_store = IndentHeader(**{**H.to_dict(), "store": "Store B"})
    assert indents.submit_new(other_store, [HASS], "s@x.com").endswith("-0002")


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
            other = [dict(d, submitted_by="other@x.com", submitted_at="2026-11-14T10:00:00+05:30",
                          store="Store Z") for d in dicts]
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


def test_delivery_date_today_or_tomorrow(backend):
    today = config.now_ist().date()
    day_after = (today + timedelta(days=2)).isoformat()
    with pytest.raises(indents.SheetError, match="today"):
        indents.submit_new(IndentHeader(**{**H.to_dict(), "delivery_date": day_after}), [HASS], "s@x.com")
    yesterday = (today - timedelta(days=1)).isoformat()
    assert not indents.date_allowed(yesterday) and indents.date_allowed(today.isoformat())
    assert indents.date_allowed(yesterday, keep=yesterday)        # a correction keeps its own date
    iid = indents.submit_new(IndentHeader(**{**H.to_dict(), "delivery_date": today.isoformat()}), [HASS], "s@x.com")
    assert iid
    m = _masters()
    errs = indents.validate(IndentHeader(**{**H.to_dict(), "delivery_date": day_after}), [HASS], m,
                            check_date=True)
    assert any("Delivery date must be today" in e for e in errs)


def test_summary_marks_editable(backend):
    indents.submit_new(H, [HASS], "s@x.com")
    s = indents.summary(indents.read_lines(fresh=True))
    assert bool(s.iloc[0]["can_edit"]) is True


def test_qty_must_be_whole_number():
    m = _masters()
    errs = indents.validate(H, [IndentLine(**{**HASS.to_dict(), "qty": 2.5})], m)
    assert any("whole number" in e for e in errs)


def test_lot_size_written_to_sheet(backend):
    indents.submit_new(H, [HASS], "s@x.com")
    assert backend.read("Indent_Lines").iloc[0]["lot_size"] == "1 Pcs"


def test_typed_delivery_times():
    from pages_src.delivery import parse_time
    assert parse_time("6:45 pm") == "18:45" and parse_time("0730") == "07:30"
    assert parse_time("12 am") == "00:00" and parse_time("25:00") is None and parse_time("abc") is None


def test_typed_time_survives_stale_check():
    from pages_src.delivery import parse_time
    for t in ("18:45", "07:10", "00:00"):
        assert parse_time(t) == t  # what _drop_stale relies on to keep typed times
    assert parse_time("11:01") == "11:01"


def test_one_indent_per_store_per_date_and_update_cannot_collide(backend):
    a = indents.submit_new(H, [HASS], "s@x.com")
    b_hdr = IndentHeader(**{**H.to_dict(), "store": "Store B"})
    b = indents.submit_new(b_hdr, [HASS], "s@x.com")
    # moving B onto A's store and date is refused; A itself can still be edited
    with pytest.raises(indents.DuplicateError) as e:
        indents.submit_update(b, 1, H, [HASS], "s@x.com")
    assert e.value.indent_id == a
    v, _ = indents.submit_update(a, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 31})], "s@x.com")
    assert v == 2
    df = indents.read_lines(fresh=True)
    assert indents.find_duplicate(df, H) == a
    assert indents.find_duplicate(df, H, exclude_id=a) is None
    later = IndentHeader(**{**H.to_dict(), "delivery_date": "2099-01-01"})
    assert indents.find_duplicate(df, later) is None


def test_delivery_window_and_pack_lot(backend):
    m = _masters()
    early = IndentHeader(**{**H.to_dict(), "expected_time": "07:00"})
    assert any("between 10:00 and 20:00" in e for e in indents.validate(early, [HASS], m))
    late = IndentHeader(**{**H.to_dict(), "expected_time": "20:30"})
    assert any("between" in e for e in indents.validate(late, [HASS], m))
    # rows saved earlier with lot "gms" read back as "Pack"
    gms = IndentLine("Grapes", "200gm - Crimson grapes", "", "gms", 5, 10)
    iid = indents.submit_new(H, [gms], "s@x.com")
    assert indents.snapshot(indents.read_lines(fresh=True), iid).lines[0].lot == "Pack"


def test_variety_only_for_apple():
    m = _masters()
    import pandas as pd
    from core.schema import VARIETIES
    m.varieties = pd.concat([m.varieties, pd.DataFrame([["Kiwi", "Gold"]], columns=TABS[VARIETIES])])
    assert m.varieties_for("Kiwi") == [] and not m.needs_variety("Kiwi")
    assert m.varieties_for("Apple") == ["Queen", "Gala"]
    m.varieties = m.varieties[m.varieties["Parent SKU"] != "Apple"]
    assert m.varieties_for("Apple")[:3] == ["Gala", "Granny Smith", "Queen"]  # default list



def test_change_note_in_indent_lines(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "a@x.com")
    indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 40})], "b@x.com")
    indents.cancel(iid, 2, "a@x.com")
    raw = backend.read("Indent_Lines")
    notes = raw.groupby("version")["change_note"].first().to_dict()
    assert notes["1"].startswith("Created by a@x.com on ")
    assert notes["2"].startswith("Edited by b@x.com (other user; created by a@x.com) on ")
    assert "1PC - Hass Avocado Imported: qty 30 → 40" in notes["2"] and "deleted 1PC - Blueberry Imported" in notes["2"]
    assert notes["3"].startswith("Deleted by a@x.com (same user) on ")
    assert set(raw[raw["version"] == "2"]["change_note"]) == {notes["2"]}   # same cell text on every row
    v = indents.versions(indents.read_lines(fresh=True), iid)
    assert v.iloc[0]["status"] == "Cancelled" and v.iloc[0]["change_note"].startswith("Deleted")


def test_open_indents_first_and_city_scope(backend):
    a = indents.submit_new(H, [HASS], "a@x.com")
    b = indents.submit_new(IndentHeader(**{**H.to_dict(), "store": "Store B"}), [HASS], "b@x.com")
    c = indents.submit_new(IndentHeader(**{**H.to_dict(), "store": "Store C", "city": "Chennai"}), [HASS], "a@x.com")
    indents.freeze(a, 1, "po.pdf", "a@x.com")
    s = indents.summary(indents.read_lines(fresh=True))
    assert list(s["status"]) == ["Submitted", "Submitted", "Frozen"]      # PO-frozen goes down
    from core.auth import User
    blr = User("b@x.com", "", "sales", ["bangalore"])
    assert set(indents.visible_to(s, blr)["indent_id"]) == {a, b}          # every indent in his city
    own = User("a@x.com", "", "sales")
    assert set(indents.visible_to(s, own)["indent_id"]) == {a, c}          # no city: own indents
    owner = User("o@x.com", "", "owner")
    assert len(indents.visible_to(s, owner)) == 3
    assert blr.can_work_on("Bangalore", "a@x.com") and not blr.can_work_on("Chennai", "b@x.com")
