import pandas as pd

from core.masters import masters_from_frames
from core.production_calc import batching, production
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


def test_batching_per_delivery_point_adds_up_to_production():
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Swiggy", store="WH1", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="40"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH2", parent_sku="Avocado",
             customer_sku_name="1PC - Nectar Avocado", qty="15"),
        dict(BASE, indent_id="C", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="1PC - Hass Avocado Imported", qty="30"),
    ])
    b = batching(df, _masters())
    assert list(b["Delivery point"]) == ["WH1", "WH2", "S1"]
    assert list(b["Customer"]) == ["Swiggy", "Swiggy", "Zepto"] and list(b["Qty"]) == [40, 15, 30]
    assert b["Qty"].sum() == production(df, _masters())["Qty"].sum() == 85


def test_pdf_of_production_sheet():
    from core.pdf_report import table_pdf
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
                      customer_sku_name="1PC - Hass Avocado Imported", qty="30")])
    assert table_pdf("Production sheet", ["Delivery: → ₹"], production(df, _masters()))[:5] == b"%PDF-"
    assert table_pdf("Empty", [], production(_lines([]), _masters()))[:5] == b"%PDF-"


NEW_TAB = [["City", "Customer", "Parent SKU", "Customer SKU Name", "variety", "Spec-Repacking", "Spec-Size",
            "Spec-Origin"],
           ["Bangalore", "Zepto", "Avocado", "2PC - Hass Avocado", "Hass", "Punnet", "20C, 22C", "Tanzania"],
           ["Bangalore", "Swiggy", "Avocado", "2PC - Nectar Avocado", "Hass", "Punnet", "20C, 22C", "Tanzania"],
           ["Bangalore", "Swiggy", "Apple", "1Kg - nectr Royal Gala Apple", "Royal Gala", "Box", "80, 90", "Turkey"],
           ["Bangalore", "Zepto", "Apple", "2PC - Apple Queen Imported", "Queen", "Punnet", "90, 110", "Turkey"]]


def _base_masters():
    from core.importer import PROD_BASE, build_prod_base
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(NEW_TAB))
    assert m.has_prod_base and PROD_BASE == "New"
    return m


def test_production_from_new_tab_columns_and_club_total():
    """Columns from the New tab (no origin); Total clubs all customers; Kg packs in kilos;
    variety only for Apple; box columns per count for piece packs."""
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="2PC - Hass Avocado", lot="Pack", qty="10"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Avocado",
             customer_sku_name="2PC - Nectar Avocado", lot="Pack", qty="20"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Apple",
             customer_sku_name="1Kg - nectr Royal Gala Apple", lot="Kg", qty="700"),
        dict(BASE, indent_id="C", version="1", customer="Zepto", store="S2", parent_sku="Avocado",
             customer_sku_name="2PC - Hass Avocado", lot="Pack", qty="5", city="Chennai"),
    ])
    p = production(df, _base_masters())
    assert list(p.columns) == ["City", "Parent SKU", "Variety", "Repacking", "Spec-Size", "Lot Size", "Qty",
                               "Total", "Boxes @ count 1", "Boxes @ count 2"]
    avo = p[(p["City"] == "Bangalore") & (p["Parent SKU"] == "Avocado")].iloc[0]
    assert (avo["Variety"], avo["Repacking"], avo["Spec-Size"], avo["Lot Size"]) == ("", "Punnet", "20C, 22C",
                                                                                    "2 Pcs")
    assert avo["Qty"] == 30 and avo["Total"] == "30 Punnet"
    # 30 packs x 2 pcs = 60 pcs: 20C -> 3 boxes, 22C -> 3 boxes (60/22 = 2.7, rounded up)
    assert avo["Boxes @ count 1"] == "20C: 3" and avo["Boxes @ count 2"] == "22C: 3"
    apple = p[p["Parent SKU"] == "Apple"].iloc[0]
    assert apple["Variety"] == "Royal Gala" and apple["Total"] == "700 Kg" and apple["Boxes @ count 1"] == ""
    chn = p[p["City"] == "Chennai"].iloc[0]      # not in the New tab for Chennai: kept apart
    assert chn["Spec-Size"].startswith("not in New tab") and chn["Qty"] == 5


