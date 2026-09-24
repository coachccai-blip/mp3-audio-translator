"""Télécharge d'avance les modèles locaux (appelé par l'installateur Windows).

    python scripts/download_models.py [--whisper large-v3]
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="large-v3")
    args = ap.parse_args()
    from faster_whisper import WhisperModel

    print(f"Whisper {args.whisper}…", flush=True)
    WhisperModel(args.whisper, device="cpu", compute_type="int8")
    from demucs.pretrained import get_model

    print("Demucs htdemucs…", flush=True)
    get_model("htdemucs")
    print("Modèles prêts.")


if __name__ == "__main__":
    main()
