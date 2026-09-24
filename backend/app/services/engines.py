"""Moteurs injectables (permet de remplacer les modèles lourds dans les tests)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import get_settings
from ..pipeline import diarize as diarize_mod
from ..pipeline import separate as separate_mod
from ..pipeline import transcribe as transcribe_mod
from ..pipeline.translate import Translator, make_translator
from ..pipeline.tts import TTSProvider, get_provider


@dataclass
class Engines:
    separate: Callable[[Path, Path], separate_mod.Separation]
    transcribe: Callable[..., transcribe_mod.Transcript]
    diarize: Callable[[Path], list]
    detect_language: Callable[[Path], tuple[str, float] | None]
    translator: Callable[[], Translator]
    tts: Callable[[str], TTSProvider]


_tts_cache: dict[str, TTSProvider] = {}


def _tts(name: str) -> TTSProvider:
    if name not in _tts_cache:
        _tts_cache[name] = get_provider(name)
    return _tts_cache[name]


def default_engines() -> Engines:
    s = get_settings()
    return Engines(
        separate=lambda src, out: separate_mod.separate(src, out, s.device),
        transcribe=lambda path, language=None, on_unit=None, model=None: transcribe_mod.transcribe(
            path, model or s.whisper_model, s.device, language, on_unit),
        diarize=diarize_mod.diarize,
        detect_language=lambda path: transcribe_mod.detect_language(path, s.whisper_model, s.device),
        translator=make_translator,
        tts=_tts,
    )


_engines: Engines | None = None


def get_engines() -> Engines:
    global _engines
    if _engines is None:
        _engines = default_engines()
    return _engines


def set_engines(engines: Engines | None) -> None:
    global _engines
    _engines = engines
    _tts_cache.clear()