def test_production_counts_and_kg_helpers():
    from core.production_calc import _counts, _kg_per_lot, _pcs_per_lot
    assert _counts("22C, 24C") == [22, 24] and _counts("90, 110") == [90, 110] and _counts("33 36") == [33, 36]
    assert _counts("16mm") == [] and _counts("2,3") == [] and _counts("Blue") == [] and _counts("-") == []
    assert _kg_per_lot("1 Kg", "Kg") == 1 and _kg_per_lot("", "Kg") == 1 and _kg_per_lot("200 gm", "Pack") is None
    assert _kg_per_lot("17.5 Kg Box", "Box") is None
    assert _pcs_per_lot("2 Pcs") == 2 and _pcs_per_lot("200 gm") is None and _pcs_per_lot("") is None and _pcs_per_lot("1 Pack") is None

def test_production_total_clubs_across_varieties_same_pack():
    """Different varieties keep their own rows; Total adds them when repacking, size and lot size match."""
    tab = NEW_TAB + [["Bangalore", "Zepto", "Apple", "2PC - Apple Gala Imported", "Gala", "Punnet", "90, 110",
                      "Turkey"]]
    from core.importer import build_prod_base
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(tab))
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Apple",
             customer_sku_name="2PC - Apple Queen Imported", lot="Pack", qty="12"),
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Apple",
             customer_sku_name="2PC - Apple Gala Imported", lot="Pack", qty="8"),
    ])
    p = production(df, m)
    assert len(p) == 2 and set(p["Qty"]) == {12, 8} and set(p["Total"]) == {"20 Punnet"}
    from core.production_calc import not_in_base
    assert not_in_base(df, m).empty


def test_not_in_new_tab_listed():
    from core.production_calc import not_in_base
    df = _lines([dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Kiwi",
                      customer_sku_name="2PC - Green Kiwi", qty="4")])
    gaps = not_in_base(df, _base_masters())
    assert list(gaps["Customer SKU Name"]) == ["2PC - Green Kiwi"]


def test_new_tab_read_from_sheet_values():
    from core.masters import frames_from_values, masters_from_frames
    frames, src = frames_from_values({"New": NEW_TAB})
    m = masters_from_frames(frames, src)
    info = m.prod_info("bangalore", "SWIGGY", "1kg - nectr  royal gala apple")
    assert info["Repacking"] == "Box" and info["Spec-Origin"] == "Turkey" and info["Variety"] == "Royal Gala"


def test_make_ready_list_mixes_sizes_and_handles_loose_and_boxes():
    """All customers and sizes together; loose fruit into trays/boxes in pcs/kg; box packs in boxes."""
    from core.importer import build_prod_base
    from core.production_calc import make_ready
    tab = NEW_TAB + [
        ["Bangalore", "More", "Avocado", "1Pc - Loose Avocado", "Hass", "Tray", "18C, 20C", "Tanzania"],
        ["Bangalore", "Zepto", "Avocado", "1Pc - Hass Avocado 90", "Hass", "Punnet", "22C", "Tanzania"],
        ["Bangalore", "Swiggy", "Avocado", "1Pc - Hass Avocado 110", "Hass", "Punnet", "24C", "Tanzania"],
        ["Bangalore", "Namdhari", "Apple", "1Box - Green apple", "Granny Smith", "Box", "90, 110", "Turkey"],
        ["Bangalore", "Zepto", "Apple", "200gm - Snacky Apple", "Gala", "Punnet", "135, 150", "Turkey"],
    ]
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(tab))
    row = lambda c, n, q, lot, p: dict(BASE, indent_id="A", version="1", customer=c, store="S",  # noqa: E731
                                       parent_sku=p, customer_sku_name=n, lot=lot, qty=q)
    df = _lines([row("More", "1Pc - Loose Avocado", "7", "Pcs", "Avocado"),
                 row("Zepto", "1Pc - Hass Avocado 90", "30", "Pcs", "Avocado"),
                 row("Swiggy", "1Pc - Hass Avocado 110", "20", "Pcs", "Avocado"),
                 row("Swiggy", "1Kg - nectr Royal Gala Apple", "700", "Kg", "Apple"),
                 row("Zepto", "2PC - Apple Queen Imported", "10", "Pack", "Apple"),
                 row("Namdhari", "1Box - Green apple", "10", "Box", "Apple"),
                 row("Zepto", "200gm - Snacky Apple", "725", "Pack", "Apple")])
    mr = make_ready(df, m)
    assert list(mr.columns) == ["City", "Parent SKU", "Variety", "Repacking", "Pack", "Make ready", "Fruit needed",
                                "Spec Size"]
    got = {(r["Parent SKU"], r["Variety"], r["Repacking"], r["Pack"]): (r["Make ready"], r["Fruit needed"])
           for r in mr.to_dict("records")}
    assert got[("Avocado", "", "Punnet", "1 Pcs")] == ("50 Punnet", "50 pcs")       # 22C + 24C mixed
    assert got[("Avocado", "", "Tray", "1 Pcs")] == ("7 pcs loose", "7 pcs")       # not 7 trays
    assert got[("Apple", "Royal Gala", "Box", "1 Kg")] == ("700 kg loose", "700 kg")
    assert got[("Apple", "Queen", "Punnet", "2 Pcs")] == ("10 Punnet", "20 pcs")
    assert got[("Apple", "Granny Smith", "Box", "1 Box")] == ("10 Box", "")
    assert got[("Apple", "Gala", "Punnet", "200 gm")] == ("725 Punnet", "")         # packets, no kg
    size = {(r["Parent SKU"], r["Repacking"], r["Pack"]): r["Spec Size"] for r in mr.to_dict("records")}
    assert size[("Avocado", "Punnet", "1 Pcs")] == "22C: 2 Tray | 24C: 1 Tray"      # 30/22, 20/24 rounded up
    assert size[("Avocado", "Tray", "1 Pcs")] == "18C: 1 Tray | 20C: 1 Tray"
    assert size[("Apple", "Punnet", "200 gm")] == "135C, 150C"                       # spec only
    assert size[("Apple", "Box", "1 Box")] == "90C, 110C"


