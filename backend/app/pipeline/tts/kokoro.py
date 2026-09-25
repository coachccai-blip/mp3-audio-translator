"""Kokoro-82M (licence Apache 2.0) : voix HD 24 kHz, gratuites, calculées sur votre ordinateur.

Modèle ONNX publié par kokoro-onnx : https://github.com/thewh1teagle/kokoro-onnx/releases
Langues couvertes (voix du modèle) : anglais US/UK, français, espagnol, italien, chinois mandarin.
"""
from __future__ import annotations

import threading
import urllib.request
from pathlib import Path

import numpy as np

from ...config import get_settings
from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider, native_voice_name

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
LANG = {"en-US": "en-us", "en-GB": "en-gb", "fr-FR": "fr-fr", "es-ES": "es", "it-IT": "it", "zh-CN": "cmn"}
_lock = threading.Lock()
_model = None
_zh_g2p = None


def _mandarin_phonemes(text: str) -> str | None:
    """Phonèmes du chinois mandarin (pinyin, tons) avec le convertisseur officiel de Kokoro (misaki).

    Le modèle a été entraîné avec lui : la phonétisation générique d'espeak (« cmn ») donne un accent
    étranger. Renvoie None si misaki n'est pas installé (repli sur espeak).
    """
    global _zh_g2p
    try:
        if _zh_g2p is None:
            from misaki import zh

            _zh_g2p = zh.ZHG2P()
        phonemes, _ = _zh_g2p(text)
        return phonemes or None
    except Exception:
        return None


def model_dir() -> Path:
    return get_settings().models_dir / "kokoro"


def available() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except Exception:
        return False


def download_models(progress=print) -> None:
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = d / name
        if target.exists() and target.stat().st_size > 1000:
            continue
        progress(f"Kokoro : téléchargement de {name}…")
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(f"{RELEASE}/{name}", tmp)
        tmp.replace(target)


def _load():
    global _model
    if _model is None:
        from kokoro_onnx import Kokoro

        download_models()
        _model = Kokoro(str(model_dir() / FILES[0]), str(model_dir() / FILES[1]))
    return _model


class KokoroTTS(TTSProvider):
    name = "kokoro"

    def __init__(self):
        if not available():
            raise TTSError("Kokoro n'est pas installé (pip install kokoro-onnx).")

    def list_voices(self, locale: str) -> list[ProviderVoice]:
        from ...services.catalog import get_catalog

        return [ProviderVoice(v.id, locale, v.display_name, v.gender)
                for v in get_catalog().voices.get(locale, []) if v.provider == self.name]

    @staticmethod
    def locale_of(voice_id: str) -> str:
        from ...services.catalog import get_catalog

        return get_catalog().get_voice(voice_id).locale

    def synthesize(self, text, voice_id, rate=1.0, target_duration_ms=None) -> AudioSegment:
        lang = LANG.get(self.locale_of(voice_id))
        if lang is None:
            raise TTSError(f"Kokoro ne couvre pas cette langue ({voice_id}).")
        try:
            with _lock:  # une seule synthèse à la fois : la session ONNX utilise déjà tous les cœurs
                phonemes = _mandarin_phonemes(text) if lang == "cmn" else None
                if phonemes:
                    samples, sr = _load().create(phonemes, voice=native_voice_name(voice_id), speed=float(rate),
                                                 lang=lang, is_phonemes=True)
                else:
                    samples, sr = _load().create(text, voice=native_voice_name(voice_id), speed=float(rate), lang=lang)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Kokoro : {exc}") from exc
        return AudioSegment(np.asarray(samples, dtype=np.float32)[:, None], int(sr))
