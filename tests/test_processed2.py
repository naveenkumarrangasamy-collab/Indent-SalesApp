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
    lot = p2.TRACK_HEAD.index("Cux Lot")
    assert [r[lot] for r in t1] == ["1PC", "2PC", "1Kg", "Table total"] and p2.TRACK_HEAD[3] == "Executive"
    eff = p2.TRACK_HEAD.index("Category Efficiency% (K / J)")
    assert {r[eff] for r in t1} == {"96%"} and t1[-1][18] == 12 and t1[-1][19] == 8
    assert p2.line_pcs('2PC', 50) == 100 and p2.line_pcs('1Kg', 5) == 0
    assert [r for r in rows if r[2] == "Table 2"][0][-2] == "Not started"


def test_executive_items_lot_units_and_day_close():
    raw = RAW.assign(executive=["Ravi", ""])
    it = p2.items(raw)
    assert [(v["executive"], v["table_no"]) for v in it.values()] == [("", "2"), ("Ravi", "1")]
    assert [k.split("|")[0] for k in it] == ["2", "ravi"]                 # no name = the old key
    assert p2.lot_unit("2PC") == "PC" and p2.lot_unit("1Kg") == "Kg" and p2.lot_unit("") == ""
    assert p2.clean_line({"pack": "2PC", "mt_packs": 5, "mt_loose_kg": 3})["mt_loose_kg"] is None
    assert p2.clean_line({"pack": "1Kg", "mt_packs": 30, "mt_loose_kg": 2}) == {"pack": "1Kg", "mt_packs": None,
                                                                              "mt_loose_kg": 32.0}
    saved = pd.DataFrame(p2.close_rows("2026-11-26", "B", "me"))
    assert p2.day_state(saved, "2026-11-26", "B")["by"] == "me" and p2.day_state(saved, "2026-11-27", "B") is None
    again = pd.concat([saved, pd.DataFrame(p2.close_rows("2026-11-26", "B", "boss", "open"))], ignore_index=True)
    assert p2.day_state(again, "2026-11-26", "B") is None and p2.latest(again, "2026-11-26", "B") == {}


def test_category_efficiency_clubs_counts_per_variety_country_brand():
    raw = pd.DataFrame([
        {"entry_id": "a", "production_date": "2026-11-26", "city": "B", "parent_sku": "Apple", "variety": "Gala",
         "size": "100C", "origin": "Poland", "brand": "X", "table_no": "1", "box_kg": "18", "pcs_per_box": "100",
         "boxes_moved": "10", "stock_type": "Unused Vendor Lot"},
        {"entry_id": "b", "production_date": "2026-11-27", "city": "B", "parent_sku": "Apple", "variety": "Gala",
         "size": "110C", "origin": "Poland", "brand": "X", "table_no": "2", "box_kg": "18", "pcs_per_box": "110",
         "boxes_moved": "10", "stock_type": "Unused Vendor Lot"},
        {"entry_id": "c", "production_date": "2026-11-27", "city": "B", "parent_sku": "Apple", "variety": "Gala",
         "size": "100C", "origin": "USA", "brand": "", "table_no": "3", "box_kg": "20", "pcs_per_box": "100",
         "boxes_moved": "5", "stock_type": "Unused Vendor Lot"}])
    it = {d: p2.items(raw[raw["production_date"] == d]) for d in ("2026-11-26", "2026-11-27")}
    a = [v for v in it["2026-11-26"].values()][0]
    b = [v for v in it["2026-11-27"].values() if v["origin"] == "Poland"][0]
    saved = pd.DataFrame(
        p2.snapshot(a, [{"pack": "1Kg", "mt_loose_kg": 160}], {"gt_kg": 15, "dump_kg": 5}, "", "submitted",
                    "2026-11-26", "B", "me")
        + p2.snapshot(b, [{"pack": "1Kg", "mt_loose_kg": 170}], {"gt_kg": 5, "dump_kg": 5}, "", "draft",
                      "2026-11-27", "B", "me"))
    rows, tot = p2.category_rows(raw, saved, None, "B")
    assert [(r["Country"], r["Counts clubbed"]) for r in rows] == [("Poland", "100C, 110C"), ("USA", "100C")]
    pol, usa = rows
    assert pol["Kg used (J)"] == 360 and round(pol["Category Efficiency % (K / J)"] * 100) == 92
    assert round(pol["GT Created % (L / J)"] * 100, 1) == 5.6 and pol["Status"] == "1 submitted · 1 saved, not submitted"
    assert usa["Category Efficiency % (K / J)"] is None and usa["Status"] == "1 not started" and usa["Kg taken"] == 100
    assert tot["saved"] == 1 and round(tot["efficiency"] * 100) == 92
    one, _ = p2.category_rows(raw, saved, {"2026-11-26"}, "B")
    assert len(one) == 1 and one[0]["Counts clubbed"] == "100C"
    assert [p2.eff_band(x) for x in (0.95, 0.9, 0.85, 0.75, 0.6, None)] == ["green", "green", "amber", "yellow", "red", ""]
