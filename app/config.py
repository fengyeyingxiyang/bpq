"""Runtime configuration, read from environment variables (.env via docker compose)."""
from __future__ import annotations

import os


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _provider() -> str:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


class Settings:
    def __init__(self) -> None:
        self.data_dir = os.getenv("DATA_DIR", "data")
        self.provider = _provider()  # none | anthropic | openai | ollama
        self.model = os.getenv("LLM_MODEL", "")
        self.vision = _bool("LLM_VISION", True)
        self.timeout = float(os.getenv("LLM_TIMEOUT", "120"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1200"))

        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.ollama_base = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")

        self.max_image_mb = float(os.getenv("MAX_IMAGE_MB", "10"))
        self.rate_limit_per_min = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
        self.trust_proxy = _bool("TRUST_PROXY", False)

    def default_model(self) -> str:
        if self.model:
            return self.model
        return {
            "anthropic": "claude-sonnet-5-5",
            "openai": "gpt-4o",
            "ollama": "qwen2.5vl:7b",
        }.get(self.provider, "")
