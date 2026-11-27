from core import config
from core.models import IndentHeader


def test_facilities_and_defaults():
    assert config.facilities("PTP Bangalore") == ["PTP_Cheemchandra", "PTP_Spar", "PTP_Fusion_Huskur"]
    assert config.facilities("PTP Mumbai") == []
    assert config.is_direct_facility("PTP_Spar") and config.is_direct_facility("ptp_fusion_huskur")
    assert not config.is_direct_facility("PTP_Cheemchandra") and not config.is_direct_facility("")
    assert config.facility_of("PTP Bangalore", "") == "PTP_Cheemchandra"
    assert config.facility_of("PTP Bangalore", float("nan")) == "PTP_Cheemchandra"
    assert config.facility_of("PTP Bangalore", "PTP_Spar") == "PTP_Spar" and config.facility_of("PTP Mumbai") == ""


def test_header_keeps_facility_but_does_not_require_it():
    h = IndentHeader("2026-11-27", "PTP Bangalore", "Reliance", "PTP_Fusion_Huskur", "10:00", "PTP_Fusion_Huskur")
    assert h.to_dict()["facility"] == "PTP_Fusion_Huskur" and h.missing() == []
    assert IndentHeader.from_dict({"city": "x"}).facility == ""
