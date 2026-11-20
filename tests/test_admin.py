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
    with TestClient(main.app) as c:  # one event loop, so background import tasks keep running
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


def test_import_url_allowlist(client):
    for bad in ("http://download.se.com/a.pdf", "https://evil.example.com/a.pdf", "https://download.se.com@evil.com/a.pdf",
                "https://127.0.0.1/a.pdf", "file:///etc/passwd", "https://download.se.com:8443/a.pdf"):
        r = client.post("/api/admin/import-url", headers=H, data={"url": bad})
        assert r.status_code == 400, bad


def test_import_url_job(client, monkeypatch):
    import io
    from pypdf import PdfWriter
    from app import importer

    w = PdfWriter()
    w.add_blank_page(200, 200)
    buf = io.BytesIO()
    w.write(buf)

    async def fake_fetch(url, max_bytes, timeout=120):
        return buf.getvalue()

    monkeypatch.setattr(importer, "fetch_pdf", fake_fetch)
    r = client.post("/api/admin/import-url", headers=H, data={"url": "https://download.se.com/doc/X/x.pdf", "title": "测试手册", "series": "ATV320"})
    assert r.status_code == 200, r.text
    import time
    for _ in range(50):
        jobs = client.get("/api/admin/import-jobs", headers=H).json()
        if jobs and jobs[0]["state"] != "running":
            break
        time.sleep(0.1)
    assert jobs[0]["state"] == "done", jobs
    assert any(d["title"] == "测试手册" and d["kind"] == "manual" for d in client.get("/api/admin/docs", headers=H).json())


def test_catalog(client):
    cat = client.get("/api/admin/catalog", headers=H).json()
    assert len(cat) >= 6 and all(c["url"].startswith("https://download.") for c in cat)


def test_redirect_must_stay_on_allowlist():
    import asyncio
    import httpx
    from app import importer

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "download.se.com":
            return httpx.Response(302, headers={"location": "https://evil.example.com/x.pdf"})
        raise AssertionError("must not be requested")

    real = httpx.AsyncClient
    monkey = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)  # noqa: E731
    importer.httpx.AsyncClient = monkey
    try:
        with pytest.raises(importer.ImportError_):
            asyncio.run(importer.fetch_pdf("https://download.se.com/doc/a.pdf", 1000))
    finally:
        importer.httpx.AsyncClient = real


def test_health_explains_disabled_admin(client, monkeypatch):
    monkeypatch.setattr(main.settings, "admin_token", "")
    h = client.get("/api/health").json()
    assert h["admin"] is False and "env_files" in h["admin_hint"]
    monkeypatch.setattr(main.settings, "admin_token", "test-token")
    assert client.get("/api/health").json()["admin_hint"] is None


def test_token_quotes_stripped(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", '"abc123"')
    from app.config import Settings
    assert Settings().admin_token == "abc123"


def test_env_example_hint(monkeypatch, tmp_path):
    from app import config
    (tmp_path / ".env.example").write_text("ADMIN_TOKEN=abc123\n", encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    hint = config.Settings().admin_hint()
    assert hint["example_has_token"] is True


def test_dotenv_txt_variant(monkeypatch, tmp_path):
    from app import config
    (tmp_path / ".env.txt").write_text("MY_TEST_VAR_X=hello\n", encoding="utf-8")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MY_TEST_VAR_X", raising=False)
    config.load_dotenv()
    import os
    assert os.environ.get("MY_TEST_VAR_X") == "hello"
    monkeypatch.delenv("MY_TEST_VAR_X", raising=False)


def test_missing_expert_file_falls_back_to_bundle(tmp_path):
    from app.expert import Expert
    from app.kb import KnowledgeBase
    (tmp_path / "x.psv").write_text("# series: X1\nAAA|名|因|法|power\n", encoding="utf-8")
    ex = Expert(tmp_path)  # tmp_path has no expert/families.json -> bundled copy is used
    assert len(ex.families) >= 12
    kb = KnowledgeBase(tmp_path, fallback_dir="data")
    assert "X1" in kb.series and "ATV900" in kb.series  # old external folder + bundled series


def test_site_title_default_and_custom(client):
    j = client.get("/api/site").json()
    assert j["title"] == "变频器故障查询"
    r = client.put("/api/admin/site", headers=H, json={"title": "  某某矿  变频器查询系统 ", "subtitle": "仅限厂内使用"})
    assert r.status_code == 200 and r.json()["title"] == "某某矿 变频器查询系统"
    assert client.get("/api/site").json() == {"title": "某某矿 变频器查询系统", "subtitle": "仅限厂内使用"}
    assert client.put("/api/admin/site", json={"title": "x"}).status_code == 401
    assert len(client.put("/api/admin/site", headers=H, json={"title": "长" * 100}).json()["title"]) == 40
    client.put("/api/admin/site", headers=H, json={"title": ""})  # reset
    assert client.get("/api/site").json()["title"] == "变频器故障查询"


def test_site_title_from_env(client, monkeypatch):
    monkeypatch.setattr(main.settings, "site_title", "环境变量标题")
    assert client.get("/api/site").json()["title"] == "环境变量标题"
