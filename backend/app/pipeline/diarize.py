"""Étape 4 — diarisation des locuteurs (pyannote.audio 3.x)."""
from __future__ import annotations

import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from .transcribe import Unit

MIN_SPEAKER_S = 3.0


def pyannote_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401
        return bool(os.environ.get("HF_TOKEN"))
    except Exception:
        return False


@lru_cache(maxsize=1)
def _pipeline():
    from pyannote.audio import Pipeline

    import torch

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=os.environ["HF_TOKEN"])
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
    return pipeline


def diarize(path: Path) -> list[tuple[float, float, str]]:
    """Renvoie des tours de parole (début, fin, locuteur). Liste vide si indisponible."""
    if not pyannote_available():
        return []
    import torch

    from .audio import load

    data, sr = load(path)
    # Audio passé en mémoire : évite la dépendance de pyannote au décodage de fichiers (FFmpeg).
    annotation = _pipeline()({"waveform": torch.from_numpy(data.T.copy()), "sample_rate": sr})
    return [(t.start, t.end, spk) for t, _, spk in annotation.itertracks(yield_label=True)]


def assign_speakers(units: list[Unit], turns: list[tuple[float, float, str]]) -> list[Unit]:
    """Attribue à chaque unité le locuteur qui la recouvre le plus."""
    if not turns:
        for u in units:
            u.speaker = "S1"
        return units
    for u in units:
        overlap: dict[str, float] = defaultdict(float)
        for s, e, spk in turns:
            o = min(e, u.end) - max(s, u.start)
            if o > 0:
                overlap[spk] += o
        if overlap:
            u.speaker = max(overlap, key=overlap.get)
        else:
            mid = (u.start + u.end) / 2
            u.speaker = min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)))[2]
    return merge_small_speakers(units)


def merge_small_speakers(units: list[Unit], min_s: float = MIN_SPEAKER_S) -> list[Unit]:
    """Fusionne les locuteurs < 3 s de parole dans le locuteur voisin le plus proche."""
    totals: dict[str, float] = defaultdict(float)
    for u in units:
        totals[u.speaker] += u.end - u.start
    small = {s for s, t in totals.items() if t < min_s}
    if not small or len(small) == len(totals):
        return _relabel(units)
    for i, u in enumerate(units):
        if u.speaker not in small:
            continue
        best, best_dist = None, float("inf")
        for j, v in enumerate(units):
            if v.speaker in small:
                continue
            dist = abs(j - i)
            if dist < best_dist:
                best, best_dist = v.speaker, dist
        u.speaker = best or u.speaker
    return _relabel(units)


def _relabel(units: list[Unit]) -> list[Unit]:
    """Renomme les locuteurs S1, S2… dans l'ordre d'apparition."""
    mapping: dict[str, str] = {}
    for u in units:
        if u.speaker not in mapping:
            mapping[u.speaker] = f"S{len(mapping) + 1}"
        u.speaker = mapping[u.speaker]
    return units
