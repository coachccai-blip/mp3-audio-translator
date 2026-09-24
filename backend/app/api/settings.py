"""Routes : réglages, clés API (jamais renvoyées au frontend), cache."""
from __future__ import annotations

import os
import shutil

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config
from ..config import SECRET_KEYS, get_settings, write_env_values
from ..pipeline.diarize import pyannote_available
from ..pipeline.separate import demucs_available
from ..pipeline.transcribe import whisper_available
from ..pipeline.translate import ollama_status
from ..pipeline.tts import provider_available
from ..services import engines
from .projects import missing_requirements
from ..services.catalog import get_catalog

router = APIRouter(prefix="/api")

EDITABLE = {"DOUBLR_TTS_PROVIDER", "DOUBLR_TRANSLATOR", "DOUBLR_LOCAL_LLM", "DOUBLR_WHISPER_MODEL", "DOUBLR_DEVICE", "AZURE_SPEECH_REGION",
            "DOUBLR_OUTPUT_DIR", "DOUBLR_CLAUDE_MODEL", "DOUBLR_TTS_CONCURRENCY"}


def _dir_size(path) -> int:
    total = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    return total


@router.get("/settings")
def get_settings_route():
    s = get_settings()
    return {
        "keys": {k: bool(os.environ.get(k)) for k in SECRET_KEYS},
        "tts_provider": s.tts_provider, "whisper_model": s.whisper_model, "device": s.device,
        "azure_region": s.azure_region, "claude_model": s.claude_model, "output_dir": str(s.output_dir),
        "data_dir": str(s.data_dir), "cache_bytes": _dir_size(s.data_dir / "projects"),
        "require_validated_voices": s.require_validated_voices,
        "capabilities": {"whisper": whisper_available(), "demucs": demucs_available(), "pyannote": pyannote_available(),
                         "kokoro": provider_available("kokoro"), "piper": provider_available("piper")},
        "translator": s.translator, "translator_engine": s.translator_engine, "local_llm": s.local_llm,
        "ollama": ollama_status(), "missing": missing_requirements(),
    }


class SettingsBody(BaseModel):
    keys: dict[str, str] | None = None
    values: dict[str, str] | None = None


@router.put("/settings")
def put_settings(body: SettingsBody):
    updates = {}
    for k, v in (body.keys or {}).items():
        if k in SECRET_KEYS and v:
            updates[k] = v.strip()
    for k, v in (body.values or {}).items():
        if k in EDITABLE:
            updates[k] = str(v)
    if updates:
        write_env_values(updates)
        config.reload_settings()
        engines.set_engines(None)
        get_catalog.cache_clear()
    return get_settings_route()


@router.post("/settings/test/{service}")
def test_connection(service: str):
    try:
        if service == "anthropic":
            import anthropic

            anthropic.Anthropic().models.retrieve(get_settings().claude_model)
        elif service == "azure":
            r = httpx.get(f"https://{get_settings().azure_region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                          headers={"Ocp-Apim-Subscription-Key": os.environ.get("AZURE_SPEECH_KEY", "")}, timeout=15)
            r.raise_for_status()
        elif service == "elevenlabs":
            r = httpx.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", "")},
                          timeout=15)
            r.raise_for_status()
        elif service == "huggingface":
            r = httpx.get("https://huggingface.co/api/whoami-v2",
                          headers={"Authorization": f"Bearer {os.environ.get('HF_TOKEN', '')}"}, timeout=15)
            r.raise_for_status()
        else:
            raise HTTPException(404, "Service inconnu")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}
    return {"ok": True}


@router.delete("/cache")
def clear_cache():
    """Vide les caches intermédiaires (les originaux et les exports sont conservés)."""
    root = get_settings().data_dir / "projects"
    freed = 0
    for d in root.glob("*/files/*/*"):
        if d.is_dir() and d.name not in ("separate",):
            for cache in d.glob("cache"):
                freed += _dir_size(cache)
                shutil.rmtree(cache, ignore_errors=True)
    samples = get_settings().data_dir / "voice_samples"
    freed += _dir_size(samples)
    shutil.rmtree(samples, ignore_errors=True)
    return {"freed_bytes": freed}
