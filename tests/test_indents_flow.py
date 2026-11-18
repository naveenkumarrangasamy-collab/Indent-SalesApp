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
    assert iid == "IN-001"
    df = indents.read_lines(fresh=True)
    assert len(df) == 2 and set(df["version"]) == {1} and set(df["status"]) == {"Submitted"}
    assert df["amount"].tolist() == [3600, 3000]
    assert df["submitted_at"].iloc[0].endswith("+05:30")
    with pytest.raises(indents.DuplicateError):  # same store + date
        indents.submit_new(H, [HASS], "s@x.com")
    other_store = IndentHeader(**{**H.to_dict(), "store": "Store B"})
    assert indents.submit_new(other_store, [HASS], "s@x.com") == "IN-002"


def test_update_appends_version_and_change_log(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "s@x.com")
    hass40 = IndentLine(**{**HASS.to_dict(), "qty": 40})
    h2 = IndentHeader(**{**H.to_dict(), "expected_time": "08:00"})
    kiwi = IndentLine("Kiwi", "2PC - Green Kiwi", "", "Pcs", 5, 50)
    blue0 = IndentLine(**{**BLUE.to_dict(), "qty": 0})
    with pytest.raises(indents.SheetError, match="cannot be removed"):
        indents.submit_update(iid, 1, h2, [hass40, kiwi], "o@x.com")   # Blueberry dropped
    v, log_ok = indents.submit_update(iid, 1, h2, [hass40, blue0, kiwi], "o@x.com")
    assert v == 2 and log_ok
    df = indents.read_lines(fresh=True)
    assert len(df) == 5  # v1 (2 lines) kept, v2 (3 lines) appended
    cur = indents.snapshot(df, iid)
    assert cur.version == 2 and [x.customer_sku_name for x in cur.lines] == [
        "1PC - Hass Avocado Imported", "1PC - Blueberry Imported", "2PC - Green Kiwi"]
    log = backend.read(CHANGE_LOG)
    kinds = sorted(zip(log["change_type"], log["field"]))
    assert ("header_changed", "expected_time") in kinds
    assert ("line_changed", "qty") in kinds
    assert ("line_added", "") in kinds and ("line_removed", "") not in kinds
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
    v, frozen = indents.freeze(iid, 1, "PO-123.pdf", "s@x.com")
    assert v == 2 and frozen
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
    assert iid == "IN-002"
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
    assert any("must be Queen" in e for e in indents.validate(H, [apple], m))
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



def test_edit_deadline_is_11pm_on_delivery_day():
    """At 11:30 PM on 15 Nov the 15th is locked, the 16th is open until 11 PM (was 2 PM until 18 Nov)."""
    ist = config.IST
    now = datetime(2026, 11, 15, 23, 30, tzinfo=ist)
    assert indents.edit_deadline("2026-11-16").isoformat() == "2026-11-16T23:00:00+05:30"
    assert not indents.can_edit("2026-11-15", now)
    assert indents.can_edit("2026-11-16", now)
    assert indents.can_edit("2026-11-16", datetime(2026, 11, 16, 22, 59, tzinfo=ist))
    assert not indents.can_edit("2026-11-16", datetime(2026, 11, 16, 23, 0, tzinfo=ist))


def test_update_blocked_after_cutoff(backend, monkeypatch):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    later = config.now_ist() + timedelta(days=2)
    monkeypatch.setattr(indents.config, "now_ist", lambda: later)
    with pytest.raises(indents.CutoffError, match="editing closed"):
        indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 99})], "s@x.com")


def test_delivery_date_today_or_tomorrow(backend, monkeypatch):
    morning = datetime.combine(config.now_ist().date(), datetime.min.time(), tzinfo=config.IST) + timedelta(hours=9)
    monkeypatch.setattr(indents.config, "now_ist", lambda: morning)
    monkeypatch.setattr(indents.config, "customer_cutoff_hours", lambda: {})
    today = morning.date()
    day_after = (today + timedelta(days=2)).isoformat()
    with pytest.raises(indents.SheetError, match="today"):
        indents.submit_new(IndentHeader(**{**H.to_dict(), "delivery_date": day_after}), [HASS], "s@x.com")
    yesterday = (today - timedelta(days=1)).isoformat()
    assert not indents.date_allowed(yesterday) and indents.date_allowed(today.isoformat())
    assert indents.date_allowed(yesterday, keep=yesterday)        # a correction keeps its own date
    assert indents.submit_new(IndentHeader(**{**H.to_dict(), "delivery_date": today.isoformat()}), [HASS], "s@x.com")
    # still open at 3 PM; after 11 PM, today is closed for new indents
    monkeypatch.setattr(indents.config, "now_ist", lambda: morning + timedelta(hours=6))
    assert indents.date_allowed(today.isoformat())
    afternoon = morning + timedelta(hours=14, minutes=30)
    monkeypatch.setattr(indents.config, "now_ist", lambda: afternoon)
    assert not indents.date_allowed(today.isoformat())
    assert indents.date_allowed((today + timedelta(days=1)).isoformat())


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
    # a saved indent cannot be moved to another store (or onto A); A itself can still be edited
    with pytest.raises(indents.SheetError, match="store of a saved indent cannot be changed"):
        indents.submit_update(b, 1, H, [HASS], "s@x.com")
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
    indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 40}),
                                      IndentLine(**{**BLUE.to_dict(), "qty": 0})], "b@x.com")
    indents.cancel(iid, 2, "a@x.com")
    raw = backend.read("Indent_Lines")
    notes = raw.groupby("version")["change_note"].first().to_dict()
    assert notes["1"].startswith("Created by a@x.com on ")
    assert notes["2"].startswith("Edited by b@x.com (other user; created by a@x.com) on ")
    assert "1PC - Hass Avocado Imported: qty 30 → 40" in notes["2"] and "1PC - Blueberry Imported: qty 10 → 0" in notes["2"]
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



