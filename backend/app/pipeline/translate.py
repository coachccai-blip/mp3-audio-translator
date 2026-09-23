"""Traduction isochrone avec Claude (brief §7)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from ..config import get_settings
from .syllables import count_units

LANG_NAMES = {
    "fr": "French", "en": "English", "zh": "Mandarin Chinese", "de": "German", "sv": "Swedish",
    "es": "Spanish", "it": "Italian", "pl": "Polish", "pt": "Portuguese", "nl": "Dutch", "ja": "Japanese",
    "ko": "Korean", "ru": "Russian", "ar": "Arabic",
}
REGION_HINTS = {
    "fr-FR": "France", "fr-CA": "Québec/Canada (vocabulaire et tournures québécoises)",
    "fr-BE": "Belgium (septante, nonante…)", "fr-CH": "Switzerland (septante, huitante, nonante…)",
    "en-US": "United States (American spelling and idioms)", "en-GB": "United Kingdom (British spelling and idioms)",
    "en-AU": "Australia", "en-IE": "Ireland", "zh-CN": "Mainland China (Simplified characters)",
    "zh-TW": "Taiwan (Traditional characters, Taiwanese Mandarin usage)", "de-DE": "Germany",
    "de-AT": "Austria (österreichisches Deutsch)", "de-CH": "Switzerland (Schweizer Hochdeutsch, no ß)",
    "sv-SE": "Sweden", "es-ES": "Spain (peninsular Spanish, vosotros)", "es-MX": "Mexico (ustedes)",
    "es-AR": "Argentina (voseo)", "it-IT": "Italy", "pl-PL": "Poland",
}
REGISTERS = {"auto", "formal", "conversational", "advertising", "educational"}


class TranslationError(Exception):
    pass


@dataclass
class Attempt:
    text: str
    actual_seconds: float
    ratio: float  # durée obtenue / durée cible


@dataclass
class TranslationRequest:
    text: str
    source_lang: str
    target_locale: str
    target_seconds: float
    max_units: int
    count_unit: str = "syllables"
    register: str = "conversational"
    prev: list[str] = field(default_factory=list)
    next: list[str] = field(default_factory=list)
    glossary: list[tuple[str, str]] = field(default_factory=list)  # (source, cible ou "" = ne pas traduire)
    previous: Attempt | None = None


@dataclass
class TranslationResult:
    text: str
    estimated_units: int


@dataclass
class DocumentAnalysis:
    register: str
    terms: list[tuple[str, str]]


class Translator(Protocol):
    def translate(self, req: TranslationRequest) -> TranslationResult: ...
    def analyze_document(self, text: str, source_lang: str, target_locale: str) -> DocumentAnalysis: ...


# --- Prompts (§7.3) ---------------------------------------------------------

def build_system_prompt(req: TranslationRequest) -> str:
    target_lang = LANG_NAMES.get(req.target_locale.split("-")[0], req.target_locale)
    source_lang = LANG_NAMES.get(req.source_lang, req.source_lang)
    region = REGION_HINTS.get(req.target_locale, req.target_locale)
    unit = "characters" if req.count_unit == "characters" else "syllables"
    lines = [
        f"You are a professional dubbing translator and a native speaker of {target_lang} as spoken in {region}.",
        f"You translate spoken {source_lang} into natural spoken {target_lang} ({req.target_locale}) for voice dubbing.",
        f"Use vocabulary, spelling and turns of phrase native to {region}.",
        f"Register: {req.register}.",
        "",
        "Rules:",
        "- Sound natural to a native listener above all; this text will be read aloud by a native voice.",
        f"- The spoken duration must fit the time window: condense or expand wording as needed, without losing meaning.",
        "- Never add information that is not in the source. Never drop key information.",
        "- Keep proper nouns and numbers exactly (numbers may be written as words if more natural to say).",
        "- Output only the translated line, no notes, no quotes, no stage directions.",
        f"- Count length in {unit}" + (" (Chinese characters)." if unit == "characters" else "."),
        "",
        'Respond with strict JSON only: {"translation": "...", "estimated_syllables": n}',
    ]
    if req.glossary:
        lines += ["", "Glossary (mandatory):"]
        for src, tgt in req.glossary:
            lines.append(f"- \"{src}\" → keep as is" if not tgt else f"- \"{src}\" → \"{tgt}\"")
    return "\n".join(lines)


def build_user_prompt(req: TranslationRequest) -> str:
    parts = []
    if req.prev:
        parts.append("Previous lines (context, do not translate):\n" + "\n".join(f"- {t}" for t in req.prev[-2:]))
    if req.next:
        parts.append("Next lines (context, do not translate):\n" + "\n".join(f"- {t}" for t in req.next[:2]))
    parts.append(f"Target spoken duration: {req.target_seconds:.2f} s (recommended maximum: {req.max_units} "
                 f"{'characters' if req.count_unit == 'characters' else 'syllables'}).")
    parts.append(f"Line to translate:\n{req.text}")
    if req.previous:
        p = req.previous
        pct = abs(1 - 1 / p.ratio) * 100 if p.ratio > 1 else abs(1 - p.ratio) * 100
        direction = "Shorten" if p.ratio > 1 else "Lengthen"
        parts.append(
            f"Your previous translation was:\n{p.text}\n"
            f"Spoken, it lasted {p.actual_seconds:.2f} s instead of {req.target_seconds:.2f} s (ratio {p.ratio:.2f}). "
            f"{direction} it by about {pct:.0f}% while keeping it natural and faithful."
        )
    return "\n\n".join(parts)


# --- Implémentation Claude ---------------------------------------------------

class _TranslationOut(BaseModel):
    translation: str
    estimated_syllables: int


class _Term(BaseModel):
    source: str
    target: str


class _DocOut(BaseModel):
    speech_register: str
    terms: list[_Term]


class ClaudeTranslator:
    def __init__(self, model: str | None = None, client=None):
        self.model = model or get_settings().claude_model
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise TranslationError("Clé API Anthropic manquante (ANTHROPIC_API_KEY). Renseignez-la dans Réglages.")
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.input_tokens = 0
        self.output_tokens = 0

    def _parse(self, system: str, user: str, schema: type[BaseModel], max_tokens: int = 4000):
        import anthropic

        try:
            resp = self.client.messages.parse(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}], output_format=schema,
                output_config={"effort": os.environ.get("DOUBLR_CLAUDE_EFFORT", "medium")},
            )
        except anthropic.RateLimitError as exc:
            raise TranslationError(f"Limite de débit Anthropic atteinte : {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise TranslationError(f"Erreur API Anthropic ({exc.status_code}) : {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise TranslationError(f"API Anthropic injoignable : {exc}") from exc
        usage = getattr(resp, "usage", None)
        if usage:
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
        if resp.stop_reason == "refusal":
            raise TranslationError("Traduction refusée par le modèle pour ce segment.")
        if resp.parsed_output is None:
            raise TranslationError("Réponse de traduction invalide.")
        return resp.parsed_output

    def translate(self, req: TranslationRequest) -> TranslationResult:
        out = self._parse(build_system_prompt(req), build_user_prompt(req), _TranslationOut)
        text = out.translation.strip()
        return TranslationResult(text=text, estimated_units=count_units(text, req.target_locale))

    def analyze_document(self, text: str, source_lang: str, target_locale: str) -> DocumentAnalysis:
        target = LANG_NAMES.get(target_locale.split("-")[0], target_locale)
        system = (
            "You prepare a transcript for professional dubbing. Detect the register "
            "(speech_register, one of: formal, conversational, advertising, educational) and extract recurring proper nouns, "
            f"speaker names and key terms, with the translation to use consistently in {target} ({target_locale}). "
            "Use an empty string as target when the term must stay untranslated (brands, people). "
            "At most 30 terms. Respond with JSON only."
        )
        out = self._parse(system, f"Source language: {LANG_NAMES.get(source_lang, source_lang)}\n\nTranscript:\n{text}", _DocOut)
        register = out.speech_register if out.speech_register in REGISTERS else "conversational"
        return DocumentAnalysis(register=register, terms=[(t.source, t.target) for t in out.terms])


class EchoTranslator:
    """Traducteur factice (tests / démonstration) : ajuste la longueur du texte au besoin."""

    def __init__(self):
        self.calls: list[TranslationRequest] = []

    def translate(self, req: TranslationRequest) -> TranslationResult:
        self.calls.append(req)
        words = req.text.split()
        if req.previous:
            target_len = max(1, int(round(len(req.previous.text.split()) / req.previous.ratio)))
        else:
            target_len = len(words)
        filler = ["la", "la", "la"]
        if target_len <= len(words):
            words = words[:target_len]
        else:
            words = words + (filler * target_len)[: target_len - len(words)]
        text = " ".join(words)
        return TranslationResult(text=text, estimated_units=count_units(text, req.target_locale))

    def analyze_document(self, text, source_lang, target_locale) -> DocumentAnalysis:
        return DocumentAnalysis(register="conversational", terms=[])


def dumps_request(req: TranslationRequest) -> str:
    """Représentation stable pour le cache."""
    d = {k: getattr(req, k) for k in ("text", "source_lang", "target_locale", "target_seconds", "max_units",
                                       "register", "prev", "next", "glossary")}
    d["previous"] = req.previous.__dict__ if req.previous else None
    return json.dumps(d, sort_keys=True, ensure_ascii=False)
