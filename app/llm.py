"""Thin LLM client: Anthropic, OpenAI-compatible (OpenAI, Qwen/DashScope, DeepSeek...) or local Ollama."""
from __future__ import annotations

import base64
import json
import re

import httpx

from .config import Settings


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings
        self.provider = settings.provider
        self.model = settings.default_model()

    @property
    def enabled(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.s.anthropic_key)
        if self.provider == "openai":
            return bool(self.s.openai_key)
        return self.provider == "ollama"

    @property
    def can_see(self) -> bool:
        return self.enabled and self.s.vision

    # ------------------------------------------------------------------ chat
    async def chat(
        self,
        system: str,
        user_text: str,
        image: bytes | None = None,
        image_mime: str = "image/jpeg",
        max_tokens: int | None = None,
    ) -> str:
        if not self.enabled:
            raise LLMError("LLM not configured")
        max_tokens = max_tokens or self.s.max_tokens
        try:
            async with httpx.AsyncClient(timeout=self.s.timeout) as client:
                if self.provider == "anthropic":
                    return await self._anthropic(client, system, user_text, image, image_mime, max_tokens)
                if self.provider == "openai":
                    return await self._openai(client, system, user_text, image, image_mime, max_tokens)
                if self.provider == "ollama":
                    return await self._ollama(client, system, user_text, image, max_tokens)
        except httpx.HTTPError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        raise LLMError(f"unknown provider {self.provider!r}")

    async def _anthropic(self, client, system, user_text, image, mime, max_tokens) -> str:
        content: list[dict] = []
        if image:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(image).decode()},
            })
        content.append({"type": "text", "text": user_text})
        r = await client.post(
            f"{self.s.anthropic_base}/v1/messages",
            headers={
                "x-api-key": self.s.anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": content}],
            },
        )
        _raise_for_status(r)
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()

    async def _openai(self, client, system, user_text, image, mime, max_tokens) -> str:
        if image:
            b64 = base64.b64encode(image).decode()
            user_content: list[dict] | str = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]
        else:
            user_content = user_text
        r = await client.post(
            f"{self.s.openai_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.s.openai_key}"},
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        _raise_for_status(r)
        return (r.json()["choices"][0]["message"].get("content") or "").strip()

    async def _ollama(self, client, system, user_text, image, max_tokens) -> str:
        msg: dict = {"role": "user", "content": user_text}
        if image:
            msg["images"] = [base64.b64encode(image).decode()]
        r = await client.post(
            f"{self.s.ollama_base}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "options": {"num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, msg],
            },
        )
        _raise_for_status(r)
        return (r.json().get("message", {}).get("content") or "").strip()


def _raise_for_status(r: httpx.Response) -> None:
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")


def parse_json_object(text: str) -> dict:
    """Pull the first {...} object out of a model reply (tolerates code fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}
