import pandas as pd

from core import regrade as rg


def _grading(rows):
    return pd.DataFrame(rows)


def test_days():
    assert rg.next_day("2026-11-22") == "2026-11-23"
    assert rg.prev_day("2026-12-01") == "2026-11-30"


def test_grade_status():
    assert rg.grade_status(30, None, None, None) == (rg.NOT_GRADED, 30)
    assert rg.grade_status(30, 18, 9, 3) == (rg.GRADED, 0.0)
    assert rg.grade_status(30, 18, None, None) == (rg.PART, 12)
    assert rg.grade_status(30, 20, 20, 0)[0] == "Over"


def test_pool_from_grading_and_batching_mt():
    grading = _grading([
        {"return_date": "2026-11-22", "indent_id": "IN-043", "city": "PTP Bangalore", "customer_sku_name": "2PC - Kiwi",
         "parent_sku": "Kiwi", "variety": "", "unit": "pcs", "spec": "27", "mt": "10"},
        {"return_date": "2026-11-22", "indent_id": "IN-043", "city": "PTP Bangalore", "customer_sku_name": "2PC - Kiwi",
         "parent_sku": "Kiwi", "variety": "", "unit": "pcs", "spec": "27", "mt": "18"},   # last row wins
        {"return_date": "2026-11-21", "indent_id": "IN-040", "city": "PTP Bangalore", "customer_sku_name": "2PC - Kiwi",
         "parent_sku": "Kiwi", "variety": "", "unit": "pcs", "spec": "27", "mt": "50"},   # too old: gone to GT
    ])
    plan = pd.DataFrame([
        {"delivery_date": "2026-11-22", "city": "PTP Bangalore", "group": "Swiggy", "customer_sku_name": "1Pc - Kiwi",
         "spec": "_item", "mt_grade": "8", "parent_sku": "Kiwi", "variety": "", "unit": "pcs"},
        {"delivery_date": "2026-11-22", "city": "PTP Bangalore", "group": "Swiggy", "customer_sku_name": "1Pc - Kiwi",
         "spec": "27", "used": "100"},
    ])
    p = rg.pool(grading, plan, "2026-11-23")
    key = rg.pool_key("PTP Bangalore", "Kiwi", "", "pcs")
    assert p[key]["qty"] == 26
    assert "18 returns 27" in rg.pool_text(p, key) and "8 batching MT grade" in rg.pool_text(p, key)
    assert rg.pool(grading, plan, "2026-11-24") == {}


def test_variety_only_for_apple():
    assert rg.pool_key("C", "Apple", "Gala", "pcs") != rg.pool_key("C", "Apple", "Fuji", "pcs")
    assert rg.pool_key("C", "Kiwi", "Green", "pcs") == rg.pool_key("C", "Kiwi", "Gold", "pcs")
    assert rg.pool_key("C", "Mandarin", "", "kg") != rg.pool_key("C", "Mandarin", "", "pcs")


def test_available_excludes_own_use():
    key = rg.pool_key("C", "Kiwi", "", "pcs")
    pool = {key: {"qty": 26.0, "parts": {}}}
    use = pd.DataFrame([
        {"use_date": "d", "city": "C", "group": "Swiggy", "customer_sku_name": "2PC - Kiwi", "parent_sku": "Kiwi",
         "variety": "", "unit": "pcs", "qty": "10"},
        {"use_date": "d", "city": "C", "group": "Zepto", "customer_sku_name": "1Pc - Kiwi", "parent_sku": "Kiwi",
         "variety": "", "unit": "pcs", "qty": "6"},
    ])
    u = rg.uses(use, "d")
    assert rg.available(pool, u, key, ("c", "swiggy", "2pc - kiwi")) == 20
    assert rg.available(pool, u, key, ("c", "flipkart", "x")) == 10
    assert rg.used_for(u, "C", "Swiggy") == {"2pc - kiwi": 10.0}


def test_grading_saved_last_row():
    g = _grading([{"return_date": "d", "indent_id": "IN-1", "customer_sku_name": "A", "spec": "", "mt": "2",
                   "gt": "", "dump": "1"},
                  {"return_date": "d", "indent_id": "IN-1", "customer_sku_name": "A", "spec": "90", "mt": "3",
                   "gt": "1", "dump": ""}])
    assert rg.grading_saved(g, "d") == {("IN-1", "a"): {"spec": "90", "mt": 3.0, "gt": 1.0, "dump": None}}
