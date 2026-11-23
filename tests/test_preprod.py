import pandas as pd

from core import preprod
from core.masters import masters_from_frames
from core.schema import ACCESS, SKU_MAP, STORE_MAP, TABS, VARIETIES
from tests.test_production_calc import BASE, _lines


def _masters(new=None):
    sku = pd.DataFrame([
        ["Bangalore", "Flipkart", "Apple", "4PC - Royal Gala Apple", "New Zealand", "90, 100, 110", "Y", "Gala", "",
         "", "18 Kg"],
        ["Bangalore", "Flipkart", "Apple", "4PC - Royal Gala Apple", "Italy", "100C, 113C", "N", "Gala", "", "", ""],
        ["Bangalore", "Flipkart", "Mandarin", "1Kg - Mandarin Imported", "RSA", "1C, 2C, 65mm", "Y", "", "", "",
         "15"],
    ], columns=TABS[SKU_MAP] + ["Spec-Grade", "Box-Kg"])
    empty = {t: pd.DataFrame(columns=TABS[t]) for t in (STORE_MAP, VARIETIES, ACCESS)}
    frames = {SKU_MAP: sku, **empty}
    if new is not None:
        frames["New"] = pd.DataFrame(new)
    return masters_from_frames(frames)


def test_parse_spec_counts_and_sizes():
    assert preprod.parse_spec("90, 100, 110") == ["90", "100", "110"]
    assert preprod.parse_spec("22C, 24C | 22c") == ["22", "24"]
    assert preprod.parse_spec("1C, 2C, 65mm") == ["1C", "2C", "65mm"]
    assert preprod.spec_label("90") == "90C" and preprod.spec_label("65mm") == "65mm"


def test_need_unit_from_pack():
    assert preprod.need_unit("4PC - Royal Gala Apple", "Pcs") == ("pcs", 4.0)
    assert preprod.need_unit("1Kg - Mandarin Imported", "Kg") == ("kg", 1.0)
    assert preprod.need_unit("200gm - Blueberry", "Pack")[0] == "packs"


def test_demand_clubs_stores_of_a_customer():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Swiggy", store="Swiggy WH1", parent_sku="Apple",
             customer_sku_name="4PC - Royal Gala Apple", qty="10"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="Swiggy WH2", parent_sku="Apple",
             customer_sku_name="4pc -  royal gala apple", qty="5"),
        dict(BASE, indent_id="C", version="1", customer="Swiggy", store="Swiggy Cold Room", parent_sku="Apple",
             customer_sku_name="4PC - Royal Gala Apple", qty="2"),
    ])
    d = preprod.demand(df)
    assert list(d["group"]) == ["Swiggy", "Swiggy Cold Room"]
    assert list(d["need"]) == [60.0, 8.0] and d.iloc[0]["indents"] == "A, B"


def test_countries_from_mapping_whole_with_box_kg():
    m = _masters()
    o = preprod.country_options(m, None, "Bangalore", "Flipkart", "4PC - Royal Gala Apple", "Apple")
    assert list(o) == ["New Zealand", "Italy"]
    assert o["New Zealand"]["spec"] == ["90", "100", "110"] and o["New Zealand"]["box_kg"] == 18
    assert o["Italy"]["spec"] == ["100", "113"]
    assert preprod.suggestion(480, "pcs", o["New Zealand"]) == "90C 6 · 100C 5 · 110C 5 Box"


def test_batching_master_wins_over_new_tab():
    new = [{"City": "", "Customer": "Flipkart", "Parent SKU": "Apple", "Customer SKU Name": "4PC - Royal Gala Apple",
            "Variety": "Gala", "Repacking": "Punnet", "Spec-Size": "100, 110", "Spec-Origin": "Chile"}]
    m = _masters(new)
    o = preprod.country_options(m, None, "Bangalore", "Flipkart", "4PC - Royal Gala Apple", "Apple")
    assert list(o) == ["Chile"] and o["Chile"]["box_kg"] == 18     # kg from Mapping Whole as a fallback
    bm = pd.DataFrame([{"City": "Bangalore", "Customer": "Flipkart", "Customer SKU Name": "4PC - Royal Gala Apple",
                        "Parent SKU": "Apple", "Country": "South Africa", "Spec": "120, 135", "Unit": "Box",
                        "Box Kg": "12.5"}])
    o = preprod.country_options(m, bm, "Bangalore", "Flipkart", "4PC - Royal Gala Apple", "Apple")
    assert list(o) == ["South Africa"] and o["South Africa"]["box_kg"] == 12.5


