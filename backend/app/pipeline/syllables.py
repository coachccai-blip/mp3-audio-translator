"""Comptage de syllabes et estimation de durée parlée (brief §7.2)."""
from __future__ import annotations

import re

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_DIGIT = re.compile(r"\d")
# Groupes de voyelles par langue (approximation suffisante pour l'estimation de durée).
_VOWELS = {
    "fr": "aeiouyàâäéèêëîïôöùûüœæ",
    "en": "aeiouy",
    "de": "aeiouyäöü",
    "sv": "aeiouyåäö",
    "es": "aeiouáéíóúü",
    "it": "aeiouàèéìíòóùú",
    "pl": "aeiouyąęó",
}
# Digrammes comptés comme une seule syllabe.
_DIPHTHONGS = {
    "fr": ["eau", "ou", "ai", "ei", "au", "oi", "eu", "œu"],
    "en": ["ea", "ee", "oo", "ou", "ai", "ay", "oa", "ie"],
    "de": ["ei", "ie", "au", "eu", "äu"],
    "sv": [],
    "es": ["ai", "ei", "oi", "au", "eu", "ia", "ie", "io", "ua", "ue", "uo"],
    "it": ["ia", "ie", "io", "iu", "ua", "ue", "uo"],
    "pl": ["ie", "ia", "io", "iu"],
}


def lang_of(locale: str) -> str:
    return locale.split("-")[0].lower()


def count_units(text: str, locale: str) -> int:
    """Syllabes (langues latines) ou caractères (chinois)."""
    lang = lang_of(locale)
    if lang == "zh":
        return len(_CJK.findall(text)) + len(_DIGIT.findall(text))
    vowels = _VOWELS.get(lang, "aeiouy")
    text = text.lower()
    for d in _DIPHTHONGS.get(lang, []):
        text = text.replace(d, "a")
    total = 0
    for word in re.findall(r"[^\W\d_]+|\d+", text):
        if word.isdigit():
            total += 2 * len(word)  # « 2026 » se prononce en plusieurs syllabes
            continue
        groups = re.findall(f"[{vowels}]+", word)
        n = len(groups)
        if lang == "fr" and n > 1 and word.endswith("e"):
            n -= 1  # e muet final
        if lang == "en" and n > 1 and word.endswith("e") and not word.endswith("le"):
            n -= 1
        total += max(1, n)
    return total


def estimate_seconds(text: str, locale: str, units_per_sec: float) -> float:
    return count_units(text, locale) / units_per_sec if units_per_sec > 0 else 0.0


def max_units_for(seconds: float, units_per_sec: float) -> int:
    return max(1, int(seconds * units_per_sec))
