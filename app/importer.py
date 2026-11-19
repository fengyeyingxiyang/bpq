"""Download official manuals (PDF) from an allow-listed vendor domain and index them in the local store."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger("importer")

ALLOWED_HOSTS = {"download.se.com", "download.schneider-electric.com", "www.se.com", "www.schneider-electric.cn", "www.schneider-electric.com"}


class ImportError_(ValueError):
    pass


def check_url(url: str) -> str:
    u = urlparse((url or "").strip())
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS or u.username or u.password:
        raise ImportError_("只允许从施耐德官方站点（download.se.com 等）的 https 链接导入")
    if u.port not in (None, 443):
        raise ImportError_("不允许使用非标准端口")
    return u.geturl()


async def fetch_pdf(url: str, max_bytes: int, timeout: float = 120) -> bytes:
    """Stream the PDF; redirects are followed by hand so every hop stays on the allow-list."""
    url = check_url(url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20), follow_redirects=False) as client:
        for _ in range(5):
            async with client.stream("GET", url, headers={"User-Agent": "Mozilla/5.0 fault-assistant"}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = check_url(urljoin(url, r.headers.get("location", "")))
                    continue
                if r.status_code != 200:
                    raise ImportError_(f"下载失败：HTTP {r.status_code}")
                if int(r.headers.get("content-length") or 0) > max_bytes:
                    raise ImportError_(f"文件太大（上限 {max_bytes // 1048576} MB）")
                buf = bytearray()
                async for chunk in r.aiter_bytes(1 << 20):
                    buf += chunk
                    if len(buf) > max_bytes:
                        raise ImportError_(f"文件太大（上限 {max_bytes // 1048576} MB）")
                if not buf.startswith(b"%PDF"):
                    raise ImportError_("下载到的不是 PDF 文件")
                return bytes(buf)
    raise ImportError_("重定向次数过多")


class Jobs:
    """Tiny in-memory job table so the admin page can poll a long import."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def start(self, title: str) -> str:
        jid = uuid.uuid4().hex[:8]
        self.items[jid] = {"id": jid, "title": title, "state": "running", "message": "下载中…", "t": time.time()}
        for k in sorted(self.items, key=lambda k: self.items[k]["t"])[:-30]:
            self.items.pop(k, None)
        return jid

    def done(self, jid: str, ok: bool, message: str) -> None:
        if jid in self.items:
            self.items[jid].update(state="done" if ok else "error", message=message)

    def list(self) -> list[dict]:
        return sorted(self.items.values(), key=lambda j: -j["t"])


jobs = Jobs()
_busy = asyncio.Semaphore(1)  # one import at a time keeps memory use bounded


async def run_import(store, jid: str, url: str, title: str, series: str, max_bytes: int) -> None:
    async with _busy:
        try:
            data = await fetch_pdf(url, max_bytes)
            jobs.items[jid]["message"] = "读取文字、建立索引中…"
            fname = (urlparse(url).path.rsplit("/", 1)[-1] or "manual.pdf")
            doc = await asyncio.to_thread(store.create_doc, title, "manual", series, "", f"官方手册，来源：{url}")
            try:
                info = await asyncio.to_thread(store.add_file, doc["id"], fname, data)
            except Exception:
                await asyncio.to_thread(store.delete_doc, doc["id"])
                raise
            if info.get("scanned"):
                msg = "已导入，但这是扫描版，没有可检索文字"
            else:
                msg = f"已导入，共 {info.get('pages', 0)} 页可检索"
            jobs.done(jid, True, msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("import failed: %s", exc)
            jobs.done(jid, False, str(exc) if isinstance(exc, (ImportError_, ValueError)) else "导入失败：" + exc.__class__.__name__)
