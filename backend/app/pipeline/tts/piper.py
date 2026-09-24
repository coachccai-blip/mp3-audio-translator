"""Piper (voix VITS enregistrées par des locuteurs natifs) : gratuit, calculé sur votre ordinateur.

Voix : https://huggingface.co/rhasspy/piper-voices (licence propre à chaque voix, voir son MODEL_CARD).
Couvre notamment l'allemand, le polonais et le suédois, absents de Kokoro.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ...config import get_settings
from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider, native_voice_name

_lock = threading.Lock()
_voices: dict[str, object] = {}


def voices_dir() -> Path:
    return get_settings().models_dir / "piper"


def available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def download_voice(name: str) -> None:
    from piper.download_voices import download_voice as dl

    d = voices_dir()
    d.mkdir(parents=True, exist_ok=True)
    dl(name, d)


def _load(name: str):
    if name not in _voices:
        from piper import PiperVoice

        path = voices_dir() / f"{name}.onnx"
        if not path.exists():
            download_voice(name)
        _voices[name] = PiperVoice.load(str(path))
    return _voices[name]


class PiperTTS(TTSProvider):
    name = "piper"

    def __init__(self):
        if not available():
            raise TTSError("Piper n'est pas installé (pip install piper-tts).")

    def list_voices(self, locale: str) -> list[ProviderVoice]:
        from ...services.catalog import get_catalog

        return [ProviderVoice(v.id, locale, v.display_name, v.gender)
                for v in get_catalog().voices.get(locale, []) if v.provider == self.name]

    def synthesize(self, text, voice_id, rate=1.0, target_duration_ms=None) -> AudioSegment:
        from piper.config import SynthesisConfig

        name = native_voice_name(voice_id)
        try:
            with _lock:
                voice = _load(name)
                chunks = list(voice.synthesize(text, SynthesisConfig(length_scale=1.0 / max(rate, 0.1))))
        except Exception as exc:
            raise TTSError(f"Piper : {exc}") from exc
        if not chunks:
            raise TTSError("Piper n'a produit aucun son.")
        audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        return AudioSegment(audio[:, None], int(chunks[0].sample_rate))