def test_rounds_add_up_and_freeze_last_row_wins():
    actual = pd.DataFrame([
        dict(round_id="r1", saved_at="2026-11-22T12:10:00", saved_by="ravi", delivery_date="2026-11-22",
             city="Bangalore", group="Flipkart", customer_sku_name="4PC - Royal Gala Apple", country="New Zealand",
             spec="90", boxes="2", reason="First take-out"),
        dict(round_id="r1", saved_at="2026-11-22T12:10:00", saved_by="ravi", delivery_date="2026-11-22",
             city="Bangalore", group="Flipkart", customer_sku_name="4PC - Royal Gala Apple", country="New Zealand",
             spec="100", boxes="3", reason="First take-out"),
        dict(round_id="r2", saved_at="2026-11-22T12:55:00", saved_by="ravi", delivery_date="2026-11-22",
             city="Bangalore", group="Flipkart", customer_sku_name="4PC - Royal Gala Apple", country="New Zealand",
             spec="90", boxes="1", reason="More for grading loss"),
        dict(round_id="r3", saved_at="2026-11-22T12:55:00", saved_by="ravi", delivery_date="2026-11-23",
             city="Bangalore", group="Flipkart", customer_sku_name="4PC - Royal Gala Apple", country="New Zealand",
             spec="90", boxes="9", reason="First take-out"),
    ])
    t = preprod.taken(actual, "2026-11-22", "Bangalore", "Flipkart")
    assert t["4pc - royal gala apple"] == {"country": "New Zealand", "boxes": {"90": 3, "100": 3}}
    h = preprod.rounds(actual, "2026-11-22", "Bangalore", "Flipkart")
    assert list(h["Round"]) == [1, 2] and h.iloc[1]["Reason"] == "More for grading loss"
    assert h.iloc[0]["Boxes taken out"] == "4PC - Royal Gala Apple: 90C 2, 100C 3"
    fr = pd.DataFrame([dict(delivery_date="2026-11-22", city="Bangalore", group="Flipkart", action="freeze",
                            at="t1", by="a"),
                       dict(delivery_date="2026-11-22", city="Bangalore", group="Flipkart", action="unfreeze",
                            at="t2", by="b")])
    assert preprod.freeze_state(fr, "2026-11-22", "Bangalore", "Flipkart") == (False, "t2", "b")
    assert preprod.freeze_state(fr.iloc[:1], "2026-11-22", "Bangalore", "Flipkart")[0] is True
    assert preprod.freeze_state(None, "2026-11-22", "Bangalore", "Flipkart") == (False, "", "")


def test_statuses_and_ten_percent_limit():
    assert preprod.max_allowed(480, 10) == 528
    assert preprod.batch_status(480, 520, True, 10) == "Covered"
    assert preprod.batch_status(480, 529, True, 10) == "Over limit"
    assert preprod.batch_status(480, 400, True, 10) == "Short"
    assert preprod.batch_status(480, 0, False, 10) == "Pending"
    assert preprod.actual_status(480, 570, 6) == "Enough"
    assert preprod.actual_status(480, 300, 3) == "Not enough"
    assert preprod.actual_status(480, None, 0) == "Not started"
    assert preprod.per_box("90", "pcs", 18) == 90 and preprod.per_box("2C", "pcs", 18) is None
    assert preprod.per_box("2C", "kg", 15) == 15


def test_used_saved_last_value_wins():
    plan = pd.DataFrame([
        dict(delivery_date="2026-11-22", city="Bangalore", group="Flipkart", customer_sku_name="X", spec="90",
             used="250"),
        dict(delivery_date="2026-11-22", city="Bangalore", group="Flipkart", customer_sku_name="X", spec="90",
             used="240"),
    ])
    assert preprod.used_saved(plan, "2026-11-22", "Bangalore", "Flipkart") == {("x", "90"): 240}


class _FakeBackend:
    def __init__(self):
        self.rows = {}

    def append_dicts(self, tab, dicts):
        self.rows.setdefault(tab, []).extend(dicts)


def test_save_round_skips_zero_boxes():
    b = _FakeBackend()
    n = preprod.save_round(b, "2026-11-22", "Bangalore", "Flipkart",
                           [dict(customer_sku_name="X", country="NZ", spec="90", boxes=2),
                            dict(customer_sku_name="X", country="NZ", spec="100", boxes=0)], "First take-out", "me")
    assert n == 1 and b.rows["Preprod_Actual"][0]["boxes"] == 2
    preprod.set_frozen(b, "2026-11-22", "Bangalore", "Flipkart", True, "me")
    assert b.rows["Preprod_Freeze"][0]["action"] == "freeze"


def test_gt_dump_and_back_to_box():
    from core import preprod as pp
    import pandas as pd
    assert pp.back_to_box(10, 5, 2) == 3
    assert pp.back_to_box(10, None, None) == 10
    assert pp.back_to_box(None, 1, 1) is None
    assert pp.back_to_box(6, 0, 9) == -3            # page blocks the save
    plan = pd.DataFrame([
        {"delivery_date": "d", "city": "c", "group": "g", "customer_sku_name": "A", "spec": "100", "used": "90",
         "gt_qty": "", "dump": ""},
        {"delivery_date": "d", "city": "c", "group": "g", "customer_sku_name": "A", "spec": pp.ITEM, "used": "",
         "gt_qty": "6", "dump": ""}])
    assert pp.item_saved(plan, "d", "c", "g") == {"a": (6.0, None, None, None)}
    assert pp.back_to_box(10, 2, 1, 3) == 4
    assert pp.used_saved(plan, "d", "c", "g") == {("a", "100"): 90.0}
