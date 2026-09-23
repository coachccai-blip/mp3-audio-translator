"""Étape 5 — estimation grossière du genre par locuteur (pré-sélection de voix uniquement)."""
from __future__ import annotations

import numpy as np


def estimate_f0(mono: np.ndarray, sr: int) -> float | None:
    """Fréquence fondamentale médiane par autocorrélation sur trames voisées."""
    frame = int(sr * 0.04)
    hop = frame // 2
    lo, hi = int(sr / 400), int(sr / 70)
    f0s = []
    for start in range(0, len(mono) - frame, hop):
        x = mono[start: start + frame].astype(np.float64)
        x = x - x.mean()
        energy = np.dot(x, x)
        if energy < 1e-4 * frame * 0.01:
            continue
        ac = np.correlate(x, x, mode="full")[frame - 1:]
        if hi >= len(ac):
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / (ac[0] + 1e-12) > 0.4:
            f0s.append(sr / lag)
    return float(np.median(f0s)) if len(f0s) >= 5 else None


def estimate_gender(mono: np.ndarray, sr: int) -> str:
    f0 = estimate_f0(mono, sr)
    if f0 is None:
        return "unknown"
    return "female" if f0 >= 165 else "male"
