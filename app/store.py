"""Writable site knowledge kept on disk: custom fault entries, notes, wiring/drawings, PDF manuals.

Layout under the local dir:
  entries.json                    custom fault entries added by the admin
  docs/<id>/meta.json             title, kind, series, codes, text, files[]
  docs/<id>/files/<stored name>   uploaded files (images are re-encoded, PDFs kept as is)
  docs/<id>/pages.json            text extracted from PDFs / text files, one item per page
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from .kb import RESET_LABELS, Entry, norm

KINDS = {
    "wiring": "接线",
    "drawing": "图纸",
    "case": "现场案例",
    "manual": "手册",
    "note": "笔记",
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PDF_EXT = {".pdf"}
TEXT_EXT = {".txt", ".md", ".csv"}
MAX_PDF_PAGES = 2000

_CJK = re.compile(r"[一-鿿]+")
_LATIN = re.compile(r"[a-z0-9]{2,}")


def terms(text: str) -> set[str]:
    """Search terms: CJK character bigrams + latin/number words (no external tokenizer needed)."""
    low = (text or "").lower()
    out: set[str] = set()
    for run in _CJK.findall(low):
        if len(run) == 1:
            out.add(run)
        else:
            out.update(run[i : i + 2] for i in range(len(run) - 1))
    out.update(_LATIN.findall(low))
    return out


def split_codes(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)
    parts = re.split(r"[,，;；、\s]+", raw.strip())
    seen, out = set(), []
    for p in parts:
        p = p.strip()
        if p and norm(p) not in seen:
            seen.add(norm(p))
            out.append(p[:40])
    return out[:20]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem)[:40].strip("._") or "file"
    ext = Path(name).suffix.lower()
    return f"{uuid.uuid4().hex[:8]}_{stem}{ext}"


def _snippet(text: str, patterns: list[re.Pattern], size: int = 700) -> str:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    for rx in patterns:
        m = rx.search(text)
        if m:
            start = max(0, m.start() - size // 2)
            end = min(len(text), start + size)
            s = text[start:end]
            return ("…" if start else "") + s + ("…" if end < len(text) else "")
    return text[:size] + ("…" if len(text) > size else "")


class StoreError(ValueError):
    """Bad input from the admin (message is safe to show)."""


class LocalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "docs").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._entries: list[dict] = []
        self._docs: dict[str, dict] = {}
        self._pages: dict[str, list[dict]] = {}
        self._items: list[dict] = []
        self._df: Counter = Counter()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        with self._lock:
            ep = self.root / "entries.json"
            if ep.is_file():
                try:
                    self._entries = json.loads(ep.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self._entries = []
            self._docs, self._pages = {}, {}
            for meta_path in sorted((self.root / "docs").glob("*/meta.json")):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    self._docs[meta["id"]] = meta
                    pp = meta_path.parent / "pages.json"
                    self._pages[meta["id"]] = json.loads(pp.read_text(encoding="utf-8")) if pp.is_file() else []
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
            self._reindex()

    def _reindex(self) -> None:
        items: list[dict] = []
        for doc_id, doc in self._docs.items():
            head = " ".join(
                [doc["title"], KINDS.get(doc["kind"], ""), doc.get("series", ""), " ".join(doc.get("codes", [])), doc.get("text", "")]
                + [f.get("summary", "") for f in doc.get("files", [])]
            )
            items.append({"doc_id": doc_id, "page": None, "file": None, "text": head, "terms": terms(head)})
            for pg in self._pages.get(doc_id, []):
                items.append({"doc_id": doc_id, "page": pg["page"], "file": pg.get("file"), "text": pg["text"], "terms": terms(pg["text"])})
        self._items = items
        self._df = Counter()
        for it in items:
            self._df.update(it["terms"])

    # --------------------------------------------------------------- entries
    @staticmethod
    def _clean_entry(data: dict) -> dict:
        def s(key: str, limit: int) -> str:
            return str(data.get(key, "") or "").strip()[:limit]

        out = {
            "series": s("series", 40),
            "code": s("code", 80),
            "name": s("name", 200),
            "cause": s("cause", 2000),
            "remedy": s("remedy", 3000),
            "reset": s("reset", 10),
        }
        if not out["code"]:
            raise StoreError("请填写故障代码")
        if not out["series"]:
            raise StoreError("请填写变频器系列（可填新的，如 ABB ACS550）")
        if not (out["name"] or out["cause"] or out["remedy"]):
            raise StoreError("名称、原因、处理办法至少填一项")
        if out["reset"] not in RESET_LABELS:
            out["reset"] = ""
        return out

    def list_entries(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._entries]

    def add_entry(self, data: dict) -> dict:
        with self._lock:
            entry = {"id": uuid.uuid4().hex[:8], **self._clean_entry(data), "created": int(time.time())}
            self._entries.append(entry)
            self._save_entries()
            return dict(entry)

    def update_entry(self, entry_id: str, data: dict) -> dict:
        with self._lock:
            for e in self._entries:
                if e["id"] == entry_id:
                    e.update(self._clean_entry(data))
                    e["updated"] = int(time.time())
                    self._save_entries()
                    return dict(e)
        raise KeyError(entry_id)

    def delete_entry(self, entry_id: str) -> None:
        with self._lock:
            n = len(self._entries)
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            if len(self._entries) == n:
                raise KeyError(entry_id)
            self._save_entries()

    def _save_entries(self) -> None:
        _atomic_write(self.root / "entries.json", json.dumps(self._entries, ensure_ascii=False, indent=1))

    def entry_objects(self) -> list[Entry]:
        """Custom entries as KB entries (a code field like 'A/B' is expanded)."""
        out: list[Entry] = []
        with self._lock:
            for e in self._entries:
                for code in e["code"].split("/"):
                    code = code.strip()
                    if code:
                        out.append(Entry(e["series"], code, e["name"], e["cause"], e["remedy"], e["reset"], "现场录入", e["id"], "local"))
        return out

    # ------------------------------------------------------------------ docs
    def list_docs(self) -> list[dict]:
        with self._lock:
            docs = sorted(self._docs.values(), key=lambda d: -d.get("updated", 0))
            return [self._doc_view(d, brief=True) for d in docs]

    def get_doc(self, doc_id: str) -> dict:
        with self._lock:
            if doc_id not in self._docs:
                raise KeyError(doc_id)
            return self._doc_view(self._docs[doc_id])

    def _doc_view(self, doc: dict, brief: bool = False) -> dict:
        view = {
            "id": doc["id"],
            "title": doc["title"],
            "kind": doc["kind"],
            "kind_label": KINDS.get(doc["kind"], ""),
            "series": doc.get("series", ""),
            "codes": doc.get("codes", []),
            "updated": doc.get("updated", 0),
            "files": [
                {
                    "name": f["name"],
                    "orig": f.get("orig", f["name"]),
                    "type": f["type"],
                    "size": f.get("size", 0),
                    "pages": f.get("pages", 0),
                    "scanned": f.get("scanned", False),
                    "has_summary": bool(f.get("summary")),
                    "url": f"/api/docs/{doc['id']}/files/{f['name']}",
                }
                for f in doc.get("files", [])
            ],
        }
        text = doc.get("text", "")
        view["text"] = (text[:120] + "…") if brief and len(text) > 120 else text
        return view

    def _check_meta(self, title: str, kind: str, text: str) -> tuple[str, str, str]:
        title, text = (title or "").strip()[:100], (text or "").strip()[:20000]
        if not title:
            raise StoreError("请填写标题")
        if kind not in KINDS:
            kind = "note"
        return title, kind, text

    def create_doc(self, title: str, kind: str, series: str, codes, text: str) -> dict:
        title, kind, text = self._check_meta(title, kind, text)
        doc_id = uuid.uuid4().hex[:10]
        now = int(time.time())
        doc = {
            "id": doc_id, "title": title, "kind": kind, "series": (series or "").strip()[:40],
            "codes": split_codes(codes), "text": text, "files": [], "created": now, "updated": now,
        }
        with self._lock:
            (self.root / "docs" / doc_id / "files").mkdir(parents=True, exist_ok=True)
            self._docs[doc_id], self._pages[doc_id] = doc, []
            self._save_doc(doc_id)
            self._reindex()
            return self._doc_view(doc)

    def update_doc(self, doc_id: str, title: str, kind: str, series: str, codes, text: str) -> dict:
        title, kind, text = self._check_meta(title, kind, text)
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                raise KeyError(doc_id)
            doc.update(title=title, kind=kind, series=(series or "").strip()[:40], codes=split_codes(codes), text=text, updated=int(time.time()))
            self._save_doc(doc_id)
            self._reindex()
            return self._doc_view(doc)

    def delete_doc(self, doc_id: str) -> None:
        with self._lock:
            if doc_id not in self._docs:
                raise KeyError(doc_id)
            shutil.rmtree(self.root / "docs" / doc_id, ignore_errors=True)
            self._docs.pop(doc_id, None)
            self._pages.pop(doc_id, None)
            self._reindex()

    def _save_doc(self, doc_id: str) -> None:
        base = self.root / "docs" / doc_id
        _atomic_write(base / "meta.json", json.dumps(self._docs[doc_id], ensure_ascii=False, indent=1))
        _atomic_write(base / "pages.json", json.dumps(self._pages.get(doc_id, []), ensure_ascii=False))

    # ----------------------------------------------------------------- files
    def add_file(self, doc_id: str, orig_name: str, data: bytes, summary: str = "") -> dict:
        ext = Path(orig_name).suffix.lower()
        if ext not in IMAGE_EXT | PDF_EXT | TEXT_EXT:
            raise StoreError(f"不支持的文件类型 {ext or '(无扩展名)'}：只能上传图片、PDF、txt/md/csv")
        if not data:
            raise StoreError("文件是空的")
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                raise KeyError(doc_id)
            if len(doc["files"]) >= 30:
                raise StoreError("单条资料最多 30 个附件")

        info: dict = {"orig": Path(orig_name).name[:120], "size": len(data)}
        pages: list[dict] = []
        if ext in IMAGE_EXT:
            data, ext = self._reencode_image(data)
            info.update(type="image", size=len(data), summary=(summary or "").strip()[:6000])
        elif ext in PDF_EXT:
            pages = self._extract_pdf(data)
            chars = sum(len(p["text"]) for p in pages)
            info.update(type="pdf", pages=len(pages), scanned=bool(pages) and chars < 30 * len(pages))
        else:
            text = data.decode("utf-8", errors="replace")
            pages = [{"page": 1, "text": text[:200000]}]
            info.update(type="text")

        name = _safe_name(orig_name)
        name = Path(name).stem + ext
        info["name"] = name
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                raise KeyError(doc_id)
            fdir = self.root / "docs" / doc_id / "files"
            fdir.mkdir(parents=True, exist_ok=True)
            (fdir / name).write_bytes(data)
            doc["files"].append(info)
            for p in pages:
                self._pages[doc_id].append({"page": p["page"], "file": name, "text": p["text"]})
            doc["updated"] = int(time.time())
            self._save_doc(doc_id)
            self._reindex()
            return dict(info)

    @staticmethod
    def _reencode_image(data: bytes) -> tuple[bytes, str]:
        try:
            from PIL import Image, ImageOps

            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((2400, 2400))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=88)
            return out.getvalue(), ".jpg"
        except Exception as exc:
            raise StoreError("无法识别这张图片，请换 JPG/PNG 格式") from exc

    @staticmethod
    def _extract_pdf(data: bytes) -> list[dict]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = []
            for i, page in enumerate(reader.pages[:MAX_PDF_PAGES], 1):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                pages.append({"page": i, "text": text.strip()})
            return pages
        except Exception as exc:
            raise StoreError("无法读取这个 PDF（可能已加密或损坏）") from exc

    def set_file_summary(self, doc_id: str, name: str, summary: str) -> None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                raise KeyError(doc_id)
            for f in doc["files"]:
                if f["name"] == name:
                    f["summary"] = summary.strip()[:6000]
                    self._save_doc(doc_id)
                    self._reindex()
                    return
        raise KeyError(name)

    def remove_file(self, doc_id: str, name: str) -> None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if not doc:
                raise KeyError(doc_id)
            keep = [f for f in doc["files"] if f["name"] != name]
            if len(keep) == len(doc["files"]):
                raise KeyError(name)
            doc["files"] = keep
            self._pages[doc_id] = [p for p in self._pages.get(doc_id, []) if p.get("file") != name]
            try:
                (self.root / "docs" / doc_id / "files" / name).unlink()
            except OSError:
                pass
            doc["updated"] = int(time.time())
            self._save_doc(doc_id)
            self._reindex()

    def file_path(self, doc_id: str, name: str) -> tuple[Path, str]:
        """Path + media type of a stored file; looked up in the metadata, never built from user input."""
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc:
                for f in doc["files"]:
                    if f["name"] == name:
                        ext = Path(name).suffix.lower()
                        media = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8"}.get(ext, "image/jpeg")
                        return self.root / "docs" / doc_id / "files" / name, media
        raise KeyError(name)

    # ---------------------------------------------------------------- search
    def search(self, codes: list[str], text: str, series: str | None = None, limit: int = 5) -> list[dict]:
        with self._lock:
            if not self._docs:
                return []
            rxs = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?![A-Za-z0-9])", re.I) for c in codes if c]
            ncodes = {norm(c) for c in codes if c}
            qterms = terms(text)
            n_items = max(1, len(self._items))
            idf = {t: math.log(1 + n_items / (1 + self._df.get(t, 0))) for t in qterms}
            total_w = sum(idf.values()) or 1.0

            best: dict[tuple[str, object], tuple[float, dict]] = {}
            for it in self._items:
                doc = self._docs[it["doc_id"]]
                if series and doc.get("series") and norm(doc["series"]) != norm(series):
                    continue
                score = 0.0
                hits = [rx for rx in rxs if rx.search(it["text"])]
                for rx in hits:
                    score += 10 + min(len(rx.findall(it["text"])), 5)
                if it["page"] is None and ncodes & {norm(c) for c in doc.get("codes", [])}:
                    score += 20
                overlap = [t for t in qterms if t in it["terms"]]
                if len(overlap) >= 2:
                    ratio = sum(idf[t] for t in overlap) / total_w
                    if ratio >= 0.3:
                        score += ratio * 8
                if score <= 0:
                    continue
                key = (it["doc_id"], it["page"] if it["page"] is not None else "doc")
                best[key] = (score, {"item": it, "hits": hits})

            # keep the two best items per document, then the best documents
            per_doc: dict[str, list] = {}
            for (doc_id, _), (score, payload) in best.items():
                per_doc.setdefault(doc_id, []).append((score, payload))
            results: list[dict] = []
            for doc_id, lst in per_doc.items():
                lst.sort(key=lambda x: -x[0])
                for score, payload in lst[:2]:
                    doc, it = self._docs[doc_id], payload["item"]
                    results.append({
                        "doc_id": doc_id,
                        "title": doc["title"],
                        "kind": doc["kind"],
                        "kind_label": KINDS.get(doc["kind"], ""),
                        "series": doc.get("series", ""),
                        "page": it["page"],
                        "file": it["file"],
                        "score": round(score, 2),
                        "snippet": _snippet(it["text"], payload["hits"]),
                        "files": [
                            {"name": f["name"], "orig": f.get("orig", f["name"]), "type": f["type"],
                             "url": f"/api/docs/{doc_id}/files/{f['name']}"}
                            for f in doc["files"]
                            if f["type"] == "image" or f["name"] == it["file"]
                        ][:6],
                    })
            results.sort(key=lambda r: -r["score"])
            return results[:limit]

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._entries),
                "docs": len(self._docs),
                "pages": sum(len(p) for p in self._pages.values()),
            }

    # ---------------------------------------------------------------- backup
    def export_zip(self, dest: Path) -> None:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            with self._lock:
                for p in self.root.rglob("*"):
                    if p.is_file() and not p.name.endswith(".tmp"):
                        z.write(p, p.relative_to(self.root))
