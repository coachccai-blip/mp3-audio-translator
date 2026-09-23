"""Calibre le débit (syllabes ou caractères par seconde) de chaque locale sur le TTS réel (brief §7.2).

    python scripts/calibrate_rate.py [--write]

Synthétise des phrases de référence avec la voix par défaut de chaque variante, mesure la durée
et propose (ou écrit avec --write) les nouvelles valeurs dans config/languages.yaml.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline.syllables import count_units  # noqa: E402
from app.pipeline.tts import get_provider  # noqa: E402
from app.services.catalog import get_catalog  # noqa: E402

SENTENCES = {
    "fr": ["Nous avons préparé une présentation claire pour toute l'équipe.", "Le rendez-vous est fixé à demain matin, dans la grande salle."],
    "en": ["We have prepared a clear presentation for the whole team.", "The meeting is set for tomorrow morning in the main room."],
    "zh": ["我们为整个团队准备了一份清晰的演示。", "会议定在明天早上，在大会议室举行。"],
    "de": ["Wir haben eine klare Präsentation für das ganze Team vorbereitet.", "Das Treffen ist für morgen früh im großen Saal geplant."],
    "sv": ["Vi har förberett en tydlig presentation för hela teamet.", "Mötet är planerat till i morgon bitti i det stora rummet."],
    "es": ["Hemos preparado una presentación clara para todo el equipo.", "La reunión está fijada para mañana por la mañana en la sala grande."],
    "it": ["Abbiamo preparato una presentazione chiara per tutto il team.", "La riunione è fissata per domani mattina nella sala grande."],
    "pl": ["Przygotowaliśmy jasną prezentację dla całego zespołu.", "Spotkanie zaplanowano na jutro rano w dużej sali."],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    catalog = get_catalog()
    path = ROOT / "config" / "languages.yaml"
    text = path.read_text(encoding="utf-8")
    for locale in catalog.available_locales():
        v = catalog.default_voice(locale)
        prov = get_provider(v.provider)
        units, seconds = 0, 0.0
        for s in SENTENCES[locale.split("-")[0]]:
            seg = prov.synthesize_with_retry(s, v.id)
            units += count_units(s, locale)
            seconds += seg.duration_ms / 1000 - 0.15  # silence de début/fin approximatif
        rate = round(units / seconds, 2)
        old = catalog.units_per_sec(locale)
        print(f"{locale}: {old} → {rate} ({v.id})")
        if args.write:
            text = re.sub(rf"({re.escape(locale)}: \{{[^}}]*syllables_per_sec: )[\d.]+", rf"\g<1>{rate}", text)
    if args.write:
        path.write_text(text, encoding="utf-8")
        print("config/languages.yaml mis à jour.")


if __name__ == "__main__":
    main()
