"""Configuration de l'application (variables d'environnement + fichier .env)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
ENV_FILE = ROOT_DIR / ".env"

SECRET_KEYS = (
    "ANTHROPIC_API_KEY",
    "AZURE_SPEECH_KEY",
    "ELEVENLABS_API_KEY",
    "HF_TOKEN",
)


def read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ('"', "'") and value[:1] in value[1:]:
            value = value[1: value.index(value[0], 1)]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip() if not value.startswith("#") else ""
        values[key.strip()] = value
    return values


def write_env_values(updates: dict[str, str], path: Path = ENV_FILE) -> None:
    """Met à jour (ou ajoute) des clés dans .env sans toucher aux autres lignes."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in remaining.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for k, v in updates.items():
        os.environ[k] = v


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_get("DOUBLR_DATA_DIR", str(ROOT_DIR / "data"))))
    output_dir: Path = field(default_factory=lambda: Path(_get("DOUBLR_OUTPUT_DIR", str(ROOT_DIR / "exports"))))
    # Voix : fournisseur privilégié pour les voix par défaut (auto = meilleure voix disponible).
    tts_provider: str = field(default_factory=lambda: _get("DOUBLR_TTS_PROVIDER", "auto"))
    # Traduction : local (gratuit, Ollama), claude (clé Anthropic) ou auto (Claude si une clé existe).
    translator: str = field(default_factory=lambda: _get("DOUBLR_TRANSLATOR", "auto"))
    local_llm: str = field(default_factory=lambda: _get("DOUBLR_LOCAL_LLM", "gemma3:4b"))
    ollama_url: str = field(default_factory=lambda: _get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    models_dir: Path = field(default_factory=lambda: Path(_get("DOUBLR_MODELS_DIR", str(ROOT_DIR / "data" / "models"))))
    azure_region: str = field(default_factory=lambda: _get("AZURE_SPEECH_REGION", "westeurope"))
    claude_model: str = field(default_factory=lambda: _get("DOUBLR_CLAUDE_MODEL", "claude-opus-5"))
    whisper_model: str = field(default_factory=lambda: _get("DOUBLR_WHISPER_MODEL", "large-v3"))
    device: str = field(default_factory=lambda: _get("DOUBLR_DEVICE", "auto"))
    tts_concurrency: int = field(default_factory=lambda: int(_get("DOUBLR_TTS_CONCURRENCY", "4")))
    file_concurrency: int = field(default_factory=lambda: int(_get("DOUBLR_FILE_CONCURRENCY", "2")))
    require_validated_voices: bool = field(default_factory=lambda: _bool("DOUBLR_REQUIRE_VALIDATED_VOICES", False))
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in _get(
                "DOUBLR_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173,https://coachccai-blip.github.io",
            ).split(",")
            if o.strip()
        ]
    )

    def has_key(self, name: str) -> bool:
        return bool(_get(name))

    @property
    def translator_engine(self) -> str:
        if self.translator in ("local", "claude", "claude-code"):
            return self.translator
        return "claude" if self.has_key("ANTHROPIC_API_KEY") else "local"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'doublr.db'}"


def load_env() -> None:
    for key, value in read_env_file().items():
        os.environ.setdefault(key, value)


load_env()
settings = Settings()


def reload_settings() -> Settings:
    global settings
    settings = Settings()
    return settings


def get_settings() -> Settings:
    return settings
