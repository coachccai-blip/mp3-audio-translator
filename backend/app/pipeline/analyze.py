"""Étape 1 — analyse et validation du fichier (brief §5.1)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .assemble import integrated_loudness
from .audio import AUDIO_EXTS, VIDEO_EXTS, AudioError, AudioInfo, load, probe, to_mono

MAX_DURATION_MS = 3 * 3600 * 1000
LOW_SNR_DB = 10.0


@dataclass
class Analysis:
    info: AudioInfo
    loudness_lufs: float | None
    snr_db: float | None
    warnings: list[str]

    def to_dict(self) -> dict:
        return {**asdict(self.info), "loudness_lufs": self.loudness_lufs, "snr_db": self.snr_db, "warnings": self.warnings}


def estimate_snr(mono: np.ndarray, sr: int) -> float | None:
    """SNR grossier : énergie des trames fortes vs trames faibles."""
    frame = int(sr * 0.03)
    if len(mono) < frame * 20:
        return None
    n = len(mono) // frame
    energy = (mono[: n * frame].reshape(n, frame) ** 2).mean(axis=1) + 1e-12
    noise = np.percentile(energy, 10)
    signal = np.percentile(energy, 90)
    return float(10 * np.log10(signal / noise))


def analyze(path: Path) -> Analysis:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in AUDIO_EXTS | VIDEO_EXTS:
        raise AudioError(f"Format non pris en charge : {ext or 'inconnu'}")
    info = probe(path)
    if info.duration_ms > MAX_DURATION_MS:
        raise AudioError("Fichier trop long (maximum 3 h).")
    data, sr = load(path)
    info.duration_ms = int(round(len(data) * 1000 / sr))
    if info.duration_ms == 0:
        raise AudioError("Fichier vide ou corrompu.")
    warnings = []
    snr = estimate_snr(to_mono(data), sr)
    if snr is not None and snr < LOW_SNR_DB:
        warnings.append("noisy")
    return Analysis(info=info, loudness_lufs=integrated_loudness(data, sr), snr_db=snr, warnings=warnings)