def test_batching_takes_spec_and_variety_from_new_tab():
    """Temporary fix: batching uses the New tab like production (Spec = Spec-Size, Apple-only variety)."""
    df = _lines([
        dict(BASE, indent_id="A", version="1", customer="Zepto", store="S1", parent_sku="Avocado",
             customer_sku_name="2PC - Hass Avocado", lot="Pack", qty="10"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Apple",
             customer_sku_name="1Kg - nectr Royal Gala Apple", lot="Kg", qty="700"),
        dict(BASE, indent_id="B", version="1", customer="Swiggy", store="WH1", parent_sku="Kiwi",
             customer_sku_name="2PC - Green Kiwi", lot="Pack", qty="4"),
    ])
    raw = batching(df, _base_masters())
    b = raw.set_index("Customer SKU Name")
    assert list(raw.columns) == ["City", "Customer", "Delivery point", "Parent SKU", "Customer SKU Name",
                                             "Variety", "Lot", "Lot Size", "Spec", "Qty", "Indent"]
    assert b.loc["2PC - Hass Avocado", "Spec"] == "20C, 22C" and b.loc["2PC - Hass Avocado", "Variety"] == ""
    assert b.loc["1Kg - nectr Royal Gala Apple", "Spec"] == "80, 90"
    assert b.loc["1Kg - nectr Royal Gala Apple", "Variety"] == "Royal Gala"
    assert b.loc["2PC - Green Kiwi", "Spec"].startswith("not in New tab")
    assert b["Qty"].sum() == production(df, _base_masters())["Qty"].sum() == 714


def test_make_ready_boxes_and_blueberry_trays():
    from core.importer import build_prod_base
    from core.production_calc import make_ready
    m = _masters()
    m.prod_base = pd.DataFrame(build_prod_base(NEW_TAB + [
        ["Bangalore", "Zepto", "Apple", "2PC - Apple Royal Gala Imported", "Gala", "Punnet", "90, 100", "NZ"],
        ["Bangalore", "Zepto", "Blueberry", "125gm - Blueberry Imported", "", "Punnet", "16mm", "Peru"],
        ["Bangalore", "Swiggy", "Blueberry", "1Box - Imported Blueberry", "", "Punnet", "16mm", "Peru"]]))
    row = lambda c, n, q, lot, p: dict(BASE, indent_id="A", version="1", customer=c, store="S",  # noqa: E731
                                       parent_sku=p, customer_sku_name=n, lot=lot, qty=q)
    mr = make_ready(_lines([row("Zepto", "2PC - Apple Royal Gala Imported", "450", "Pcs", "Apple"),
                            row("Zepto", "125gm - Blueberry Imported", "100", "Pack", "Blueberry"),
                            row("Swiggy", "1Box - Imported Blueberry", "19", "Box", "Blueberry")]), m)
    got = {r["Parent SKU"]: (r["Pack"], r["Make ready"], r["Spec Size"]) for r in mr.to_dict("records")}
    assert got["Apple"] == ("2 Pcs", "450 Punnet", "90C: 10 Box | 100C: 9 Box")
    assert got["Blueberry"] == ("Punnet", "119 Punnet", "16mm: 10 Tray")      # 119 punnets / 12 a tray
