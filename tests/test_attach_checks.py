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


def test_gemini_answer_is_parsed():
    from core import ai_reader
    r = ai_reader.parse({"customer": "More Retail", "store": "Ekrajpura", "total": 117, "notes": "",
                         "lines": [{"name": "Avocado Hass", "pack": "1 pc", "qty": 100, "sure": True},
                                   {"name": "Blueberry", "pack": "125 g", "qty": 17, "sure": False},
                                   {"name": "Kiwi", "pack": "", "qty": 0, "sure": False}]})
    assert [(x.name, x.qty, x.unsure) for x in r.lines] == [("Avocado Hass - 1 pc", 100, False),
                                                           ("Blueberry - 125 g", 17, True)]
    assert r.total == 117 and "More Retail" in r.text
    assert order_reader.whose(r.text, AL) == {"More"}


def test_pictures_follow_the_key(monkeypatch):
    vals = {}
    monkeypatch.setattr(config, "get", lambda k, d=None: vals.get(k, d))
    assert not config.read_pictures()
    vals["gemini_api_key"] = "x"
    assert config.read_pictures()
    vals["read_pictures"] = "false"
    assert not config.read_pictures()


def test_picture_in_order_reader(monkeypatch):
    from core import picture_table as pt
    monkeypatch.setattr(pt, "readers", lambda: ["gemini"])
    monkeypatch.setattr(pt, "read", lambda data, name: pt.parse_gemini(
        {"customer": "Swiggy", "stores": ["WH1", "WH2"], "totals": [600, 40],
         "lines": [{"name": "Apple Snacky 2 pcs", "qtys": [600, 0], "sure": True},
                   {"name": "Kiwi 3 pcs", "qtys": [0, 40], "sure": False}]}))
    r = order_reader.read("wa.jpg", b"img", "Swiggy WH2")
    assert r.kind == "picture" and [(x.name, x.qty, x.unsure) for x in r.lines] == [("Kiwi 3 pcs", 40, True)]
    assert r.total == 40 and "Swiggy" in r.text
    r = order_reader.read("wa.jpg", b"img", "Swiggy WH1")
    assert [x.qty for x in r.lines] == [600]


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


def test_gemini_busy_falls_back(monkeypatch):
    from core import ai_reader
    monkeypatch.setattr(ai_reader, "api_key", lambda: "k")
    calls = []

    def fake(model, img, mime, key):
        calls.append(model)
        if model == ai_reader.DEFAULT_MODEL:
            raise ai_reader.Busy("busy (503)")
        return {"lines": [{"name": "Kiwi", "qty": 5, "sure": True}]}
    monkeypatch.setattr(ai_reader, "_call", fake)
    r = ai_reader.read(b"x")
    assert calls == [ai_reader.DEFAULT_MODEL, "gemini-2.5-flash"] and r.model == "gemini-2.5-flash"

    monkeypatch.setattr(ai_reader, "_call", lambda *a: (_ for _ in ()).throw(ai_reader.Busy("busy (503)")))
    import pytest
    with pytest.raises(ai_reader.AIReadError, match="Read again"):
        ai_reader.read(b"x")
