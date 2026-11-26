import pandas as pd

from core import processed2 as p2

RAW = pd.DataFrame([
    {"entry_id": "a", "production_date": "2026-11-26", "city": "B", "parent_sku": "Apple", "variety": "Gala",
     "size": "100C", "origin": "Italy", "brand": "", "table_no": "1", "box_kg": "18", "pcs_per_box": "100",
     "boxes_moved": "30", "stock_type": "Unused Vendor Lot"},
    {"entry_id": "b", "production_date": "2026-11-26", "city": "B", "parent_sku": "Apple", "variety": "Gala",
     "size": "100C", "origin": "Italy", "brand": "", "table_no": "2", "box_kg": "18", "pcs_per_box": "100",
     "boxes_moved": "40", "stock_type": "Unused Vendor Lot"}])
LINES = [{"pack": "1PC", "mt_packs": 1500}, {"pack": "2PC", "mt_packs": 600}, {"pack": "1Kg", "mt_packs": 30}]


def test_tables_are_separate_items():
    it = p2.items(RAW)
    assert [v["table_no"] for v in it.values()] == ["1", "2"]
    assert list(it.values())[0]["taken_kg"] == 540 and list(it.values())[1]["boxes_moved"] == 40


def test_total_and_states():
    it = list(p2.items(RAW).values())[0]
    t = p2.total(it, LINES, {})
    assert round(t["mt_kg"]) == 516 and [round(x) for x in t["mt_per_line"]] == [270, 216, 30]
    assert p2.state_of(t) == "low"                                   # 96 %
    ok = p2.total(it, LINES, {"gt_kg": 12, "dump_kg": 8})
    assert round(ok["out_kg"]) == 536 and p2.state_of(ok) == "ok" and round(ok["efficiency"] * 100) == 96
    assert p2.state_of(p2.total(it, LINES, {"gt_kg": 40, "dump_kg": 8})) == "over"   # 104 %
    back = p2.total(it, [{"pack": "1PC", "mt_packs": 1400}, {"pack": "2PC", "mt_packs": 600},
                         {"pack": "1Kg", "mt_packs": 20}], {"left_box": 2, "gt_kg": 10, "dump_kg": 6})
    assert round(back["used_kg"]) == 504 and round(back["sum"] * 100) == 100
    assert p2.state_of(p2.total(it, [], {})) == "empty"


def test_snapshot_latest_and_tracking_rows():
    it = list(p2.items(RAW).values())[0]
    draft = p2.snapshot(it, LINES[:1], {}, "", "draft", "2026-11-26", "B", "me")
    final = p2.snapshot(it, LINES, {"gt_kg": 12, "dump_kg": 8}, "ok", "submitted", "2026-11-26", "B", "me")
    saved = pd.DataFrame(draft + final)
    s = p2.latest(saved, "2026-11-26", "B")[f"2026-11-26|B|{it['key']}"]
    assert s["status"] == "submitted" and len(s["lines"]) == 3 and s["tbl"]["gt_kg"] == 12 and s["comment"] == "ok"
    rows = p2.track_rows(RAW, saved)
    t1 = [r for r in rows if r[2] == "Table 1"]
    assert [r[13] for r in t1] == ["1PC", "2PC", "1Kg", "Table total"]
    eff = p2.TRACK_HEAD.index("Category Efficiency% (K / J)")
    assert {r[eff] for r in t1} == {"96%"} and t1[-1][18] == 12 and t1[-1][19] == 8 and t1[0][11] == 3000
    assert p2.line_pcs('2PC', 50) == 100 and p2.line_pcs('1Kg', 5) == 0
    assert [r for r in rows if r[2] == "Table 2"][0][-2] == "Not started"
