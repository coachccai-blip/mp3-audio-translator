"""Télécharge d'avance les modèles locaux (appelé par l'installateur Windows).

    python scripts/download_models.py [--whisper large-v3]
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="large-v3-turbo")
    args = ap.parse_args()
    from faster_whisper import WhisperModel

    print(f"Whisper {args.whisper}…", flush=True)
    WhisperModel(args.whisper, device="cpu", compute_type="int8")
    from demucs.pretrained import get_model

    print("Demucs htdemucs…", flush=True)
    get_model("htdemucs")
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.pipeline.tts import kokoro, piper
    from app.services.catalog import get_catalog

    print("Kokoro (voix HD gratuites)…", flush=True)
    kokoro.download_models()
    names = sorted({v.id.split(":", 1)[1] for vs in get_catalog().voices.values() for v in vs if v.provider == "piper"})
    for i, name in enumerate(names, 1):
        print(f"Piper {i}/{len(names)} : {name}", flush=True)
        piper.download_voice(name)
    print("Modèles prêts.")


if __name__ == "__main__":
    main()
