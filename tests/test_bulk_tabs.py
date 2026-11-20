"""20 Nov: Bulk indents (one tab per store) and Delivery_Times / Store_Aliases."""
import io

import pandas as pd

from core import bulk_tabs as bt, order_reader, store_settings
from core.po_reader import POLine
from core.sheets import LocalBackend

STORES = [("Swiggy", "Swiggy WH1"), ("Swiggy", "Swiggy WH2"), ("Swiggy", "Swiggy Cold Room_PTP"),
          ("Zepto", "Zepto - Yalachanayakanapura"), ("More", "More_BLR EKRAJPURA")]
CUST = ["Swiggy", "Zepto", "More"]


def test_tab_names_to_stores():
    assert bt.resolve_tab("Swiggy WH1", STORES, {}, CUST) == ("Swiggy", "Swiggy WH1", "store")
    assert bt.resolve_tab("swiggy wh2 ", STORES, {}, CUST)[1] == "Swiggy WH2"
    assert bt.resolve_tab("More", STORES, {}, CUST) == ("More", "More_BLR EKRAJPURA", "customer")
    assert bt.resolve_tab("Cold Room_PTP", STORES, {}, CUST)[1:] == ("Swiggy Cold Room_PTP", "close")
    assert bt.resolve_tab("Zepto YLK", STORES, {"zepto ylk": ("Zepto", "Zepto - Yalachanayakanapura")}, CUST)[2] == "saved"
    assert bt.resolve_tab("Swiggy Cold Room New", STORES, {}, CUST) == ("Swiggy", "", "")
    assert bt.resolve_tab("Bigbasket BLR", STORES, {}, CUST) == ("", "", "")


class R:
    def __init__(self, lines):
        self.lines = lines


def test_same_item_twice_is_added_up():
    names = {"1pc - avocado imported ea (hass)": "1Pc - Avocado Imported Ea (Hass)"}
    links = {"avocado imported ea (hass) - 1 pc": "1Pc - Avocado Imported Ea (Hass)"}
    got = bt.lines_for(R([POLine("Avocado Imported Ea (Hass) - 1 Pc", 370), POLine("Avocado Imported Ea (Hass) - 1 Pc", 49),
                          POLine("Mango Alphonso - 1 Kg", 2)]), names, links, ["Avocado", "Kiwi"])
    assert [(x.sku, x.qty, x.status, x.combined) for x in got] == [
        ("1Pc - Avocado Imported Ea (Hass)", 419, "ok", True), ("1Kg - Mango Alphonso", 2, "red", False)]


def test_compare_with_saved():
    lines = [bt.Line("A", 10, "ok"), bt.Line("B", 5, "ok"), bt.Line("C", 1, "new")]
    assert bt.compare({"a": 10, "b": 4}, lines) == (["B 4→5"], ["C"])
    assert bt.compare({"a": 10, "b": 5, "c": 1}, lines) == ([], [])


def test_read_tabs_one_per_store():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame([["Kiwi Sungold", "1 Pack", 39]], columns=["Customer SKU name", "UOM", "Qty"]).to_excel(
            w, sheet_name="Zepto YLK", index=False)
        pd.DataFrame([["Imported Avocado", "1 PC", 120]], columns=["Customer SKU name", "UOM", "Qty"]).to_excel(
            w, sheet_name="Swiggy WH1", index=False)
        pd.DataFrame([["notes only"]]).to_excel(w, sheet_name="Notes", index=False)
    tabs = order_reader.read_tabs(buf.getvalue())
    assert [(n, [(x.name, x.qty) for x in r.lines]) for n, r in tabs] == [
        ("Zepto YLK", [("Kiwi Sungold - 1 Pack", 39)]), ("Swiggy WH1", [("Imported Avocado - 1 PC", 120)])]


def test_delivery_times_and_aliases(tmp_path):
    b = LocalBackend(tmp_path)
    b.ensure_tabs()
    store_settings.save_times(b, [{"City": "B", "Customer": "Swiggy", "Store": "Swiggy WH1", "Time": "10:30"}], "u")
    store_settings.save_times(b, [{"City": "B", "Customer": "Swiggy", "Store": "Swiggy WH2", "Time": "11:00"},
                                  {"City": "B", "Customer": "Swiggy", "Store": "Swiggy WH1", "Time": "12:00"}], "u")
    assert store_settings.times(b) == {("b", "swiggy", "swiggy wh1"): "12:00", ("b", "swiggy", "swiggy wh2"): "11:00"}
    assert store_settings.time_for(b, "B", "swiggy", "SWIGGY WH2") == "11:00"
    store_settings.save_aliases(b, "B", [("Zepto YLK", "Zepto", "Zepto - Yalachanayakanapura")], "u")
    assert store_settings.aliases(b, "B") == {"zepto ylk": ("Zepto", "Zepto - Yalachanayakanapura")}


def test_duplicate_names():
    df = pd.DataFrame([["B", "Zepto", n] for n in [
        "1Pack - Kiwi Sungold", "1Pack - Kiwi Sungold", "2PC - Kiwi Sungold", "2PC - Sungold Kiwi",
        "2PC - Bloom Kiwi Sungold Imported (New Zealand)", "3Pc - Kiwi Green", "1Pc - Hass"]] + [
        ["B", "More", "1Pc - Hass"], ["B", "More", "1Pc - Hass"]], columns=["City", "Customer", "Customer SKU Name"])
    got = {(r["Customer"], r["Names"]): r["Kind"] for r in bt.duplicate_names(df)}
    assert got == {("More", "1Pc - Hass ×2"): "same name on several rows",
                   ("Zepto", "1Pack - Kiwi Sungold ×2 | 2PC - Kiwi Sungold | 2PC - Sungold Kiwi"):
                       "3 names, same words (check the packs)"}


def test_one_pack_name_style():
    from core import master_add
    assert master_add.new_sku_name("Kiwi Sungold - 1 Pack") == "1Pack - Kiwi Sungold"
    assert master_add.new_sku_name("Kiwi Sungold - 2 PIECE") == "2PC - Kiwi Sungold"
