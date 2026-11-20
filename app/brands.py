"""Brand and drive-family identification shared by search, upload and admin flows.

Identification is deliberately conservative: a brand/model is returned only when an
explicit alias or model-family token appears in the supplied text. It never guesses
from a fault code alone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_BRANDS: list[dict[str, Any]] = [
    {
        "id": "schneider", "name": "施耐德电气", "aliases": ["Schneider", "Schneider Electric", "施耐德"],
        "families": [
            {"id": "ATV12", "aliases": ["ATV12"]},
            {"id": "ATV312", "aliases": ["ATV312"]},
            {"id": "ATV320", "aliases": ["ATV320"]},
            {"id": "ATV340", "aliases": ["ATV340"]},
            {"id": "ATV600", "aliases": ["ATV600", "ATV630", "ATV650", "ATV660", "ATV680"]},
            {"id": "ATV900", "aliases": ["ATV900", "ATV930", "ATV950", "ATV960", "ATV980", "ATV993"]},
            {"id": "ATV61", "aliases": ["ATV61"]},
            {"id": "ATV610", "aliases": ["ATV610"]},
            {"id": "ATV71", "aliases": ["ATV71"]},
        ],
    },
    {
        "id": "abb", "name": "ABB", "aliases": ["ABB"],
        "families": [{"id": x, "aliases": [x]} for x in
                     ["ACS100", "ACS150", "ACS180", "ACS310", "ACS355", "ACS380", "ACS480",
                      "ACS510", "ACS550", "ACS580", "ACS800", "ACS880", "ACQ580", "ACH580"]],
    },
    {
        "id": "siemens", "name": "西门子", "aliases": ["Siemens", "西门子"],
        "families": [{"id": x, "aliases": [x]} for x in
                     ["SINAMICS V20", "SINAMICS G120", "SINAMICS G120C", "SINAMICS G120X",
                      "SINAMICS G120P", "SINAMICS G120D", "SINAMICS S120", "SINAMICS G130",
                      "SINAMICS G150", "MASTERDRIVES"]],
    },
    {
        "id": "danfoss", "name": "丹佛斯", "aliases": ["Danfoss", "丹佛斯"],
        "families": [{"id": x, "aliases": [x]} for x in
                     ["VLT FC51", "VLT FC101", "VLT FC102", "VLT FC202", "VLT FC301",
                      "VLT FC302", "VLT FC360", "VLT FC280"]],
    },
    {
        "id": "invt", "name": "英威腾", "aliases": ["INVT", "英威腾"],
        "families": [{"id": x, "aliases": [x]} for x in
                     ["GD10", "GD20", "GD200A", "GD300", "GD3000", "GD350", "GD600",
                      "CHF100A", "CHE100"]],
    },
    {
        "id": "inovance", "name": "汇川技术", "aliases": ["Inovance", "汇川", "汇川技术"],
        "families": [{"id": x, "aliases": [x]} for x in
                     ["MD200", "MD290", "MD310", "MD320", "MD500", "MD520", "MD600", "MD800"]],
    },
]


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


class BrandRegistry:
    def __init__(self, brands: list[dict[str, Any]] | None = None):
        self.brands = brands if brands is not None else DEFAULT_BRANDS
        self._families: list[tuple[str, str, str]] = []
        self._brand_aliases: list[tuple[str, str]] = []
        self._brand_names = {b["id"]: b["name"] for b in self.brands}
        for brand in self.brands:
            for alias in [brand["id"], brand["name"], *brand.get("aliases", [])]:
                n = _normalise(alias)
                if n:
                    self._brand_aliases.append((n, brand["id"]))
            for family in brand.get("families", []):
                for alias in [family["id"], *family.get("aliases", [])]:
                    n = _normalise(alias)
                    if n:
                        self._families.append((n, brand["id"], family["id"]))
        # Longest aliases first: e.g. ATV610 before ATV61, G120C before G120.
        self._families.sort(key=lambda item: len(item[0]), reverse=True)
        self._brand_aliases.sort(key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def load(cls, path: str | Path) -> "BrandRegistry":
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("brand registry must be a JSON list")
            return cls(data)
        except FileNotFoundError:
            return cls()
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid brand registry {p}: {exc}") from exc

    def identify(self, text: str) -> dict[str, str] | None:
        """Return {brand, brand_name, series} for an explicit model/family match."""
        raw = text or ""
        n = _normalise(raw)
        if not n:
            return None
        for alias, brand_id, family_id in self._families:
            if alias in n:
                return {"brand": brand_id, "brand_name": self._brand_names[brand_id], "series": family_id}
        # Brand-only identification is useful for filtering upload queues, but not a model.
        for alias, brand_id in self._brand_aliases:
            if alias in n:
                return {"brand": brand_id, "brand_name": self._brand_names[brand_id], "series": ""}
        return None

    def list_brands(self) -> list[dict[str, Any]]:
        return [
            {"id": b["id"], "name": b["name"],
             "families": [f["id"] for f in b.get("families", [])]}
            for b in self.brands
        ]
