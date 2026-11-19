"""Expert layer: general troubleshooting know-how (fault families) kept outside the LLM.

A small local model knows little about drives, so the program classifies each query into
fault families (by code, by the wording of the manual entry, by the symptom the user
describes) and hands the model a ranked checklist to follow, instead of hoping it knows one.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .kb import norm

log = logging.getLogger("expert")


class Expert:
    def __init__(self, data_dir: str | Path):
        self.families: dict[str, dict] = {}
        self._code_map: dict[str, str] = {}
        self._symptoms: list[dict] = []
        path = Path(data_dir) / "expert" / "families.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("expert knowledge not loaded (%s): %s", path, exc)
            return
        for fam in doc.get("families", []):
            self.families[fam["id"]] = fam
            for c in fam.get("codes", []):
                self._code_map.setdefault(norm(c), fam["id"])
        self._symptoms = doc.get("symptoms", [])
        log.info("expert knowledge: %d fault families", len(self.families))

    # --------------------------------------------------------------- classify
    def classify(self, codes: list[str], entries: list[dict], text: str = "", limit: int = 2) -> list[dict]:
        """Rank fault families for the query; returns the family dicts (best first)."""
        score: dict[str, float] = {}

        def add(fid: str, w: float) -> None:
            if fid in self.families:
                score[fid] = score.get(fid, 0.0) + w

        for c in codes:
            fid = self._code_map.get(norm(c))
            if fid:
                add(fid, 10)
        for e in entries:
            fid = self._code_map.get(norm(e.get("code", "")))
            if fid:
                add(fid, 6)
            hay = f"{e.get('name', '')} {e.get('cause', '')}".lower()
            for fam in self.families.values():
                if any(k.lower() in hay for k in fam.get("keywords", [])):
                    add(fam["id"], 1.5)
        low = (text or "").lower()
        if low:
            for sym in self._symptoms:
                if any(k.lower() in low for k in sym["keywords"]):
                    for i, fid in enumerate(sym["families"]):
                        add(fid, 3 - i * 0.5)
            for fam in self.families.values():
                if any(k.lower() in low for k in fam.get("keywords", [])):
                    add(fam["id"], 2)
        ranked = sorted(score.items(), key=lambda kv: -kv[1])
        return [self.families[fid] for fid, _ in ranked[:limit]]

    # ----------------------------------------------------------------- render
    @staticmethod
    def for_prompt(fams: list[dict], compact: bool = False) -> str:
        """Checklist text for the LLM. compact=True keeps it short for small local models."""
        out = []
        for f in fams:
            causes = f["causes"][:4] if compact else f["causes"]
            lines = [f"【{f['title']}】", f"原理：{f['mechanism']}", "常见原因（按现场出现概率排序）及判断方法："]
            lines += [f"{i}. {c['c']}——{c['tell']}" for i, c in enumerate(causes, 1)]
            lines.append("建议排查顺序：" + "；".join(f"({i}){s}" for i, s in enumerate(f["steps"][:5 if compact else None], 1)))
            lines.append("不要这样做：" + "；".join(f["avoid"]))
            lines.append("遇到这种情况停止并联系厂家：" + f["stop"])
            out.append("\n".join(lines))
        return "\n\n".join(out)

    @staticmethod
    def for_user(fams: list[dict]) -> list[dict]:
        """Structured version for the web page and for the no-LLM answer."""
        return [
            {
                "id": f["id"],
                "title": f["title"],
                "mechanism": f["mechanism"],
                "causes": f["causes"],
                "steps": f["steps"],
                "avoid": f["avoid"],
                "stop": f["stop"],
            }
            for f in fams
        ]


_WORD = re.compile(r"\s+")


def one_line(text: str) -> str:
    return _WORD.sub(" ", text or "").strip()
