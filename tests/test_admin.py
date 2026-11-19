import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main

H = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client():
    main._hits.clear()
    main._admin_fail.clear()
    c = TestClient(main.app)
    yield c
    main._admin_fail.clear()
    for d in c.get("/api/admin/docs", headers=H).json():
        c.delete(f"/api/admin/docs/{d['id']}", headers=H)
    for e in c.get("/api/admin/entries", headers=H).json():
        c.delete(f"/api/admin/entries/{e['id']}", headers=H)


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    return buf.getvalue()


def test_requires_token(client):
    assert client.get("/api/admin/entries").status_code == 401
    assert client.get("/api/admin/entries", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/admin/ping", headers=H).status_code == 200
    assert client.get("/api/admin/ping", headers={"X-Admin-Token": "test-token"}).status_code == 200


def test_brute_force_lockout(client):
    for _ in range(10):
        client.get("/api/admin/ping", headers={"Authorization": "Bearer bad"})
    assert client.get("/api/admin/ping", headers=H).status_code == 429


def test_admin_disabled_without_token(client, monkeypatch):
    monkeypatch.setattr(main.settings, "admin_token", "")
    assert client.get("/api/admin/ping", headers=H).status_code == 503


def test_local_entry_shows_in_diagnose(client):
    r = client.post(
        "/api/admin/entries",
        headers=H,
        json={"series": "atv320", "code": "XZ99", "name": "皮带机现场故障", "cause": "编码器线松", "remedy": "紧固 X3 端子", "reset": "power"},
    )
    assert r.status_code == 200, r.text
    j = client.post("/api/diagnose", data={"code": "XZ99"}).json()
    assert j["entries"][0]["origin"] == "local" and j["entries"][0]["series"] == "ATV320"
    assert "紧固 X3" in j["answer"]
    eid = r.json()["id"]
    assert client.delete(f"/api/admin/entries/{eid}", headers=H).status_code == 200
    assert not client.post("/api/diagnose", data={"code": "XZ99"}).json()["entries"]


def test_doc_text_and_image_roundtrip(client):
    r = client.post(
        "/api/admin/docs",
        headers=H,
        data={"title": "1号皮带 ATV320 接线", "kind": "wiring", "series": "ATV320", "codes": "OCF", "text": "DI1 接启动按钮，端子 X1:3 到 变频器 DI1", "ai_read": "false"},
        files=[("files", ("wire.png", png(), "image/png"))],
    )
    assert r.status_code == 200, r.text
    doc = r.json()["doc"]
    assert doc["files"][0]["type"] == "image"
    j = client.post("/api/diagnose", data={"code": "OCF", "series": "ATV320"}).json()
    assert any(n["title"] == "1号皮带 ATV320 接线" for n in j["notes"])
    name = doc["files"][0]["name"]
    f = client.get(f"/api/docs/{doc['id']}/files/{name}")
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg"
    # free-text search without a code
    j = client.post("/api/diagnose", data={"note": "X1:3 DI1 启动按钮"}).json()
    assert j["notes"]


def test_file_path_traversal_blocked(client):
    for bad in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "nothere.jpg"):
        assert client.get(f"/api/docs/xx/files/{bad}").status_code in (404, 400)


def test_txt_upload_searchable(client):
    r = client.post(
        "/api/admin/docs",
        headers=H,
        data={"title": "案例", "kind": "case", "series": "", "codes": "", "text": ""},
        files=[("files", ("case.txt", "2号泵 SCF1 故障：电机线对地绝缘低，更换电缆后恢复".encode(), "text/plain"))],
    )
    assert r.status_code == 200, r.text
    j = client.post("/api/diagnose", data={"code": "SCF1"}).json()
    assert any("绝缘" in n["snippet"] for n in j["notes"])


def test_bad_kind_and_upload_limit(client, monkeypatch):
    r = client.post("/api/admin/docs", headers=H, data={"title": "x", "kind": "evil", "text": "a"})
    assert r.status_code == 200 and r.json()["doc"]["kind"] == "note"  # unknown kind -> note
    assert client.post("/api/admin/docs", headers=H, data={"title": " ", "kind": "note", "text": "a"}).status_code == 400
    monkeypatch.setattr(main.settings, "max_upload_mb", 0.0001)
    r = client.post(
        "/api/admin/docs", headers=H, data={"title": "big", "kind": "note", "text": "a"},
        files=[("files", ("a.txt", b"x" * 5000, "text/plain"))],
    )
    assert r.status_code == 413


def test_export_zip(client):
    client.post("/api/admin/docs", headers=H, data={"title": "t", "kind": "note", "text": "hello"})
    r = client.get("/api/admin/export", headers=H)
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_admin_page_served(client):
    r = client.get("/admin/")
    assert r.status_code == 200 and "知识库管理" in r.text
    assert client.get("/admin", follow_redirects=True).status_code == 200
