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
    "en-AU": "Australia", "en-IE": "Ireland", "zh-CN": "Mainland China: Standard Mandarin (Putonghua), Simplified characters only, mainland vocabulary and phrasing",
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
    target_units: int | None = None  # longueur idéale, calculée sur le débit réel de la voix choisie


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
    def translate_many(self, reqs: list[TranslationRequest]) -> list[TranslationResult | None]: ...
    def analyze_document(self, text: str, source_lang: str, target_locale: str) -> DocumentAnalysis: ...


BATCH_SIZE = 12  # lignes par appel : assez pour le contexte, assez peu pour un JSON fiable avec un petit modèle


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


def _unit_word(req: TranslationRequest) -> str:
    return "characters" if req.count_unit == "characters" else "syllables"


def build_batch_system_prompt(req: TranslationRequest) -> str:
    """Consignes communes à un lot de lignes (même langue, registre, glossaire)."""
    base = build_system_prompt(req).split("\n\nRespond with strict JSON only")[0]
    return base + (
        "\n\nYou receive numbered lines of one continuous recording. Translate each line separately "
        "(never merge or split lines), keeping the flow natural across lines.\n"
        f"Each line has a spoken time window and a {_unit_word(req)} budget: aim close to the target, "
        "never above the maximum. Count carefully; rephrase rather than cram.\n"
        'Respond with strict JSON only: {"items": [{"id": <line number>, "translation": "..."}]}'
    )


def build_batch_user_prompt(reqs: list[TranslationRequest], before: list[str], after: list[str]) -> str:
    unit = _unit_word(reqs[0])
    parts = []
    if before:
        parts.append("Previous lines (context, do not translate):\n" + "\n".join(f"- {t}" for t in before[-2:]))
    lines = []
    for i, r in enumerate(reqs, 1):
        target = r.target_units or r.max_units
        line = f"[{i}] ({r.target_seconds:.1f} s, target ~{target} {unit}, max {r.max_units}) {r.text}"
        if r.previous:
            p = r.previous
            have = count_units(p.text, r.target_locale)
            delta = have - target
            verb = f"REMOVE about {delta}" if delta > 0 else f"ADD about {-delta}"
            line += (f"\n    previous translation ({have} {unit}, lasted {p.actual_seconds:.1f} s instead of "
                     f"{r.target_seconds:.1f} s): {p.text}\n    rewrite it with ~{target} {unit}: {verb} {unit}, "
                     "keeping the meaning (drop filler words, use shorter synonyms)" if delta > 0 else
                     f"\n    previous translation ({have} {unit}, lasted {p.actual_seconds:.1f} s instead of "
                     f"{r.target_seconds:.1f} s): {p.text}\n    rewrite it with ~{target} {unit}: {verb} {unit}, "
                     "keeping the meaning (no new information)")
        lines.append(line)
    parts.append("Lines to translate:\n" + "\n".join(lines))
    if after:
        parts.append("Next lines (context, do not translate):\n" + "\n".join(f"- {t}" for t in after[:2]))
    return "\n\n".join(parts)


class _Item(BaseModel):
    id: int
    translation: str


class _BatchOut(BaseModel):
    items: list[_Item]


def translate_in_batches(translator, reqs: list[TranslationRequest], call) -> list[TranslationResult | None]:
    """Découpe en lots, appelle `call(system, user, n)` → _BatchOut ; repli ligne par ligne sur les manques."""
    out: list[TranslationResult | None] = [None] * len(reqs)
    for start in range(0, len(reqs), BATCH_SIZE):
        chunk = reqs[start: start + BATCH_SIZE]
        before = chunk[0].prev
        after = chunk[-1].next
        try:
            res = call(build_batch_system_prompt(chunk[0]), build_batch_user_prompt(chunk, before, after), len(chunk))
            for item in res.items:
                if 1 <= item.id <= len(chunk) and item.translation.strip():
                    text = item.translation.strip().strip('"«»').strip()
                    out[start + item.id - 1] = TranslationResult(text, count_units(text, chunk[0].target_locale))
        except TranslationError:
            pass
        for k in range(start, start + len(chunk)):
            if out[k] is None:  # ligne oubliée par le modèle : traduction individuelle
                try:
                    out[k] = translator.translate(reqs[k])
                except TranslationError:
                    out[k] = None
    return out


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

        # La réflexion (active par défaut) consomme aussi des jetons de sortie : marge large pour ne pas tronquer.
        max_tokens = max(max_tokens, 16000)
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
        if resp.stop_reason == "max_tokens":
            raise TranslationError("Réponse de traduction tronquée (limite de longueur atteinte).")
        if resp.stop_reason == "refusal":
            raise TranslationError("Traduction refusée par le modèle pour ce segment.")
        if resp.parsed_output is None:
            raise TranslationError("Réponse de traduction invalide.")
        return resp.parsed_output

    def translate(self, req: TranslationRequest) -> TranslationResult:
        out = self._parse(build_system_prompt(req), build_user_prompt(req), _TranslationOut)
        text = out.translation.strip()
        return TranslationResult(text=text, estimated_units=count_units(text, req.target_locale))

    def translate_many(self, reqs: list[TranslationRequest]) -> list[TranslationResult | None]:
        return translate_in_batches(self, reqs, lambda sys_p, user, n: self._parse(sys_p, user, _BatchOut, 400 + 250 * n))

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

    def translate_many(self, reqs: list[TranslationRequest]) -> list[TranslationResult | None]:
        self.batch_calls = getattr(self, "batch_calls", 0) + 1
        return [self.translate(r) for r in reqs]

    def analyze_document(self, text, source_lang, target_locale) -> DocumentAnalysis:
        return DocumentAnalysis(register="conversational", terms=[])


