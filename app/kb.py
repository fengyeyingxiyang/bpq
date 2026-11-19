"""Fault-code knowledge base: loads *.psv files and looks codes up."""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("kb")

# How the drive clears this fault (shown to the user, Chinese labels).
RESET_LABELS = {
    "power": "需排除原因后断电重启，不能自动复位",
    "auto": "排除原因后可复位，或开启自动重启功能",
    "rsf": "排除原因后需用复位输入/按键复位，不支持自动重启",
    "hrfc": "需开启扩展故障复位后才能复位",
    "self": "原因消除后自动清除",
    "": "",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,5}(?:\.[A-Za-z])?")


def norm(code: str) -> str:
    """Normalize a code for lookup: lower case, drop spaces/dashes/dots."""
    return re.sub(r"[\s\-_.]", "", code).lower()


@dataclass
class Entry:
    series: str
    code: str
    name: str
    cause: str
    remedy: str
    reset: str
    source: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reset_label"] = RESET_LABELS.get(self.reset, "")
        return d


class KnowledgeBase:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.series: dict[str, dict] = {}
        self.entries: list[Entry] = []
        self._index: dict[str, list[Entry]] = {}
        self._alias: dict[str, str] = {}
        self.load()

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        self.series, self.entries, self._index, self._alias = {}, [], {}, {}
        for path in sorted(self.data_dir.glob("*.psv")):
            self._load_file(path)
        log.info("knowledge base: %d series, %d entries", len(self.series), len(self.entries))

    def _load_file(self, path: Path) -> None:
        meta: dict[str, str] = {}
        rows: list[list[str]] = []
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                key, _, value = line[1:].partition(":")
                meta[key.strip().lower()] = value.strip()
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 5:
                log.warning("%s:%d skipped (expected 5 fields)", path.name, lineno)
                continue
            rows.append(parts)

        series_id = meta.get("series", path.stem).upper()
        info = {
            "id": series_id,
            "title": meta.get("title", series_id),
            "source": meta.get("source", ""),
            "count": 0,
        }
        self.series[series_id] = info
        self._alias[norm(series_id)] = series_id
        for alias in meta.get("aliases", "").split(","):
            if alias.strip():
                self._alias[norm(alias)] = series_id

        for code_field, name, cause, remedy, reset in rows:
            for code in code_field.split("/"):
                code = code.strip()
                if not code:
                    continue
                entry = Entry(series_id, code, name, cause, remedy, reset, info["source"])
                self.entries.append(entry)
                self._index.setdefault(norm(code), []).append(entry)
                info["count"] += 1

    # ---------------------------------------------------------------- series
    def resolve_series(self, text: str) -> str | None:
        """Map user text such as 'atv630' or 'ATV 12' to a series id."""
        n = norm(text or "")
        if not n:
            return None
        if n in self._alias:
            return self._alias[n]
        for alias, sid in self._alias.items():
            if alias in n:
                return sid
        return None

    def series_list(self) -> list[dict]:
        return [dict(s) for s in self.series.values()]

    # ---------------------------------------------------------------- lookup
    def lookup(self, code: str, series: str | None = None) -> list[Entry]:
        found = self._index.get(norm(code), [])
        if series:
            hit = [e for e in found if e.series == series]
            if hit:
                return hit
        return list(found)

    def extract_codes(self, text: str) -> tuple[list[str], list[str]]:
        """Find fault codes in free text.

        Returns (exact_codes, approximate_codes); approximate ones are fuzzy
        matches of tokens that are not codes themselves (e.g. a typo).
        """
        exact: list[str] = []
        approx: list[str] = []
        seen: set[str] = set()
        for token in _TOKEN_RE.findall(text or ""):
            n = norm(token)
            if n in seen:
                continue
            seen.add(n)
            if n in self._index:
                exact.append(self._index[n][0].code)
        if not exact:
            keys = list(self._index)
            for token in _TOKEN_RE.findall(text or ""):
                n = norm(token)
                if len(n) < 3:
                    continue
                close = difflib.get_close_matches(n, keys, n=1, cutoff=0.8)
                if close and close[0] not in seen:
                    seen.add(close[0])
                    approx.append(self._index[close[0]][0].code)
        return exact, approx

    def search_text(self, query: str, series: str | None = None, limit: int = 5) -> list[Entry]:
        """Very small keyword search over name/cause/remedy (English words)."""
        words = [w for w in re.findall(r"[a-z]{3,}", (query or "").lower())]
        if not words:
            return []
        scored: list[tuple[int, Entry]] = []
        for e in self.entries:
            if series and e.series != series:
                continue
            hay = f"{e.name} {e.cause} {e.remedy}".lower()
            score = sum(1 for w in words if w in hay)
            if score:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]
