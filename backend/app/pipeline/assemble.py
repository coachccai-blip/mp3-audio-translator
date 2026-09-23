"""Assemblage final (brief §5.1, étapes 10–11)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import fit_length, set_channels

CROSSFADE_MS = 10
DUCK_DB = -6.0
ATTACK_MS = 50
RELEASE_MS = 300


@dataclass
class PlacedSegment:
    start_ms: float
    samples: np.ndarray  # (n, 1) ou (n, ch), même sample rate que la sortie


def apply_fades(seg: np.ndarray, sr: int, ms: float = CROSSFADE_MS) -> np.ndarray:
    n = min(int(sr * ms / 1000), len(seg) // 2)
    if n <= 0:
        return seg
    seg = seg.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    seg[:n] *= ramp
    seg[-n:] *= ramp[::-1]
    return seg


def build_voice_track(segments: list[PlacedSegment], n_total: int, sr: int, channels: int) -> tuple[np.ndarray, np.ndarray]:
    """Piste voix de la durée exacte + masque d'activité vocale."""
    track = np.zeros((n_total, channels), dtype=np.float32)
    active = np.zeros(n_total, dtype=bool)
    for s in segments:
        start = int(round(s.start_ms * sr / 1000))
        if start >= n_total:
            continue
        seg = apply_fades(set_channels(s.samples, channels), sr)
        end = min(n_total, start + len(seg))
        track[start:end] += seg[: end - start]
        active[start:end] = True
    return track, active


def ducking_gain(active: np.ndarray, sr: int, duck_db: float = DUCK_DB,
                 attack_ms: float = ATTACK_MS, release_ms: float = RELEASE_MS) -> np.ndarray:
    """Gain du fond : −6 dB sous la voix, attaque 50 ms, relâchement 300 ms."""
    if len(active) == 0:
        return np.ones(0, dtype=np.float32)
    block = max(1, sr // 1000)  # calcul à 1 kHz puis interpolation
    n_blocks = int(np.ceil(len(active) / block))
    padded = np.zeros(n_blocks * block, dtype=bool)
    padded[: len(active)] = active
    target = np.where(padded.reshape(n_blocks, block).any(axis=1), 10 ** (duck_db / 20), 1.0)
    a_att = np.exp(-1.0 / max(attack_ms, 1e-3))
    a_rel = np.exp(-1.0 / max(release_ms, 1e-3))
    g = np.empty(n_blocks, dtype=np.float64)
    cur = 1.0
    for i, t in enumerate(target):
        a = a_att if t < cur else a_rel
        cur = a * cur + (1 - a) * t
        g[i] = cur
    x_blocks = (np.arange(n_blocks) + 0.5) * block
    gain = np.interp(np.arange(len(active)), x_blocks, g)
    return gain.astype(np.float32)


def integrated_loudness(data: np.ndarray, sr: int) -> float | None:
    try:
        import pyloudnorm as pyln

        if len(data) < sr * 0.5:
            return None
        value = pyln.Meter(sr).integrated_loudness(data.astype(np.float64))
        return float(value) if np.isfinite(value) else None
    except Exception:
        return None


def match_loudness(data: np.ndarray, sr: int, target_lufs: float | None) -> np.ndarray:
    """Normalise au niveau mesuré sur l'original (EBU R128), avec limiteur doux."""
    if target_lufs is None:
        return data
    current = integrated_loudness(data, sr)
    if current is None:
        return data
    out = data * (10 ** ((target_lufs - current) / 20))
    peak = np.abs(out).max() if len(out) else 0
    if peak > 0.98:
        # limiteur doux : compresse seulement au-dessus du seuil
        thr = 0.9
        over = np.abs(out) > thr
        out[over] = np.sign(out[over]) * (thr + (1 - thr) * np.tanh((np.abs(out[over]) - thr) / (1 - thr)))
    return out.astype(np.float32)


def assemble(segments: list[PlacedSegment], n_total: int, sr: int, channels: int,
             background: np.ndarray | None = None, target_lufs: float | None = None,
             duck: bool = True) -> dict[str, np.ndarray]:
    """Renvoie {'mix', 'voice', 'background'} à la durée exacte de l'original."""
    voice, active = build_voice_track(segments, n_total, sr, channels)
    out = {"voice": voice}
    if background is not None:
        bg = fit_length(set_channels(background, channels), n_total)
        if duck:
            bg = bg * ducking_gain(active, sr)[:, None]
        out["background"] = bg
        mix = voice + bg
    else:
        mix = voice
    out["mix"] = match_loudness(mix, sr, target_lufs)
    for k in out:
        out[k] = fit_length(out[k], n_total)
    return out