def dumps_request(req: TranslationRequest) -> str:
    """Représentation stable pour le cache."""
    d = {k: getattr(req, k) for k in ("text", "source_lang", "target_locale", "target_seconds", "max_units",
                                       "register", "prev", "next", "glossary")}
    d["previous"] = req.previous.__dict__ if req.previous else None
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


# --- Implémentation locale gratuite (Ollama) ------------------------------------

class OllamaTranslator:
    """Traduction gratuite par un modèle de langage open source exécuté localement par Ollama.

    Mêmes consignes que pour Claude (§7.3) ; la sortie JSON est contrainte par un schéma.
    """

    def __init__(self, model: str | None = None, url: str | None = None, timeout: float = 600.0):
        s = get_settings()
        self.model = model or s.local_llm
        self.url = (url or s.ollama_url).rstrip("/")
        self.timeout = timeout
        self.input_tokens = 0
        self.output_tokens = 0

    def _chat(self, system: str, user: str, schema: type[BaseModel], num_predict: int = 512):
        import httpx

        body = {
            "model": self.model, "stream": False, "format": schema.model_json_schema(),
            "keep_alive": "30m",  # garde le modèle en mémoire entre les appels (évite ~10-30 s de rechargement)
            "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": num_predict},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TranslationError(
                f"Traducteur local (Ollama) injoignable sur {self.url} : lancez Doublr avec son raccourci "
                f"ou démarrez « ollama serve ». ({exc})") from exc
        if r.status_code == 404:
            raise TranslationError(f"Modèle local « {self.model} » absent : exécutez « ollama pull {self.model} ».")
        if r.status_code != 200:
            raise TranslationError(f"Ollama HTTP {r.status_code} : {r.text[:200]}")
        data = r.json()
        self.input_tokens += int(data.get("prompt_eval_count") or 0)
        self.output_tokens += int(data.get("eval_count") or 0)
        try:
            return schema.model_validate_json(data["message"]["content"])
        except Exception as exc:
            raise TranslationError(f"Réponse du modèle local invalide : {str(exc)[:200]}") from exc

    def translate(self, req: TranslationRequest) -> TranslationResult:
        out = self._chat(build_system_prompt(req), build_user_prompt(req), _TranslationOut)
        text = out.translation.strip().strip('"«»').strip()
        if not text:
            raise TranslationError("Traduction vide.")
        return TranslationResult(text=text, estimated_units=count_units(text, req.target_locale))

    def translate_many(self, reqs: list[TranslationRequest]) -> list[TranslationResult | None]:
        return translate_in_batches(self, reqs, lambda sys_p, user, n: self._chat(sys_p, user, _BatchOut, 120 + 90 * n))

    def warm_up(self) -> None:
        """Charge le modèle en mémoire en arrière-plan (pendant la transcription) pour gagner ~10-30 s."""
        import httpx

        try:
            httpx.post(f"{self.url}/api/generate", json={"model": self.model, "keep_alive": "30m"}, timeout=120)
        except Exception:
            pass

    def analyze_document(self, text: str, source_lang: str, target_locale: str) -> DocumentAnalysis:
        # Sur processeur, cette analyse coûte autant qu'une traduction : le modèle local déduit le registre
        # du contexte, et les lots donnent la cohérence des termes (le glossaire utilisateur reste appliqué).
        return DocumentAnalysis(register="auto (infer it from the lines)", terms=[])

    def _analyze_document_full(self, text: str, source_lang: str, target_locale: str) -> DocumentAnalysis:
        target = LANG_NAMES.get(target_locale.split("-")[0], target_locale)
        system = (
            "You prepare a transcript for dubbing. Give its speech_register (one of: formal, conversational, "
            f"advertising, educational) and up to 20 recurring proper nouns or key terms with their {target} "
            "translation (empty target = keep untranslated). Respond with JSON only."
        )
        out = self._chat(system, text[:12000], _DocOut, 1024)
        register = out.speech_register if out.speech_register in REGISTERS else "conversational"
        return DocumentAnalysis(register=register, terms=[(t.source, t.target) for t in out.terms])


