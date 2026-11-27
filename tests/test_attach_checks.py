"""19 Nov night: attached file must be the chosen customer's; Saved vs File; screenshot POs."""
from core import config, order_reader
from core.mailer import file_mime

AL = config.customer_aliases()


def test_file_of_another_customer_is_refused():
    found = order_reader.whose("Purchase Order  Flipkart India Pvt Ltd  Avocado", AL)
    assert found == {"Flipkart"}
    assert order_reader.wrong_customer("Zepto", found) == "Flipkart"
    assert order_reader.wrong_customer("flipkart", found) == ""


def test_file_naming_nobody_or_both_is_allowed():
    assert order_reader.wrong_customer("Zepto", order_reader.whose("Avocado 120 Kiwi 30", AL)) == ""
    both = order_reader.whose("Swiggy Instamart order, supplier Moksh; ref Zepto", AL)
    assert order_reader.wrong_customer("Zepto", both) == ""


def test_more_is_not_matched_by_the_plain_word():
    assert order_reader.whose("Add more kiwi if possible", AL) == set()
    assert order_reader.whose("MORE RETAIL LTD - EKRAJPURA", AL) == {"More"}


def test_format_and_file_name_count():
    assert order_reader.whose("", AL, hint="Zepto") == {"Zepto"}
    assert order_reader.whose("", AL, file_name="swiggy_wh1_indent.xlsx") == {"Swiggy"}


def test_change_cell():
    from pages_src.attach import _change
    assert _change("", 559, 600, True) == "🟡 +41"
    assert _change("", 53, 40, True) == "🔻 −13"
    assert _change("", 107, 107, True) == "✓ same"
    assert _change("", None, 52, True) == "🆕 added"
    assert _change("new", None, 52, True) == "🆕 new item"
    assert _change("", None, 5, False) == "✓ exact name"


def test_screenshot_po():
    assert "more" in config.no_po_customers()
    assert file_mime("IN-021 - wa.jpg") == "image/jpeg" and file_mime("po.pdf") == "application/pdf"


def test_bigbasket_names_in_our_style():
    from core import master_add as ma
    assert ma.new_sku_name("Fresho Kiwi - Green 3 pcs  ( 240 Gms *)") == "3PC - Fresho Kiwi - Green (240 Gms)"
    assert ma.new_sku_name("Fresho Baby Orange 1 kg  ( Imported)") == "1Kg - Fresho Baby Orange (Imported)"
    assert ma.new_sku_name("Fresho Blueberry 125 g") == "125gm - Fresho Blueberry"
    assert ma.new_sku_name("Avocado Hass Imported") == "Avocado Hass Imported"
    assert ma.new_sku_name("Pear Packham Imported - 2 PIECE") == "2PC - Pear Packham Imported"
    assert ma.guess_parent("Fresho Baby Orange 1 kg", ["Orange", "Mandarin"]) == "Mandarin"
    assert ma.guess_parent("Orange Imported", ["Orange", "Mandarin"]) == "Orange"


def test_links_for_new_items(monkeypatch):
    from pages_src import attach
    rows = attach.links_to_save("Bigbasket", [
        {"Customer SKU Name": "125gm - Fresho Blueberry", "From file": "Fresho Blueberry 125 g"},
        {"Customer SKU Name": "1Pc - Hass", "From file": "1pc - hass"}])
    assert [(r["PO Item Name"], r["Customer SKU Name"]) for r in rows] == [("Fresho Blueberry 125 g",
                                                                          "125gm - Fresho Blueberry")]


def test_freeze_customers_24nov():
    from core import config
    for c in ["Trent", "Trent Hypermarket", "Amazon", "Bigbasket", "Reliance", "More", "Metro", "Namdhari", "Firstclub"]:
        assert config.can_freeze(c), c
    for c in ["Swiggy", "Zepto", "Zomato", "Moreover"]:
        assert not config.can_freeze(c), c
    assert config.po_first("Amazon") and config.po_first("Firstclub") and not config.po_first("Namdhari")
    assert not config.po_first("Trent")
