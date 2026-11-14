import pandas as pd

from core.masters import masters_from_frames
from core.production_calc import NO_ORIGIN, aggregate, filter_lines
from core.schema import ACCESS, SKU_MAP, STORE_MAP, TABS, VARIETIES
from core import indents


def _masters():
    sku = pd.DataFrame([
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Tanzania", "20C, 22C", "Y", "", ""],
        ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Kenya", "20C, 22C", "N", "", ""],
        ["Bangalore", "Swiggy", "Avocado", "1PC - Nectar Avocado", "Tanzania", "20C, 22C", "Y", "", ""],
        ["Bangalore", "Zepto", "Kiwi", "2PC - Green Kiwi", "", "", "", "", ""],
        ["Bangalore", "Zepto", "Apple", "2PC - Apple Queen Imported", "", "", "Y", "Queen", ""],
        ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "China", "60", "", "", ""],
        ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "RSA", "2C", "", "", ""],
    ], columns=TABS[SKU_MAP])
    empty = {t: pd.DataFrame(columns=TABS[t]) for t in (STORE_MAP, VARIETIES, ACCESS)}
    return masters_from_frames({SKU_MAP: sku, **empty})


def _lines(rows):
    cols = TABS["Indent_Lines"]
    out = []
    for i, r in enumerate(rows):
        d = {c: "" for c in cols}
        d.update(r)
        d["_row"] = i + 2
        out.append(d)
    return indents.prepare(pd.DataFrame(out, columns=cols + ["_row"]))


BASE = dict(status="Submitted", delivery_date="2026-11-15", city="Bangalore", lot="Pcs", price="100")


def test_aggregate_groups_by_parent_spec_lot():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="12"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="0", lot="Box"),
    ])
    agg = aggregate(df, _masters(), with_spec=True)
    pcs = agg[(agg["Lot"] == "Pcs")].iloc[0]
    assert pcs["Origin"] == "Tanzania" and pcs["Spec-Size"] == "20C, 22C"
    assert pcs["Total Qty"] == 42
    assert pcs["Indents"] == 2
    assert pcs["Customer SKU Names"] == "1PC - Hass Avocado Imported, 1PC - Nectar Avocado"
    assert set(agg["Lot"]) == {"Pcs", "Box"}


def test_single_row_without_active_and_missing_active():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Kiwi",
             customer_sku_name="2PC - Green Kiwi", qty="5"),
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Mandarin",
             customer_sku_name="3PC - Baby Orange Imported", qty="7"),
    ])
    agg = aggregate(df, _masters(), with_spec=True).set_index("Parent SKU")
    assert agg.loc["Kiwi", "Origin"] == NO_ORIGIN  # single row, no origin text
    assert agg.loc["Mandarin", "Origin"] == NO_ORIGIN  # two origins, none Active


def test_variety_splits_groups():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Apple", variety="Queen",
             customer_sku_name="2PC - Apple Queen Imported", qty="5"),
    ])
    agg = aggregate(df, _masters())
    assert agg.iloc[0]["Variety"] == "Queen"


def test_only_current_version_counts_and_filters():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
        dict(BASE, indent_id="A", version="2", customer="Zepto", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="40"),
        dict(BASE, indent_id="C", version="1", customer="Zepto", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="1", delivery_date="2026-11-16"),
    ])
    cur = indents.current_rows(df)
    lines = filter_lines(cur, delivery_date="2026-11-15", city="bangalore", allowed_ids=None)
    assert aggregate(lines, _masters())["Total Qty"].tolist() == [40]
    assert filter_lines(cur, delivery_date="2026-11-15", city=None, allowed_ids={"C"}).empty


def test_empty():
    assert aggregate(_lines([]), _masters()).empty



def test_without_spec_groups_by_parent_variety_lot():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Mandarin",
             customer_sku_name="3PC - Baby Orange Imported", qty="7"),
        dict(BASE, indent_id="B", version="1", customer="Zepto", parent_sku="Mandarin",
             customer_sku_name="3PC - Baby Orange Imported", qty="3"),
    ])
    agg = aggregate(df, _masters(), with_spec=False)
    assert "Origin" not in agg.columns and agg.iloc[0]["Total Qty"] == 10


def test_city_sku_report_and_dates():
    from core.production_calc import city_sku_report, default_date, delivery_dates
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="2PC - Mini Avocado Imported", qty="30"),
        dict(BASE, indent_id="B", version="1", customer="Zepto", store="S2", parent_sku="Avocado",
             customer_sku_name="2PC - Mini Avocado Imported", qty="12", delivery_date="2026-11-16"),
        dict(BASE, indent_id="B", version="1", customer="Zepto", store="S2", parent_sku="Litchi",
             customer_sku_name="200gm - Litchi Imported (Longan)", qty="5", lot="gms",
             delivery_date="2026-11-16"),
    ])
    rep = city_sku_report(df)
    row = rep[rep["Customer SKU Name"] == "2PC - Mini Avocado Imported"].iloc[0]
    assert (row["City"], row["Lot"], row["Lot Size"], row["Qty"], row["Stores"]) == ("Bangalore", "Pcs", "2 Pcs", 42, 2)
    assert delivery_dates(df) == ["2026-11-15", "2026-11-16"]
    assert default_date(["2026-11-15", "2026-11-16"], "2026-11-16") == "2026-11-16"
    assert default_date(["2026-11-10"], "2026-11-16") == "2026-11-10"
    agg = aggregate(df, _masters(), with_spec=False)
    assert "Lot Size" in agg.columns



def test_spec_size_column_without_origin():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
        dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Kiwi",
             customer_sku_name="2PC - Green Kiwi", qty="5"),
    ])
    agg = aggregate(df, _masters()).set_index("Parent SKU")
    assert "Origin" not in agg.columns
    assert agg.loc["Avocado", "Spec-Size"] == "20C, 22C"   # Active (Tanzania) row
    assert agg.loc["Kiwi", "Spec-Size"] == ""              # not in Mapping Whole
    m = _masters()
    assert m.spec_size("Bangalore", "Zepto", "3PC - Baby Orange Imported") == ""  # 2 origins, sizes differ, none active


def test_pdf_report():
    from core.pdf_report import table_pdf
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", parent_sku="Avocado",
                      customer_sku_name="1PC - Hass Avocado Imported", qty="30")])
    pdf = table_pdf("Production sheet", ["Delivery: Mon, 16 Nov 2026 → test ₹"], aggregate(df, _masters()))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
    assert table_pdf("Empty", [], aggregate(_lines([]), _masters()))[:5] == b"%PDF-"
