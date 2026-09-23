"""Interface commune des fournisseurs de synthèse vocale (brief §5.1, étape 8)."""
from __future__ import annotations

import io
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import soundfile as sf


class TTSError(Exception):
    pass


@dataclass
class AudioSegment:
    samples: np.ndarray  # float32 (n, 1)
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        return len(self.samples) * 1000.0 / self.sample_rate

    @classmethod
    def from_bytes(cls, data: bytes) -> "AudioSegment":
        arr, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return cls(arr[:, :1] if arr.shape[1] > 1 else arr, sr)


@dataclass
class ProviderVoice:
    id: str
    locale: str
    display_name: str
    gender: str | None = None


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def list_voices(self, locale: str) -> list[ProviderVoice]:
        ...

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, rate: float = 1.0,
                   target_duration_ms: float | None = None) -> AudioSegment:
        ...

    def supports_target_duration(self) -> bool:
        return False

    def synthesize_with_retry(self, text: str, voice_id: str, rate: float = 1.0,
                              target_duration_ms: float | None = None, attempts: int = 3) -> AudioSegment:
        """Réessai ×3 avec backoff exponentiel (brief §8.4)."""
        delay = 1.0
        last: Exception | None = None
        for i in range(attempts):
            try:
                return self.synthesize(text, voice_id, rate, target_duration_ms)
            except TTSError as exc:
                last = exc
                if i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        raise TTSError(f"Synthèse échouée après {attempts} essais : {last}")


def native_voice_name(voice_id: str) -> str:
    """`azure:fr-FR-DeniseNeural` → `fr-FR-DeniseNeural`."""
    return voice_id.split(":", 1)[1] if ":" in voice_id else voice_id
