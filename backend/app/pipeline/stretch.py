"""Time-stretching sans changement de hauteur (brief §4.3).

Utilise pyrubberband + rubberband si disponibles (meilleure qualité), sinon un WSOLA numpy.
"""
from __future__ import annotations

import shutil

import numpy as np

from .audio import fit_length


def _has_rubberband() -> bool:
    try:
        import pyrubberband  # noqa: F401
    except Exception:
        return False
    return shutil.which("rubberband") is not None


def stretch_to_length(data: np.ndarray, sr: int, n_target: int) -> np.ndarray:
    """Étire/compresse `data` (n, ch) pour obtenir exactement `n_target` échantillons."""
    if data.ndim == 1:
        data = data[:, None]
    n = len(data)
    if n == 0 or n_target <= 0:
        return np.zeros((max(n_target, 0), data.shape[1]), dtype=np.float32)
    if n == n_target:
        return data
    rate = n / n_target  # >1 : accélérer
    if _has_rubberband():
        import pyrubberband as pyrb

        out = pyrb.time_stretch(data, sr, rate)
    else:
        out = wsola(data, sr, rate)
    return fit_length(out.astype(np.float32), n_target)


def wsola(data: np.ndarray, sr: int, rate: float) -> np.ndarray:
    """Waveform Similarity Overlap-Add. `rate` > 1 raccourcit, < 1 allonge."""
    frame = max(256, int(sr * 0.032))
    frame += frame % 2
    hop_out = frame // 2
    hop_in = hop_out * rate
    tol = hop_out // 2
    window = np.hanning(frame).astype(np.float32)
    mono = data.mean(axis=1)
    n = len(data)
    n_out = int(round(n / rate))
    pad = frame + tol * 2
    x = np.concatenate([np.zeros((tol, data.shape[1]), np.float32), data, np.zeros((pad, data.shape[1]), np.float32)])
    xm = np.concatenate([np.zeros(tol, np.float32), mono, np.zeros(pad, np.float32)])
    out = np.zeros((n_out + frame * 2, data.shape[1]), dtype=np.float32)
    norm = np.zeros(n_out + frame * 2, dtype=np.float32)

    prev_pos = tol
    k = 0
    while True:
        out_pos = k * hop_out
        if out_pos >= n_out:
            break
        nominal = int(round(k * hop_in)) + tol
        if k == 0:
            pos = nominal
        else:
            # Chercher, autour de la position nominale, le segment le plus semblable
            # à la continuation naturelle du segment précédent.
            natural = xm[prev_pos + hop_out: prev_pos + hop_out + frame]
            lo = max(0, nominal - tol)
            hi = min(len(xm) - frame, nominal + tol)
            if hi <= lo or len(natural) < frame:
                pos = min(max(nominal, 0), len(xm) - frame)
            else:
                region = xm[lo: hi + frame]
                corr = np.correlate(region, natural, mode="valid")
                pos = lo + int(np.argmax(corr))
        seg = x[pos: pos + frame]
        if len(seg) < frame:
            break
        out[out_pos: out_pos + frame] += seg * window[:, None]
        norm[out_pos: out_pos + frame] += window
        prev_pos = pos
        k += 1

    norm[norm < 1e-3] = 1.0
    out = out / norm[:, None]
    return out[:n_out]
