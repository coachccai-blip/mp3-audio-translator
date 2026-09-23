"""Catalogue des langues et des voix natives (brief §3, §4.1, §10)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import CONFIG_DIR, get_settings


class NoNativeVoiceError(Exception):
    """Aucune voix native validée pour la locale : on refuse, jamais de repli silencieux."""

    def __init__(self, locale: str):
        super().__init__(f"Aucune voix native validée pour {locale}")
        self.locale = locale


@dataclass
class Voice:
    id: str
    provider: str
    locale: str
    display_name: str
    gender: str
    age_range: str = "adult"
    styles: list[str] = field(default_factory=list)
    sample: str | None = None
    validated_by: str | None = None
    validated_on: str | None = None
    status: str = "to_confirm"
    default: bool = False
    disabled: bool = False

    @property
    def validated(self) -> bool:
        return bool(self.validated_by and self.validated_on)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "provider": self.provider, "locale": self.locale, "display_name": self.display_name,
            "gender": self.gender, "age_range": self.age_range, "styles": self.styles,
            "validated": self.validated, "status": self.status, "default": self.default, "disabled": self.disabled,
        }


class Catalog:
    def __init__(self, languages_path: Path, voices_path: Path, disabled_path: Path | None = None):
        self.languages: dict = yaml.safe_load(languages_path.read_text(encoding="utf-8"))["languages"]
        raw = yaml.safe_load(voices_path.read_text(encoding="utf-8")) or {}
        self.disabled_path = disabled_path
        disabled = set()
        if disabled_path and disabled_path.exists():
            disabled = {l.strip() for l in disabled_path.read_text().splitlines() if l.strip()}
        self.voices: dict[str, list[Voice]] = {}
        for locale, entries in raw.items():
            for e in entries or []:
                if "multilingual" in e["id"].lower():
                    raise ValueError(f"Voix multilingue interdite dans le catalogue : {e['id']}")
                v = Voice(
                    id=e["id"], provider=e.get("provider", e["id"].split(":")[0]), locale=locale,
                    display_name=e.get("display_name", e["id"]), gender=e.get("gender", "unknown"),
                    age_range=e.get("age_range", "adult"), styles=list(e.get("styles") or []),
                    sample=e.get("sample"), validated_by=e.get("validated_by"),
                    validated_on=str(e["validated_on"]) if e.get("validated_on") else None,
                    status=e.get("status", "to_confirm"), default=bool(e.get("default")),
                    disabled=e["id"] in disabled,
                )
                self.voices.setdefault(locale, []).append(v)

    # --- Langues -----------------------------------------------------------
    def locale_info(self, locale: str) -> dict:
        lang = locale.split("-")[0]
        info = self.languages.get(lang)
        if not info or locale not in info["variants"]:
            raise KeyError(locale)
        return {**info["variants"][locale], "lang": lang, "count_unit": info.get("count_unit", "syllables")}

    def units_per_sec(self, locale: str) -> float:
        return float(self.locale_info(locale)["syllables_per_sec"])

    def all_locales(self) -> list[str]:
        return [loc for info in self.languages.values() for loc in info["variants"]]

    # --- Voix --------------------------------------------------------------
    def usable_voices(self, locale: str, require_validated: bool | None = None) -> list[Voice]:
        if require_validated is None:
            require_validated = get_settings().require_validated_voices
        return [v for v in self.voices.get(locale, [])
                if not v.disabled and (v.validated or not require_validated)]

    def available_locales(self) -> list[str]:
        """Une variante n'est proposée que si au moins une voix native utilisable existe (§3)."""
        return [loc for loc in self.all_locales() if self.usable_voices(loc)]

    def voices_for(self, locale: str) -> list[Voice]:
        voices = self.usable_voices(locale)
        if not voices:
            raise NoNativeVoiceError(locale)
        return voices

    def get_voice(self, voice_id: str) -> Voice:
        for vs in self.voices.values():
            for v in vs:
                if v.id == voice_id:
                    return v
        raise KeyError(voice_id)

    def default_voice(self, locale: str, gender: str | None = None) -> Voice:
        voices = self.voices_for(locale)
        if gender in ("male", "female"):
            same = [v for v in voices if v.gender == gender]
            if same:
                return next((v for v in same if v.default), same[0])
        return next((v for v in voices if v.default), voices[0])

    def languages_payload(self) -> list[dict]:
        """Langues pour l'UI, variantes sans voix native masquées (pas grisées)."""
        available = set(self.available_locales())
        out = []
        for code, info in self.languages.items():
            variants = [{"locale": loc, **v} for loc, v in info["variants"].items() if loc in available]
            if not variants:
                continue
            default = info["default_locale"] if info["default_locale"] in available else variants[0]["locale"]
            out.append({"code": code, "native_name": info["native_name"], "names": info["names"],
                        "default_locale": default, "variants": variants})
        return out

    def set_disabled(self, voice_id: str, disabled: bool) -> None:
        v = self.get_voice(voice_id)
        v.disabled = disabled
        if self.disabled_path:
            ids = sorted(x.id for vs in self.voices.values() for x in vs if x.disabled)
            self.disabled_path.parent.mkdir(parents=True, exist_ok=True)
            self.disabled_path.write_text("\n".join(ids) + "\n")


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    s = get_settings()
    return Catalog(CONFIG_DIR / "languages.yaml", CONFIG_DIR / "voices.yaml", s.data_dir / "disabled_voices.txt")
