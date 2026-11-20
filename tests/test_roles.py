"""21 Nov: Warehouse / Sales / Owner / Creator; Owner cities and Access page."""
import pandas as pd

from core import auth
from core.schema import ROLES, role_name


def _acc(rows):
    base = {"Name": "", "Status": "active", "City": "", "Admin_Page": ""}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_role_names_and_order():
    assert [role_name(r) for r in ROLES] == ["Warehouse", "Sales", "Owner", "Creator"]


def test_owner_cities_and_access_page():
    acc = _acc([{"Email": "c@x.com", "Role": "owner_full"},
                {"Email": "o@x.com", "Role": "owner", "City": "PTP Bangalore", "Admin_Page": "yes"},
                {"Email": "p@x.com", "Role": "owner"}])
    c, o, p = (auth.resolve_user(acc, e) for e in ("c@x.com", "o@x.com", "p@x.com"))
    assert c.opens_access and c.sees_all_cities
    assert o.opens_access and not o.sees_all_cities and o.in_my_cities("PTP Bangalore")
    assert not p.opens_access and p.sees_all_cities          # default No; empty city = all cities


def test_owner_sees_only_his_city_indents():
    from core import indents
    acc = _acc([{"Email": "o@x.com", "Role": "owner", "City": "PTP Bangalore"}])
    o = auth.resolve_user(acc, "o@x.com")
    summ = pd.DataFrame({"indent_id": ["IN-1", "IN-2"], "city": ["PTP Bangalore", "PTP Hyderabad"],
                         "store": ["a", "b"], "created_by": ["x", "y"]})
    assert list(indents.visible_to(summ, o)["indent_id"]) == ["IN-1"]


def test_owner_manages_only_sales_warehouse_in_his_cities():
    from pages_src import access
    acc = _acc([{"Email": "c@x.com", "Role": "owner_full"},
                {"Email": "o@x.com", "Role": "owner", "City": "PTP Bangalore", "Admin_Page": "yes"},
                {"Email": "o2@x.com", "Role": "owner", "City": "PTP Bangalore"},
                {"Email": "s1@x.com", "Role": "sales", "City": "PTP Bangalore"},
                {"Email": "s2@x.com", "Role": "sales", "City": "PTP Hyderabad"},
                {"Email": "w@x.com", "Role": "warehouse", "City": "PTP Bangalore, PTP Hyderabad"}])
    o = auth.resolve_user(acc, "o@x.com")
    seen = set(access._manageable(o, acc)["Email"])
    assert seen == {"o@x.com", "s1@x.com", "w@x.com"}
    assert access._roles_for(o, acc) == ["warehouse", "sales"]
    c = auth.resolve_user(acc, "c@x.com")
    assert access._roles_for(c, acc) == ROLES and len(access._manageable(c, acc)) == 6


def test_variety_from_the_name_wins():
    from core.masters import name_variety
    v = ["Gala", "Envy", "Granny Smith", "Queen", "RD"]
    assert name_variety(v, "2PC - Apple Green Imported (Granny Smith)") == "Granny Smith"
    assert name_variety(v, "1Box - Green apple") == "Granny Smith"
    assert name_variety(v, "2PC - Apple Queen Imported") == "Queen"
    assert name_variety(v, "2PC - Bloom Apple Royal Gala Imported") == "Gala"
    assert name_variety(v, "1Kg - Nectr gala apple Large - 350-450g") == "Gala"
    assert name_variety(v, "1Box - Apple Envy") == "Envy"
    assert name_variety(v, "2PC - Snacky Apple") == ""


def test_variety_fix_plan():
    from core import variety_fix
    v = ["Gala", "Granny Smith", "Queen"]
    new = [["City", "Customer", "Parent SKU", "Customer SKU Name", "variety"],
           ["B", "Zepto", "Apple", "2PC - Apple Queen Imported", "Gala"],
           ["B", "Zepto", "Apple", "2PC - Apple Green Imported (Granny Smith)", "Granny Smith"],
           ["B", "Zepto", "Apple", "2PC - Snacky Apple", ""],
           ["B", "Zepto", "Kiwi", "2PC - Kiwi Green", "Kiwi"]]
    acc = [["City", "Customer", "Parent SKU", "Classification", "Customer SKU Name"],
           ["B", "Namdhari", "Apple", "Gala", "1Box - Green apple"]]
    rows = variety_fix.plan({"New": new, "All Cux City": acc}, v)
    assert [(r["Tab"], r["Row"], r["Change to"]) for r in rows] == [("New", 2, "Queen"),
                                                                  ("All Cux City", 2, "Granny Smith")]
    assert rows[1]["_col"] == 3


def test_last_order_of_the_store():
    from core import indents
    df = pd.DataFrame([
        # IN-1 v1/v2 for 19 Nov, IN-2 for 20 Nov (the last one), IN-3 another store, IN-4 tomorrow
        {"indent_id": "IN-1", "version": 1, "status": "Submitted", "delivery_date": "2026-11-19", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Kiwi", "customer_sku_name": "Old", "variety": "",
         "lot": "Pcs", "qty": 5, "_row": 2},
        {"indent_id": "IN-2", "version": 1, "status": "Submitted", "delivery_date": "2026-11-20", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Kiwi", "customer_sku_name": "1Pack - Kiwi Sungold",
         "variety": "", "lot": "Pack", "qty": 39, "_row": 3},
        {"indent_id": "IN-2", "version": 2, "status": "Submitted", "delivery_date": "2026-11-20", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Kiwi", "customer_sku_name": "1Pack - Kiwi Sungold",
         "variety": "", "lot": "Pack", "qty": 40, "_row": 4},
        {"indent_id": "IN-2", "version": 2, "status": "Submitted", "delivery_date": "2026-11-20", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Apple", "customer_sku_name": "2PC - Apple Queen Imported",
         "variety": "Gala", "lot": "Pcs", "qty": 10, "_row": 5},
        {"indent_id": "IN-2", "version": 2, "status": "Submitted", "delivery_date": "2026-11-20", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Kiwi", "customer_sku_name": "Dropped", "variety": "",
         "lot": "Pcs", "qty": 0, "_row": 6},
        {"indent_id": "IN-3", "version": 1, "status": "Submitted", "delivery_date": "2026-11-20", "city": "B",
         "customer": "Zepto", "store": "T", "parent_sku": "Kiwi", "customer_sku_name": "Other", "variety": "",
         "lot": "Pcs", "qty": 3, "_row": 7},
        {"indent_id": "IN-4", "version": 1, "status": "Submitted", "delivery_date": "2026-11-22", "city": "B",
         "customer": "Zepto", "store": "S", "parent_sku": "Kiwi", "customer_sku_name": "Future", "variety": "",
         "lot": "Pcs", "qty": 3, "_row": 8},
    ])
    got = indents.last_order(df, "B", "zepto", "S", "2026-11-21")
    assert [g["customer_sku_name"] for g in got] == ["1Pack - Kiwi Sungold", "2PC - Apple Queen Imported"]
    assert indents.last_order(df, "B", "Zepto", "X", "2026-11-21") == []