def test_apple_variety_from_name():
    m = _masters()
    assert m.variety_from_name("Apple", "2PC - Apple Royal Gala Imported") == "Gala"
    assert m.variety_from_name("Apple", "2PC - Apple Queen Imported") == "Queen"
    assert m.variety_from_name("Apple", "2PC - Apple Snacky") == ""          # user picks
    snacky = IndentLine("Apple", "2PC - Apple Queen Imported", "Gala", "Pcs", 1, 1)
    assert any("must be Queen" in e for e in indents.validate(H, [snacky], m))


def test_indent_numbers_run_on_across_days_and_cities():
    from core.indents import next_indent_id
    old = ["IND-20261114-PTP-0001", "IND-20261114-PTP-0004"]
    assert next_indent_id(old) == "IN-001"
    assert next_indent_id(old + ["IN-001", "IN-002"]) == "IN-003"
    assert next_indent_id(["IN-999"]) == "IN-1000"


def test_qty_zero_only_for_saved_items(backend):
    m = _masters()
    zero = IndentLine(**{**HASS.to_dict(), "qty": 0})
    assert any("greater than 0" in e for e in indents.validate(H, [zero], m))
    assert not [e for e in indents.validate(H, [zero], m, zero_ok={HASS.customer_sku_name}) if "Qty" in e]


def test_po_mismatch_is_uploaded_and_flagged(backend):
    iid = indents.submit_new(H, [HASS, BLUE], "s@x.com")
    v, frozen = indents.freeze(iid, 1, "po.pdf", "s@x.com", po_number="PO-77",
                               po_qty={HASS.customer_sku_name: 30, "Extra Kiwi": 5})
    assert frozen and v == 2
    info = indents.po_info(indents.read_po_freeze(), iid)
    assert info["pos"] == 1 and not info["ended"]
    rows = {r["customer_sku_name"]: r for r in indents.po_vs_indent(
        indents.snapshot(indents.read_lines(fresh=True), iid).lines, info)}
    assert rows[HASS.customer_sku_name]["ok"]
    assert rows[BLUE.customer_sku_name]["po_qty"] is None and not rows[BLUE.customer_sku_name]["ok"]  # never 0
    assert rows["Extra Kiwi"]["diff"] == 5
    po = backend.read("PO_Freeze").iloc[-1]
    assert po["po_number"] == "PO-77" and float(po["po_total_qty"]) == 35


