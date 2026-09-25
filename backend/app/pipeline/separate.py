"""Étape 2 — séparation voix / fond avec Demucs (htdemucs)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
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


_model = None
_model_lock = threading.Lock()


def _separate_in_process(data: np.ndarray, sr: int, device: str) -> tuple[np.ndarray, np.ndarray]:
    """Demucs chargé une fois pour toute la session (évite ~5-10 s de chargement par fichier)."""
    global _model
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    from .audio import resample, set_channels

    with _model_lock:
        if _model is None:
            _model = get_model("htdemucs")
            _model.eval()
        model = _model
    dev = "cuda" if device in ("cuda", "auto") and torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        torch.set_num_threads(os.cpu_count() or 4)
    wav = set_channels(resample(data, sr, model.samplerate), model.audio_channels)
    t = torch.from_numpy(np.ascontiguousarray(wav.T))
    ref = t.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        sources = apply_model(model, ((t - mean) / std)[None], device=dev, split=True, overlap=0.25,
                              progress=False)[0]
    sources = sources * std + mean
    vocals = sources[model.sources.index("vocals")]
    background = sources.sum(0) - vocals
    channels = data.shape[1]

    def back(x):
        return set_channels(resample(x.cpu().numpy().T.astype(np.float32), model.samplerate, sr), channels)[: len(data)]

    return back(vocals), back(background)


def separate_to_files(src: str, vocals_path: str, background_path: str, device: str) -> bool:
    """Exécuté dans le processus PyTorch (voir worker.py). Renvoie True s'il y a un fond sonore."""
    data, sr = load(Path(src))
    v, b = _separate_in_process(data, sr, device)
    save(v, sr, Path(vocals_path))
    if is_near_silent(b):
        return False
    save(b, sr, Path(background_path))
    return True


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
    try:
        from . import worker

        has_background = worker.run("separate.separate_to_files", str(src), str(vocals), str(background), device)
        return Separation(vocals, background if has_background else None, "demucs")
    except Exception:  # repli : Demucs en ligne de commande
        pass
    cmd = [sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "-o", str(out_dir / "demucs")]
    engine = "demucs-cli"
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
        return Separation(vocals, None, engine)
    save(b, sr, background)
    return Separation(vocals, background, engine)
