from pathlib import Path

import pytest

from app.kb import KnowledgeBase, norm

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(DATA)


def test_series_loaded(kb):
    assert {"ATV12", "ATV61", "ATV600"} <= set(kb.series)
    assert all(s["count"] > 0 for s in kb.series.values())


def test_no_malformed_rows():
    for path in DATA.glob("*.psv"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                assert len(line.split("|")) == 5, f"{path.name}: {line[:60]}"


def test_lookup_case_insensitive(kb):
    assert kb.lookup("ocf")
    assert kb.lookup(" O-C-F ")
    assert {"ATV12", "ATV61", "ATV600", "ATV320", "ATV340"} <= {e.series for e in kb.lookup("OCF")}


def test_lookup_series_filter(kb):
    hits = kb.lookup("OCF", "ATV600")
    assert [e.series for e in hits] == ["ATV600"]
    # unknown in that series -> falls back to others
    assert kb.lookup("bOF", "ATV600")[0].series != "ATV600"


def test_slash_groups_expanded(kb):
    for c in ("LFF1", "LFF5", "t4CF", "tH5F", "IFd"):
        assert kb.lookup(c, "ATV600"), c


def test_extract_codes_from_chinese_text(kb):
    exact, approx = kb.extract_codes("面板显示 SCF1 短路，怎么办")
    assert exact == ["SCF1"] and not approx
    exact, _ = kb.extract_codes("ocf过流")
    assert exact == ["OCF"]


def test_extract_codes_fuzzy(kb):
    exact, approx = kb.extract_codes("OCFF")
    assert not exact and approx == ["OCF"]


def test_resolve_series(kb):
    assert kb.resolve_series("ATV 630") == "ATV600"
    assert kb.resolve_series("atv12") == "ATV12"
    assert kb.resolve_series("") is None


def test_norm():
    assert norm("COM.E") == "come"


def test_atv900_series_and_codes():
    from app.kb import KnowledgeBase
    kb = KnowledgeBase("data")
    assert kb.resolve_series("ATV930C13N4C") == "ATV900"
    assert kb.resolve_series("ATV630HD15N4") == "ATV600"
    assert kb.lookup("BUF", "ATV900")[0].series == "ATV900"
    assert kb.lookup("INFD", "ATV900")[0].cause
    assert all(e.series != "ATV600" for e in kb.lookup("BUF", "ATV600"))  # falls back to other series
