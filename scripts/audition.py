"""Génère un échantillon de 5 s pour chaque voix du catalogue, pour relecture humaine (brief §4.1.5).

    python scripts/audition.py [--locale fr-FR] [--out samples/voices]

Écoutez chaque fichier, puis renseignez `validated_by` et `validated_on` dans config/voices.yaml
pour les voix jugées natives et naturelles par un locuteur natif.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.voices import SAMPLE_TEXT  # noqa: E402
from app.pipeline.tts import get_provider  # noqa: E402
from app.services.catalog import get_catalog  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--locale")
    ap.add_argument("--out", default=str(ROOT / "samples" / "voices"))
    args = ap.parse_args()
    catalog = get_catalog()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    providers = {}
    for locale, voices in catalog.voices.items():
        if args.locale and locale != args.locale:
            continue
        for v in voices:
            prov = providers.setdefault(v.provider, get_provider(v.provider))
            text = SAMPLE_TEXT[locale.split("-")[0]]
            try:
                seg = prov.synthesize_with_retry(text, v.id)
            except Exception as exc:  # noqa: BLE001
                print(f"✗ {v.id} : {exc}")
                continue
            path = out / f"{locale}-{v.display_name.lower()}.wav"
            sf.write(str(path), seg.samples, seg.sample_rate)
            state = "validée" if v.validated else "À VALIDER"
            print(f"✓ {v.id:<40} {seg.duration_ms / 1000:.1f} s  [{state}]  → {path}")


if __name__ == "__main__":
    main()
