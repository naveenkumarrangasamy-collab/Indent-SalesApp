import pandas as pd

from core import processed as pr


def test_matches_g_sheet_kiwi_row():
    v = {"mt_packs": 60, "left_box": 1, "left_pcs": 12, "gt_pcs": 28, "dump_pcs": 17}
    r = pr.compute(5.6, 59, 4, "2PC", v)
    assert round(r["taken_kg"], 2) == 22.40 and round(r["left_kg_total"], 2) == 6.74
    assert round(r["used_kg"], 2) == 15.66 and round(r["mt_kg"], 2) == 11.39
    assert round(r["gt_kg_total"], 2) == 2.66 and round(r["dump_kg_total"], 2) == 1.61
    assert abs(r["lotting"]) < 0.01 and round(r["efficiency"] * 100) == 73


def test_kg_pack_mandarin_row():
    v = {"mt_packs": 6, "mt_loose_kg": 0.4, "gt_box": 2, "gt_kg": 3, "dump_kg": 0.6}
    r = pr.compute(9, 80, 9, "9Kg", v)
    assert round(r["mt_kg"], 2) == 54.4 and round(r["gt_kg_total"], 2) == 21


def test_pack_labels_and_needs():
    assert pr.pack_label("2 Pcs") == "2PC" and pr.pack_label("1 Kg") == "1Kg"
    assert pr.pack_label("250 gm") == "0.250 kg"
    lines = pd.DataFrame([
        {"delivery_date": "2026-11-25", "city": "B", "parent_sku": "Avocado", "lot_size": "1 Pcs", "qty": 300},
        {"delivery_date": "2026-11-25", "city": "B", "parent_sku": "Avocado", "lot_size": "1 Pcs", "qty": 420},
        {"delivery_date": "2026-11-25", "city": "B", "parent_sku": "Apple", "lot_size": "1 Kg", "qty": 5}])
    assert pr.packs_for(lines, "Avocado", "2026-11-25", "B") == {"1PC": 720}


def test_row_and_latest():
    lot = {"entry_id": "L1", "parent_sku": "Avocado", "table_no": "3", "size": "18C", "box_kg": 4,
           "pcs_per_box": 18, "boxes_moved": 50}
    r1 = pr.row(lot, "1PC", {"mt_packs": 700}, "2026-11-25", "B")
    r2 = pr.row(lot, "1PC", {"mt_packs": 710}, "2026-11-25", "B")
    df = pd.DataFrame([r1, r2])
    assert list(pr.latest(df)["mt_packs"]) == [710]
    assert list(pr.view(df)["Efficiency"])[0].endswith("%")


def test_sum_check_and_colour():
    r = {"used_kg": 10.0, "mt_kg": 7.0, "gt_kg_total": 2.0, "dump_kg_total": 1.0}
    assert pr.sum_check(r) == 1.0 and pr.sum_colour(1.0)[1] == "#27500A"
    r2 = dict(r, gt_kg_total=0.0)            # GT box missed -> 80 %, red
    assert round(pr.sum_check(r2), 2) == 0.8 and pr.sum_colour(0.8)[1] == "#791F1F"
    assert pr.sum_colour(0.93)[1] == "#633806" and pr.sum_check({"used_kg": 0}) is None
    assert pr.sum_colour(0.97)[1] == "#27500A" and pr.sum_colour(1.03)[1] == "#791F1F"


def test_blank_boxes_save_as_zero():
    lot = {"entry_id": "L1", "parent_sku": "Apple", "box_kg": "17.5", "pcs_per_box": "120", "boxes_moved": "10"}
    out = pr.row(lot, "1PC", {"mt_packs": 100}, "2026-11-26", "PTP Bangalore")
    assert out["gt_box"] == 0 and out["dump_kg"] == 0 and out["mt_packs"] == 100


def test_group_lots_clubs_same_spec_and_sums():
    raw = pd.DataFrame([
        {"entry_id": "a", "parent_sku": "Apple", "variety": "Gala", "size": "90C", "origin": "Turkey",
         "table_no": "2", "box_kg": "17.5", "pcs_per_box": "90", "boxes_moved": "110", "stock_type": "Unused Vendor Lot"},
        {"entry_id": "b", "parent_sku": "Apple", "variety": "Gala", "size": "90C", "origin": "Turkey",
         "table_no": "4", "box_kg": "17.5", "pcs_per_box": "90", "boxes_moved": "10", "stock_type": "Unused Vendor Lot"},
        {"entry_id": "c", "parent_sku": "Avocado", "variety": "Hass", "size": "20C", "origin": "Kenya",
         "table_no": "5", "box_kg": "4", "pcs_per_box": "20", "boxes_moved": "15", "stock_type": "Returns"}])
    g = pr.group_lots(raw)
    assert set(g) == {"a+b", "c"}
    ab = g["a+b"]
    assert ab["boxes_moved"] == 120 and ab["table_no"] == "2 + 4" and round(ab["taken_kg"]) == 2100
    assert ab["taken_pcs"] == 120 * 90
    assert pr.member_map(g)["b"] == "a+b"
    # 1Kg packs: D1 = 2,058 one-kg packs -> MT 2,058 kg; dump 21 kg -> 2,079 of 2,100 = 99 %
    t = pr.group_total([("1Kg", {"mt_packs": 1500}), ("1Kg", {"mt_packs": 558, "dump_kg": 21})], ab)
    assert round(t["out_kg"]) == 2079 and pr.sum_colour(t["sum"])[1] == "#27500A"
