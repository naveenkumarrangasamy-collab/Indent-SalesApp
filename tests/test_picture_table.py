"""19 Nov night: picture -> table (items x store columns), store guessing."""
from core import picture_table as pt


def test_bigbasket_like_text():
    t = pt.parse_lines(["Date\t20-Nov-26\t1,050", "Sku Code\tSku Description\tRoot Link Con",
                        "20000911\tFresho Kiwi - Green 3 pcs  ( 240 Gms *)\t700",
                        "20003955\tFresho Baby Orange 1 kg  ( Imported)\t200",
                        "30009286\tFresho Blueberry 125 g\t150", "-\t-\t1,050"])
    assert t.stores == ["Root Link Con"] and t.totals == [1050]
    assert [(r.code, r.qtys) for r in t.rows] == [("20000911", [700]), ("20003955", [200]), ("30009286", [150])]


def test_two_store_columns():
    t = pt.parse_lines(["Item  WH1  WH2", "Kiwi Green 3pc  100  50", "Avocado Hass 1pc  30", "Total  100  80"])
    assert t.stores == ["WH1", "WH2"] and t.totals == [100, 80]
    assert [r.qtys for r in t.rows] == [[100, 50], [0, 30]]


def test_guess_store_and_column():
    st = ["Swiggy WH1", "Swiggy WH2"]
    assert pt.guess_store("FNV1", st) == "Swiggy WH1" and pt.guess_store("MBF", st) == "Swiggy WH1"
    assert pt.guess_store("WH 2", st) == "Swiggy WH2" and pt.guess_store("Zepto", st) == ""
    t = pt.parse_gemini({"stores": ["WH1", "WH2"], "lines": [{"name": "Kiwi", "qtys": [1, 2], "sure": True}]})
    assert pt.pick_column(t, "Swiggy WH2") == 1 and pt.pick_column(t, "Swiggy WH1") == 0


def test_chain_falls_through(monkeypatch):
    monkeypatch.setattr(pt, "readers", lambda: ["gemini", "ocrspace"])
    monkeypatch.setattr(pt, "read_gemini", lambda d, m: (_ for _ in ()).throw(pt.TableReadError("busy")))
    monkeypatch.setattr(pt, "read_ocrspace", lambda d: pt.parse_lines(["Kiwi 3pc  12"]))
    t = pt.read(b"x", "a.jpg")
    assert t.rows[0].qtys == [12] and "busy" in t.notes


def test_small_jpeg_under_one_mb():
    import io
    import random
    from PIL import Image
    im = Image.new("RGB", (3000, 3000))
    im.putdata([(random.randint(0, 255),) * 3 for _ in range(3000 * 3000)])
    b = io.BytesIO()
    im.save(b, "PNG")
    assert len(pt._small_jpeg(b.getvalue())) <= 950_000
