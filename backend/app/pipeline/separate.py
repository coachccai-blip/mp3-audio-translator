"""Étape 2 — séparation voix / fond avec Demucs (htdemucs)."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import load, save

BACKGROUND_SILENCE_DB = -45.0


@dataclass
class Separation:
    vocals: Path
    background: Path | None       # None = fichier voix seule, pas de remix
    engine: str


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except Exception:
        return False


def is_near_silent(data: np.ndarray, threshold_db: float = BACKGROUND_SILENCE_DB) -> bool:
    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2))) if len(data) else 0.0
    return 20 * np.log10(rms + 1e-12) < threshold_db


def separate(src: Path, out_dir: Path, device: str = "auto") -> Separation:
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals, background = out_dir / "vocals.wav", out_dir / "background.wav"
    if vocals.exists():
        return Separation(vocals, background if background.exists() else None, "cache")
    data, sr = load(src)
    if not demucs_available():
        # Repli : pas de séparation → on considère que tout est voix, le fond n'est pas conservé.
        save(data, sr, vocals)
        return Separation(vocals, None, "none")
    cmd = [sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "-o", str(out_dir / "demucs")]
    if device in ("cpu", "cuda", "mps"):
        cmd += ["-d", device]
    wav_in = out_dir / "input.wav"
    save(data, sr, wav_in)
    proc = subprocess.run([*cmd, str(wav_in)], capture_output=True)
    wav_in.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Demucs a échoué : {proc.stderr.decode('utf-8', 'replace')[-400:]}")
    stem_dir = out_dir / "demucs" / "htdemucs" / "input"
    v, vsr = load(stem_dir / "vocals.wav", sample_rate=sr)
    b, _ = load(stem_dir / "no_vocals.wav", sample_rate=sr)
    save(v, sr, vocals)
    if is_near_silent(b):
        return Separation(vocals, None, "demucs")
    save(b, sr, background)
    return Separation(vocals, background, "demucs")
