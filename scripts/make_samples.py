"""Génère les fichiers de test de `samples/` (signal synthétique + transcription de référence).

Les fichiers contiennent un signal « voisé » aux horodatages de la transcription de référence
et une musique de fond. Pour des essais réels, ajoutez vos propres enregistrements.
Usage : python scripts/make_samples.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.pipeline.audio import ffmpeg_exe  # noqa: E402

SAMPLES = [
    {
        "name": "sample_fr_interview", "ext": "mp3", "sr": 44100, "channels": 2, "language": "fr", "duration": 24.0,
        "units": [
            (0.8, 4.6, "Bonjour à tous et bienvenue dans ce nouvel épisode.", "S1"),
            (5.2, 9.9, "Aujourd'hui nous parlons de doublage audio et d'intelligence artificielle.", "S1"),
            (10.6, 14.2, "Merci de m'accueillir, c'est un plaisir d'être ici.", "S2"),
            (14.9, 20.3, "Le plus important, c'est que la voix reste naturelle pour un auditeur natif.", "S2"),
            (20.9, 23.2, "Absolument, commençons.", "S1"),
        ],
    },
    {
        "name": "sample_en_voiceover", "ext": "wav", "sr": 48000, "channels": 1, "language": "en", "duration": 15.0,
        "units": [
            (0.5, 4.8, "Welcome to the training module on workplace safety.", "S1"),
            (5.5, 10.1, "In the next few minutes you will learn the three key rules.", "S1"),
            (10.8, 14.2, "Let's get started with the first one.", "S1"),
        ],
    },
    {
        "name": "sample_de_ad", "ext": "flac", "sr": 44100, "channels": 2, "language": "de", "duration": 10.0,
        "units": [
            (0.4, 4.2, "Entdecken Sie jetzt unsere neue Kollektion für den Herbst.", "S1"),
            (4.9, 9.1, "Nur für kurze Zeit mit zwanzig Prozent Rabatt.", "S1"),
        ],
    },
]


def voiced(n: int, sr: int, f0: float, rng) -> np.ndarray:
    t = np.arange(n) / sr
    sig = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6)) / k for k in range(1, 7))
    env = 0.5 * (1 - np.cos(2 * np.pi * 4.5 * t)) ** 1.5
    fade = np.minimum(1, np.minimum(t, t[-1] - t) / 0.03)
    return 0.25 * sig * env * fade


def main(out: Path | None = None, stems_dir: Path | None = None):
    out = out or ROOT / "samples"
    out.mkdir(exist_ok=True)
    rng = np.random.default_rng(7)
    for s in SAMPLES:
        sr, n = s["sr"], int(s["duration"] * s["sr"])
        t = np.arange(n) / sr
        music = 0.05 * (np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 164.8 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t))
        voice = np.zeros(n)
        for a, b, _, spk in s["units"]:
            i, j = int(a * sr), int(b * sr)
            voice[i:j] += voiced(j - i, sr, 120.0 if spk == "S1" else 210.0, rng)
        mix = np.stack([voice + music] * s["channels"], axis=1).astype(np.float32)
        wav = out / f"{s['name']}.wav"
        target = out / f"{s['name']}.{s['ext']}"
        if s["ext"] == "wav":
            sf.write(str(target), mix, sr, subtype="PCM_16")
        elif s["ext"] == "flac":
            sf.write(str(target), mix, sr, subtype="PCM_16", format="FLAC")
        else:
            sf.write(str(wav), mix, sr, subtype="PCM_16")
            subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k",
                            str(target)], check=True)
            wav.unlink()
        # Stems de référence (simulent la sortie de Demucs dans les tests)
        if stems_dir is None:
            stems_dir = out / "stems"
        stems = stems_dir / s["name"]
        stems.mkdir(parents=True, exist_ok=True)
        sf.write(str(stems / "vocals.wav"), np.stack([voice] * s["channels"], axis=1).astype(np.float32), sr)
        sf.write(str(stems / "background.wav"), np.stack([music] * s["channels"], axis=1).astype(np.float32), sr)
        (out / f"{s['name']}.json").write_text(json.dumps({
            "language": s["language"],
            "units": [{"start": a, "end": b, "text": txt, "speaker": spk} for a, b, txt, spk in s["units"]],
        }, ensure_ascii=False, indent=2))
        print("écrit", target)


if __name__ == "__main__":
    main()
