import io
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import main
from app.store import LocalStore, clean_text, looks_garbled

H = {"Authorization": "Bearer test-token"}


def blank_pdf(pages=1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.fixture()
def store():
    d = tempfile.mkdtemp(prefix="fa-ret-")
    st = LocalStore(d)
    yield st
    shutil.rmtree(d, ignore_errors=True)


def add_manual(store, title, series, pages, kind="manual"):
    doc = store.create_doc(title, kind, series, "", "")
    store._docs[doc["id"]]["files"].append({"name": "m.pdf", "orig": "m.pdf", "type": "pdf", "size": 1, "pages": len(pages)})
    store._pages[doc["id"]] = [{"page": i, "file": "m.pdf", "text": t} for i, t in pages.items()]
    store._reindex()
    return doc["id"]


PAGES = {
    10: "OCF 过电流\n可能原因：惯量或负载过高；机械堵塞。\n解决措施：减小 [电流限幅] CLI。",
    50: "[进线接触器动作超时] LCT\n设置输入接触器闭合的最长等待时间，默认 5 s。",
    51: "[电流限幅] CLI\n限制变频器输出的最大电流，单位 A。",
    70: "安装环境：温度 -10 ～ 50 ℃，湿度不超过 95 %，无凝露。",
}


def test_clean_text_removes_cjk_gaps():
    assert clean_text("过 电 流 故 障 OCF 已 触发") == "过电流故障 OCF 已触发"
    assert clean_text("Motor thermal current") == "Motor thermal current"


def test_garbled_detection():
    assert looks_garbled("�" * 200)
    assert not looks_garbled("过电流故障，请检查电机和电缆。OCF overcurrent " * 20)
    assert not looks_garbled("短")


def test_code_heading_page_ranks_first(store):
    add_manual(store, "ATV320 编程手册", "ATV320", PAGES)
    r = store.search(["OCF"], "", "ATV320")
    assert r[0]["page"] == 10


def test_parameter_names_from_remedy_find_parameter_pages(store):
    add_manual(store, "ATV320 编程手册", "ATV320", PAGES)
    r = store.search(["LCF"], "输入接触器", "ATV320", params=["进线接触器动作超时", "LCT"])
    assert r and r[0]["page"] == 50
    r = store.search(["OCF"], "", "ATV320", params=["电流限幅", "CLI"])
    assert {x["page"] for x in r} >= {10, 51}


def test_same_series_and_plant_notes_rank_higher(store):
    add_manual(store, "ATV610 编程手册", "ATV610", {5: "OCF 过电流 检查电机"})
    add_manual(store, "ATV320 编程手册", "ATV320", {7: "OCF 过电流 检查电机"})
    r = store.search(["OCF"], "", None)
    assert len(r) == 2
    r = store.search(["OCF"], "", "ATV320")
    assert [x["series"] for x in r] == ["ATV320"]  # other series' manuals are not mixed in
    nid = add_manual(store, "3号机现场案例", "ATV320", {1: "OCF 过电流，原因是皮带跑偏卡住"}, kind="case")
    r = store.search(["OCF"], "", "ATV320")
    assert r[0]["doc_id"] == nid


def test_irrelevant_query_returns_nothing(store):
    add_manual(store, "ATV320 编程手册", "ATV320", PAGES)
    assert store.search(["ZZZ9"], "", "ATV320") == []


def test_fault_params_extracted_from_entries():
    ps = main._fault_params([{"cause": "x", "remedy": "检查 [进线接触器动作超时] LCT 超时设置；减小 [电流限幅] CLI。"}])
    assert "进线接触器动作超时" in ps and "LCT" in ps and "CLI" in ps
    bare = main._fault_params([{"cause": "PLC 通信异常", "remedy": "检查 CLI、tUn 与 HRFC；联系 Schneider 代表 and EMC"}])
    assert "CLI" in bare and "tUn" in bare and "HRFC" in bare
    assert "PLC" not in bare and "EMC" not in bare and "and" not in bare


def test_inbox_scan_imports_once_and_detects_series(store):
    store.inbox_dir.mkdir(parents=True, exist_ok=True)
    (store.inbox_dir / "ATV320_编程手册_中文.pdf").write_bytes(blank_pdf())
    (store.inbox_dir / "说明.txt").write_text("ignored", encoding="utf-8")
    resolve = lambda t: "ATV320" if "ATV320" in t.upper() else None  # noqa: E731
    first = store.scan_inbox(resolve, [])
    assert len(first) == 1 and first[0]["ok"] and first[0]["series"] == "ATV320"
    assert store.scan_inbox(resolve, []) == first or store.inbox_status["last"]
    docs = store.list_docs()
    assert len(docs) == 1 and docs[0]["series"] == "ATV320" and docs[0]["kind"] == "manual"


def test_inbox_catalog_name_gives_title(store):
    store.inbox_dir.mkdir(parents=True, exist_ok=True)
    (store.inbox_dir / "1755859.pdf").write_bytes(blank_pdf())
    cat = [{"series": "ATV71", "title": "ATV71 编程手册（中文）1755859", "url": "https://download.se.com/doc/1755859/1755859.pdf"}]
    res = store.scan_inbox(lambda t: None, cat)
    assert res[0]["series"] == "ATV71" and res[0]["title"].startswith("ATV71")


def test_search_test_endpoint():
    with TestClient(main.app) as c:
        r = c.post("/api/admin/search-test", headers=H, data={"code": "OCF", "series": "ATV320"})
        assert r.status_code == 200
        j = r.json()
        assert j["codes"] == ["OCF"] and j["series"] == "ATV320" and "hits" in j and j["params"]
        assert c.post("/api/admin/search-test", data={"code": "OCF"}).status_code == 401
