"""TTS factice pour les tests et le mode hors-ligne.

Produit un signal « voisé » (harmoniques + enveloppe syllabique) dont la durée suit le
nombre de syllabes. Ce n'est PAS une voix : il ne sert qu'à valider le pipeline.
"""
from __future__ import annotations

import numpy as np

from ..syllables import count_units
from .base import AudioSegment, ProviderVoice, TTSProvider


class MockTTS(TTSProvider):
    name = "mock"

    def __init__(self, units_per_sec: float = 5.0, sample_rate: int = 24000, bias: dict[str, float] | None = None):
        self.units_per_sec = units_per_sec
        self.sample_rate = sample_rate
        self.bias = bias or {}   # facteur de durée par voix (simule des voix plus lentes)
        self.calls: list[tuple[str, str]] = []

    def list_voices(self, locale: str) -> list[ProviderVoice]:
        return [ProviderVoice(id=f"mock:{locale}-A", locale=locale, display_name="Mock A", gender="female")]

    def synthesize(self, text, voice_id, rate=1.0, target_duration_ms=None) -> AudioSegment:
        self.calls.append((text, voice_id))
        locale = voice_id.split(":")[-1][:5]
        units = max(1, count_units(text, locale))
        seconds = units / self.units_per_sec / rate * self.bias.get(voice_id, 1.0) + 0.12
        n = int(seconds * self.sample_rate)
        t = np.arange(n) / self.sample_rate
        f0 = 180.0 if hash(voice_id) % 2 else 120.0
        sig = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))
        env = 0.5 * (1 - np.cos(2 * np.pi * self.units_per_sec * rate * t)) ** 1.5
        fade = np.minimum(1, np.minimum(t, t[-1] - t) / 0.02)
        out = (0.2 * sig * env * fade).astype(np.float32)
        return AudioSegment(out[:, None], self.sample_rate)