def test_owner_replaces_a_wrong_po(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    indents.freeze(iid, 1, "a.pdf", "o", po_qty={"Avocado Hass Imported - 1 pc": 25})
    lines = indents.snapshot(indents.read_lines(fresh=True), iid).lines
    first = indents.po_vs_indent(lines, indents.po_info(indents.read_po_freeze(), iid))[0]
    assert first["po_qty"] == 25 and not first["ok"]       # customer's name still matched to our item
    v, frozen = indents.freeze(iid, 2, "b.pdf", "o", po_qty={" 1PC - Hass  Avocado Imported": 30}, replace=True)
    info = indents.po_info(indents.read_po_freeze(), iid)
    assert v == 2 and frozen and info["pos"] == 1                       # only the latest PO counts
    assert all(r["ok"] for r in indents.po_vs_indent(lines, info))      # spaces / case ignored


def test_swiggy_many_pos_until_end(backend):
    hdr = IndentHeader(**{**H.to_dict(), "customer": "Swiggy"})
    iid = indents.submit_new(hdr, [HASS, BLUE], "s@x.com")
    assert indents.freeze(iid, 1, "a.pdf", "s@x.com", po_qty={HASS.customer_sku_name: 20}) == (1, False)
    assert indents.freeze(iid, 1, "b.pdf", "s@x.com", po_qty={HASS.customer_sku_name: 10,
                                                             BLUE.customer_sku_name: BLUE.qty}) == (1, False)
    cur = indents.snapshot(indents.read_lines(fresh=True), iid)
    assert cur.status == "Submitted"
    info = indents.po_info(indents.read_po_freeze(), iid)
    assert info["pos"] == 2 and all(r["ok"] for r in indents.po_vs_indent(cur.lines, info))
    v = indents.end_pos(iid, 1, "s@x.com")
    cur = indents.snapshot(indents.read_lines(fresh=True), iid)
    assert cur.status == "Frozen" and cur.version == v == 2
    assert indents.po_info(indents.read_po_freeze(), iid)["ended"]
    assert indents.latest_po()[iid]["_pos"] == 2


def test_lock_then_po(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    v = indents.lock(iid, 1, "s@x.com")
    assert indents.snapshot(indents.read_lines(fresh=True), iid).status == "Locked"
    with pytest.raises(indents.FrozenError):
        indents.submit_update(iid, v, H, [IndentLine(**{**HASS.to_dict(), "qty": 1})], "s@x.com")
    v2, frozen = indents.freeze(iid, v, "po.pdf", "s@x.com", po_qty={HASS.customer_sku_name: 30})
    assert frozen and indents.snapshot(indents.read_lines(fresh=True), iid).status == "Frozen"


def test_zepto_cutoff_same_as_others(backend, monkeypatch):
    day = config.now_ist().date()
    at = lambda h, m=0: datetime.combine(day, datetime.min.time(), tzinfo=config.IST) + timedelta(hours=h, minutes=m)
    assert indents.cutoff_hour("Zepto") == 23 and indents.cutoff_hour("More") == 23
    assert indents.can_edit(day.isoformat(), now=at(22, 59), customer="Zepto")
    assert not indents.can_edit(day.isoformat(), now=at(23), customer="zepto")
    # a per-customer override from the secrets still works
    monkeypatch.setattr(indents.config, "customer_cutoff_hours", lambda: {"zepto": 1})
    assert indents.cutoff_hour("Zepto") == 1 and not indents.can_edit(day.isoformat(), now=at(1), customer="Zepto")

def test_po_correction_allowed_after_cutoff(backend, monkeypatch):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    monkeypatch.setattr(indents, "can_edit", lambda *a, **k: False)
    with pytest.raises(indents.CutoffError):
        indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 31})], "s@x.com")
    v, _ = indents.submit_update(iid, 1, H, [IndentLine(**{**HASS.to_dict(), "qty": 31})], "s@x.com",
                                 po_fix=True)
    assert v == 2


def test_owner_can_delete_until_two_days_after_delivery_even_with_po(backend, monkeypatch):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    jid = indents.submit_new(IndentHeader(**{**H.to_dict(), "store": "Store Z"}), [HASS], "s@x.com")
    indents.freeze(iid, 1, "po.pdf", "s@x.com")
    with pytest.raises(indents.FrozenError):
        indents.cancel(iid, 2, "s@x.com")                       # sales: frozen, not allowed
    monkeypatch.setattr(indents, "can_edit", lambda *a, **k: False)
    assert indents.cancel(iid, 2, "o@x.com", owner=True) == 3   # owner: after cutoff, with a PO
    monkeypatch.setattr(indents, "owner_can_delete", lambda d: False)   # older than T-2
    with pytest.raises(indents.CutoffError):
        indents.cancel(jid, 1, "o@x.com", owner=True)


def test_owner_delete_window_is_two_days():
    today = config.now_ist().date()
    assert indents.owner_can_delete((today - timedelta(days=2)).isoformat())
    assert not indents.owner_can_delete((today - timedelta(days=3)).isoformat())
    assert indents.owner_can_delete((today + timedelta(days=1)).isoformat())


def test_backup_and_clear_starts_fresh(backend):
    indents.submit_new(H, [HASS], "s@x.com")
    done = indents.backup_and_clear("o@x.com")
    assert done[INDENT_LINES] == 1 and indents.read_lines(fresh=True).empty
    assert any(t.startswith("Backup_") and t.endswith(INDENT_LINES) for t in backend.list_tabs())
    assert indents.submit_new(H, [HASS], "s@x.com") == "IN-001"


def test_owner_moves_delivery_date_past_cutoff(backend):
    iid = indents.submit_new(H, [HASS], "s@x.com")
    yesterday = (config.now_ist().date() - timedelta(days=1)).isoformat()
    v = indents.move_date(iid, 1, yesterday, "owner@x.com")
    cur = indents.snapshot(indents.read_lines(fresh=True), iid)
    assert v == 2 and cur.header.delivery_date == yesterday and cur.status == "Submitted"
