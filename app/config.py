"""Runtime configuration, read from environment variables (.env via docker compose)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # running as a PyInstaller binary
# Folder holding the binary (user-editable data/.env live here); otherwise the cwd.
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path.cwd()
# Folder with files bundled inside the binary.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def load_dotenv() -> None:
    """Minimal .env loader for the standalone binary (Docker passes env vars itself)."""
    for path in (APP_DIR / ".env", Path.cwd() / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def _default_data_dir() -> str:
    if os.getenv("DATA_DIR"):
        return os.environ["DATA_DIR"]
    if FROZEN:
        external = APP_DIR / "data"
        return str(external if external.is_dir() else BUNDLE_DIR / "data")
    return "data"


def _default_local_dir() -> str:
    if os.getenv("LOCAL_DIR"):
        return os.environ["LOCAL_DIR"]
    return str(APP_DIR / "local") if FROZEN else "local"


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
        if FROZEN:
            load_dotenv()
        self.data_dir = _default_data_dir()
        self.local_dir = _default_local_dir()  # writable: admin-entered knowledge
        self.admin_token = os.getenv("ADMIN_TOKEN", "").strip()  # empty = admin features disabled
        self.max_upload_mb = float(os.getenv("MAX_UPLOAD_MB", "60"))
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
