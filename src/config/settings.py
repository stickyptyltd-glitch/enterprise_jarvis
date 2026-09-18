"""Environment-driven configuration for the JARVIS business engine."""

import os
from dataclasses import dataclass, field

def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOTENV = os.path.join(_PROJECT_ROOT, ".env")


def _load_dotenv(path: str = _DOTENV) -> None:
    """Minimal .env loader: populates os.environ without overriding real env vars."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def _banner_missing(key: str, hint: str) -> None:
    print(f"\033[91m\u2715 Error: environment variable {key} is not set.\033[0m")
    print(f"    Please run: {hint}")
    raise SystemExit(1)


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("JARVIS_MODEL", "gpt-4o"))
    temperature: float = field(default_factory=lambda: float(os.getenv("JARVIS_TEMPERATURE", "0.1")))
    company_name: str = field(default_factory=lambda: os.getenv("JARVIS_COMPANY", "Acme Industries"))
    data_file: str = field(
        default_factory=lambda: os.getenv(
            "JARVIS_DATA_FILE",
            os.path.join(_PROJECT_ROOT, "data", "jarvis_business.json"),
        )
    )
    autonomy: str = field(default_factory=lambda: os.getenv("JARVIS_AUTONOMY", "none").strip().lower())
    trust_tools: bool = field(default_factory=lambda: _as_bool(os.getenv("JARVIS_TRUST_TOOLS", "0")))

    def require_api_key(self) -> "Settings":
        if not self.openai_api_key:
            _banner_missing("OPENAI_API_KEY", "export OPENAI_API_KEY='your-key'")
        return self

    @classmethod
    def from_env(cls, require_key: bool = True) -> "Settings":
        settings = cls()
        if require_key:
            settings.require_api_key()
        return settings