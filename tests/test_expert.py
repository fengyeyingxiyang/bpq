import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.expert import Expert

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def ex():
    return Expert(DATA)


def test_families_well_formed(ex):
    assert len(ex.families) >= 12
    for f in ex.families.values():
        assert f["causes"] and f["steps"] and f["stop"] and f["mechanism"]
        assert all("c" in c and "tell" in c for c in f["causes"])


def test_every_manual_code_family_codes_exist(ex):
    # codes listed in families that are real manual codes should resolve; at least most should
    from app.kb import KnowledgeBase, norm
    kb = KnowledgeBase(DATA)
    known = {norm(e.code) for e in kb.entries}
    listed = [c for f in ex.families.values() for c in f["codes"] if len(c) >= 3 and c[0] != "F"]
    hit = [c for c in listed if norm(c) in known]
    assert len(hit) / len(listed) > 0.8, [c for c in listed if norm(c) not in known]


def test_classify_by_code(ex):
    assert ex.classify(["OCF"], [])[0]["id"] == "overcurrent"
    assert ex.classify(["SCF1"], [])[0]["id"] == "short_ground"
    assert ex.classify(["OBF"], [])[0]["id"] == "overvoltage"
    assert ex.classify(["ocf"], [])[0]["id"] == "overcurrent"


def test_classify_by_symptom_only(ex):
    assert ex.classify([], [], "减速的时候就跳闸")[0]["id"] == "overvoltage"
    assert "short_ground" in {f["id"] for f in ex.classify([], [], "下雨以后一启动就跳", 2)}


def test_classify_by_entry_wording(ex):
    fam = ex.classify(["XYZ"], [{"code": "XYZ", "name": "未知", "cause": "散热器温度过高 overheat"}])
    assert fam and fam[0]["id"] == "drive_overtemp"


def test_prompt_compact_is_shorter(ex):
    fams = ex.classify(["OCF"], [])
    assert len(ex.for_prompt(fams, compact=True)) < len(ex.for_prompt(fams))


def test_diagnose_includes_expert_without_llm():
    main._hits.clear()
    j = TestClient(main.app).post("/api/diagnose", data={"code": "OCF", "series": "ATV320"}).json()
    assert j["expert"] and j["expert"][0]["id"] == "overcurrent"
    assert "排查步骤" in j["answer"] and "通用经验" in j["answer"]


def test_symptom_only_query_gets_answer():
    main._hits.clear()
    j = TestClient(main.app).post("/api/diagnose", data={"note": "减速的时候就跳闸"}).json()
    assert j["expert"] and "排查" in j["answer"]


def test_prompt_contains_expert_block(monkeypatch):
    fams = main.expert.classify(["OCF"], [])
    prompt = main._build_prompt(["OCF"], [], [], "", None, fams)
    assert "<expert>" in prompt and "过电流" in prompt
    monkeypatch.setattr(main.settings, "small_model", True)
    assert main.SMALL_SYSTEM_PROMPT and "示例" in main.SMALL_SYSTEM_PROMPT
