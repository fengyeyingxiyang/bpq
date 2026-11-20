from pathlib import Path

from app.kb import KnowledgeBase


def test_kb_resolves_new_vendor_families_without_fault_tables():
    kb = KnowledgeBase(Path(__file__).resolve().parent.parent / "data")
    assert kb.resolve_series("ABB ACS880-01") == "ACS880"
    assert kb.resolve_series("Siemens SINAMICS G120C") == "SINAMICS G120C"
    assert kb.resolve_series("Danfoss VLT FC302") == "VLT FC302"
    assert kb.resolve_series("INVT GD200A") == "GD200A"
    assert kb.resolve_series("汇川 MD520") == "MD520"


def test_kb_keeps_schneider_family_resolution():
    kb = KnowledgeBase(Path(__file__).resolve().parent.parent / "data")
    assert kb.resolve_series("ATV630HD15N4") == "ATV600"
    assert kb.resolve_series("ATV930C13N4C") == "ATV900"
