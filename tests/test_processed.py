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
