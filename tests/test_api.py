import io
import os

os.environ["LLM_PROVIDER"] = "none"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main


@pytest.fixture()
def client():
    main._hits.clear()
    return TestClient(main.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["llm"] == "none"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "变频器故障查询" in r.text


def test_series(client):
    ids = {s["id"] for s in client.get("/api/series").json()}
    assert "ATV600" in ids


def test_diagnose_code(client):
    r = client.post("/api/diagnose", data={"code": "OCF", "series": "ATV600"})
    j = r.json()
    assert r.status_code == 200
    assert j["mode"] == "kb" and j["codes"] == ["OCF"]
    assert j["entries"][0]["series"] == "ATV600"
    assert "OCF" in j["answer"]


def test_diagnose_unknown_code(client):
    j = client.post("/api/diagnose", data={"code": "ZZZZ9"}).json()
    assert j["mode"] == "none" and j["entries"] == []


def test_empty_request_rejected(client):
    assert client.post("/api/diagnose", data={}).status_code == 400


def test_image_without_llm_warns(client):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    r = client.post(
        "/api/diagnose",
        data={"code": "SCF1"},
        files={"image": ("p.png", buf.getvalue(), "image/png")},
    )
    j = r.json()
    assert r.status_code == 200 and j["codes"] == ["SCF1"]
    assert any("照片" in w for w in j["warnings"])


def test_bad_image_rejected(client):
    r = client.post(
        "/api/diagnose",
        data={"code": "OCF"},
        files={"image": ("x.jpg", b"not an image", "image/jpeg")},
    )
    assert r.status_code == 400


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main.settings, "rate_limit_per_min", 2)
    for _ in range(2):
        assert client.post("/api/diagnose", data={"code": "OCF"}).status_code == 200
    assert client.post("/api/diagnose", data={"code": "OCF"}).status_code == 429
