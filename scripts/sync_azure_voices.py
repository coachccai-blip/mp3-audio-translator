"""Vérifie chaque voix Azure du catalogue contre l'API Azure (voices/list).

    python scripts/sync_azure_voices.py

Pour chaque voix : existe-t-elle ? sa locale correspond-elle ? est-elle multilingue (interdit) ?
Liste aussi les voix natives disponibles non présentes dans le catalogue.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline.tts.azure import AzureTTS  # noqa: E402
from app.services.catalog import get_catalog  # noqa: E402


def main():
    remote = {v["ShortName"]: v for v in AzureTTS().list_all_voices()}
    catalog = get_catalog()
    problems = 0
    for locale, voices in catalog.voices.items():
        for v in voices:
            if v.provider != "azure":
                continue
            name = v.id.split(":", 1)[1]
            r = remote.get(name)
            if r is None:
                print(f"✗ {name} : introuvable chez Azure")
                problems += 1
            elif r["Locale"] != locale:
                print(f"✗ {name} : locale Azure {r['Locale']} ≠ {locale}")
                problems += 1
            elif "Multilingual" in name or r.get("SecondaryLocaleList"):
                print(f"✗ {name} : voix multilingue (interdite)")
                problems += 1
            else:
                print(f"✓ {name} ({r.get('Gender')})")
        known = {v.id.split(':', 1)[1] for v in voices}
        extra = [n for n, r in remote.items() if r["Locale"] == locale and n not in known and "Multilingual" not in n]
        if extra:
            print(f"  autres voix natives {locale} disponibles : {', '.join(sorted(extra)[:8])}")
    print("OK" if not problems else f"{problems} problème(s) — corrigez config/voices.yaml")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