def claude_code_path() -> str | None:
    """Claude Code (outil officiel d'Anthropic) installé sur ce PC, connecté au compte Claude de l'utilisateur."""
    import shutil
    from pathlib import Path

    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for c in (home / ".local" / "bin" / "claude.exe", home / ".local" / "bin" / "claude",
              Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
        if str(c) and c.exists():
            return str(c)
    return None


NOT_LOGGED_IN = ("Claude n'est pas connecté à votre compte : sur l'accueil de Doublr, cliquez sur "
                 "« Se connecter à mon compte Claude ».")


def run_claude_code(prompt: str, timeout: float = 600) -> str:
    """Envoie un message à Claude Code en mode non interactif (`claude -p`) et renvoie sa réponse texte.

    Utilise l'abonnement Claude (Pro, Max…) de la personne connectée dans Claude Code : pas de clé API.
    """
    import subprocess
    import tempfile

    exe = claude_code_path()
    if not exe:
        raise TranslationError("Claude Code n'est pas installé : sur l'accueil de Doublr, cliquez sur "
                               "« Se connecter à mon compte Claude ».")
    # Sans clé API dans l'environnement : Claude Code utilise alors le compte Claude connecté.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    with tempfile.TemporaryDirectory(prefix="doublr-claude-") as cwd:  # dossier vide : rien à lire ni modifier
        try:
            proc = subprocess.run([exe, "-p", "--output-format", "json"], input=prompt, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, env=env,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise TranslationError("Claude Code ne répond pas (délai dépassé).") from exc
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = None
    if not isinstance(out, dict):
        detail = (proc.stderr or proc.stdout or "").strip()[-300:]
        if "login" in detail.lower() or "log in" in detail.lower() or "auth" in detail.lower():
            raise TranslationError(NOT_LOGGED_IN)
        raise TranslationError(f"Claude Code a échoué : {detail or f'code {proc.returncode}'}")
    result = str(out.get("result") or "")
    if out.get("is_error") or proc.returncode != 0:
        low = result.lower()
        if "login" in low or "api key" in low or "authenticat" in low:
            raise TranslationError(NOT_LOGGED_IN)
        raise TranslationError(f"Claude Code : {result[:300] or 'erreur inconnue'}")
    return result


class ClaudeCodeTranslator(ClaudeTranslator):
    """Traduction par Claude avec le compte Claude de l'utilisateur, via Claude Code installé localement."""

    def __init__(self):
        self.model = "claude-code"
        self.client = None
        self.input_tokens = 0
        self.output_tokens = 0

    def _parse(self, system: str, user: str, schema: type[BaseModel], max_tokens: int = 4000):
        prompt = (f"{system}\n\nRespond with ONLY one JSON object (no markdown fence, no commentary, no tool use) "
                  f"that validates against this JSON Schema:\n{json.dumps(schema.model_json_schema())}\n\n{user}")
        last = ""
        for _ in range(2):  # une seconde chance si la réponse n'est pas du JSON valide
            text = run_claude_code(prompt)
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                try:
                    return schema.model_validate_json(text[start: end + 1])
                except ValueError as exc:
                    last = str(exc)[:200]
        raise TranslationError(f"Réponse de traduction invalide ({last or 'pas de JSON'}).")


def make_translator() -> Translator:
    """Traducteur selon les réglages : Claude (clé API ou compte via Claude Code), sinon local gratuit."""
    engine = get_settings().translator_engine
    if engine == "claude":
        return ClaudeTranslator()
    if engine == "claude-code":
        return ClaudeCodeTranslator()
    return OllamaTranslator()


def ollama_status() -> dict:
    """État du traducteur local : serveur Ollama joignable et modèle téléchargé."""
    import httpx

    s = get_settings()
    try:
        r = httpx.get(f"{s.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
        names = [m.get("name", "") for m in r.json().get("models", [])] if r.status_code == 200 else []
    except Exception:
        return {"running": False, "model": s.local_llm, "model_ready": False}
    want = s.local_llm if ":" in s.local_llm else f"{s.local_llm}:latest"
    return {"running": True, "model": s.local_llm, "model_ready": want in names}
