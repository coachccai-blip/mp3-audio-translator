"""Orchestration du pipeline par fichier et par langue, avec cache (brief §5, §6.4)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from ..config import get_settings
from ..models import AudioFile, Project, Segment, Speaker, select, session
from ..services.catalog import NoNativeVoiceError, get_catalog
from ..services.cost import TTS_PRICE_PER_MCHAR, claude_cost
from ..services.engines import get_engines
from . import audio as A
from .assemble import PlacedSegment, assemble
from .diarize import assign_speakers
from .fit import (MAX_RETRANSLATIONS, STATUS_ERROR, Take, better, finalize, predicted_rate, retranslation_request,
                  take, take_once)
from .profile import estimate_gender
from .report import build_report
from .separate import Separation
from .syllables import count_units, max_units_for
from .transcribe import TranscriptionUnavailable, Unit, Word
from .translate import Attempt, TranslationError, TranslationRequest, TranslationResult, Translator, dumps_request
from .tts.base import AudioSegment, TTSError

WORK_SR = 24000  # fréquence des segments TTS mis en cache


class Cancelled(Exception):
    pass


@dataclass
class Ctx:
    """Contexte d'exécution : progression, logs, annulation, coûts."""
    on_step: Callable[[str, str, str | None], None] = lambda key, status, detail=None: None
    on_log: Callable[[str], None] = lambda msg: None
    on_text: Callable[[str], None] = lambda text: None
    cancel: threading.Event = field(default_factory=threading.Event)
    tts_chars: dict = field(default_factory=dict)  # fournisseur → caractères synthétisés
    tokens_in: int = 0
    tokens_out: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def cost_usd(self) -> float:
        s = get_settings()
        translation = claude_cost(s.claude_model, self.tokens_in, self.tokens_out) \
            if s.translator_engine == "claude" else 0.0
        return translation + sum(n / 1e6 * TTS_PRICE_PER_MCHAR.get(p, 16.0) for p, n in self.tts_chars.items())


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:20]


def project_dir(project_id: str) -> Path:
    return get_settings().data_dir / "projects" / project_id


def file_dir(f: AudioFile) -> Path:
    return project_dir(f.project_id) / "files" / f.id


def locale_dir(f: AudioFile, locale: str) -> Path:
    return file_dir(f) / locale


# --- Étapes 2 à 5 : préparation ----------------------------------------------

def load_transcript(f: AudioFile) -> list[Unit]:
    p = file_dir(f) / "transcript.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Unit(start=u["start"], end=u["end"], text=u["text"], speaker=u["speaker"],
                 words=[Word(**w) for w in u.get("words", [])]) for u in raw["units"]]


def save_transcript(f: AudioFile, units: list[Unit], language: str | None) -> None:
    p = file_dir(f) / "transcript.json"
    p.write_text(json.dumps({"language": language, "units": [u.to_dict() for u in units]}, ensure_ascii=False),
                 encoding="utf-8")


def separation_of(f: AudioFile) -> Separation | None:
    d = file_dir(f) / "separate"
    v = d / "vocals.wav"
    if not v.exists():
        return None
    b = d / "background.wav"
    return Separation(v, b if b.exists() else None, "cache")


def prepare_file(ctx: Ctx, f: AudioFile, project: Project) -> None:
    eng = get_engines()
    src = Path(f.path)
    ctx.on_step("separate", "running", None)
    sep = eng.separate(src, file_dir(f) / "separate")
    if sep.engine == "none":
        ctx.on_log("Demucs indisponible : pas de séparation voix/fond, le fond sonore ne sera pas conservé.")
        _add_warning(f, "no_separation")
    ctx.on_step("separate", "done", sep.engine)
    ctx.check()

    ctx.on_step("transcribe", "running", None)
    language = project.source_lang if project.settings.get("source_locked") else None
    try:
        # Modèle des Réglages (large-v3 par défaut : le plus rapide mesuré sur processeur, CI Windows 4 cœurs :
        # 38 s contre 79–123 s pour large-v3-turbo). « Précise » force large-v3.
        kwargs = {"model": "large-v3"} if project.settings.get("quality") == "precise" else {}
        tr = eng.transcribe(sep.vocals, language=language, on_unit=ctx.on_text,
                            on_progress=lambda done, total: ctx.on_step("transcribe", "running",
                                                                        f"{int(done)}/{max(int(total), 1)}"),
                            **kwargs)
    except TranscriptionUnavailable as exc:
        raise RuntimeError(str(exc)) from exc
    where = {"cuda": " · carte graphique", "cpu": " · processeur"}.get(getattr(tr, "device", ""), "")
    if getattr(tr, "note", ""):
        ctx.on_log(f"Transcription sur processeur (plus lente) : {tr.note}.")
    ctx.on_step("transcribe", "done", f"{len(tr.units)} segments{where}")
    ctx.check()

    ctx.on_step("diarize", "running", None)
    try:
        turns = eng.diarize(sep.vocals)
    except Exception as exc:  # diarisation facultative : on continue avec un seul locuteur
        ctx.on_log(f"Détection des locuteurs indisponible ({exc}) : un seul locuteur sera utilisé.")
        _add_warning(f, "no_diarization")
        turns = []
    units = assign_speakers(tr.units, turns)
    ctx.on_step("diarize", "done", None)

    vocals, sr = A.load(sep.vocals)
    mono = A.to_mono(vocals)
    by_speaker: dict[str, list[Unit]] = {}
    for u in units:
        by_speaker.setdefault(u.speaker, []).append(u)

    with session() as db:
        for old in db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all():
            db.delete(old)
        catalog = get_catalog()
        for i, (key, us) in enumerate(sorted(by_speaker.items(), key=lambda kv: int(kv[0][1:]))):
            clip = np.concatenate([mono[int(u.start * sr): int(u.end * sr)] for u in us][:20] or [np.zeros(1)])
            gender = estimate_gender(clip, sr)
            voices = {}
            for loc in project.targets:
                try:
                    voices[loc] = catalog.default_voice(loc, gender).id
                except NoNativeVoiceError:
                    pass
            db.add(Speaker(audio_file_id=f.id, key=key, label=f"Locuteur {i + 1}", gender=gender,
                           speech_ms=int(sum(u.end - u.start for u in us) * 1000), voices=voices))
        dbf = db.get(AudioFile, f.id)
        dbf.detected_lang = dbf.detected_lang or tr.language
        dbf.status = "prepared"
        p = db.get(Project, project.id)
        if not p.source_lang:
            p.source_lang = tr.language
        db.commit()
        f.detected_lang, f.status = dbf.detected_lang, dbf.status
        project.source_lang = p.source_lang
    save_transcript(f, units, tr.language)


def _add_warning(f: AudioFile, w: str):
    with session() as db:
        dbf = db.get(AudioFile, f.id)
        if w not in dbf.warnings:
            dbf.warnings = [*dbf.warnings, w]
            db.commit()


# --- Traduction et synthèse (cache) ------------------------------------------

class CachedTranslator:
    def __init__(self, inner: Translator, cache_dir: Path, ctx: Ctx):
        self.inner, self.cache_dir, self.ctx = inner, cache_dir, ctx
        cache_dir.mkdir(parents=True, exist_ok=True)

    def translate(self, req: TranslationRequest) -> TranslationResult:
        p = self.cache_dir / f"{_hash(dumps_request(req))}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return TranslationResult(d["text"], d["estimated_units"])
        before = (getattr(self.inner, "input_tokens", 0), getattr(self.inner, "output_tokens", 0))
        res = self.inner.translate(req)
        with self.ctx.lock:
            self.ctx.tokens_in += getattr(self.inner, "input_tokens", 0) - before[0]
            self.ctx.tokens_out += getattr(self.inner, "output_tokens", 0) - before[1]
        p.write_text(json.dumps({"text": res.text, "estimated_units": res.estimated_units}, ensure_ascii=False),
                     encoding="utf-8")
        return res

    def translate_many(self, reqs: list[TranslationRequest]) -> list[TranslationResult | None]:
        paths = [self.cache_dir / f"{_hash(dumps_request(r))}.json" for r in reqs]
        out: list[TranslationResult | None] = [None] * len(reqs)
        missing = []
        for k, p in enumerate(paths):
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                out[k] = TranslationResult(d["text"], d["estimated_units"])
            else:
                missing.append(k)
        if missing:
            before = (getattr(self.inner, "input_tokens", 0), getattr(self.inner, "output_tokens", 0))
            if hasattr(self.inner, "translate_many"):
                results = self.inner.translate_many([reqs[k] for k in missing])
            else:
                results = [self.inner.translate(reqs[k]) for k in missing]
            with self.ctx.lock:
                self.ctx.tokens_in += getattr(self.inner, "input_tokens", 0) - before[0]
                self.ctx.tokens_out += getattr(self.inner, "output_tokens", 0) - before[1]
            for k, res in zip(missing, results):
                out[k] = res
                if res is not None:
                    paths[k].write_text(json.dumps({"text": res.text, "estimated_units": res.estimated_units},
                                                   ensure_ascii=False), encoding="utf-8")
        return out

    def analyze_document(self, text, source_lang, target_locale):
        return self.inner.analyze_document(text, source_lang, target_locale)


def cached_synth(ctx: Ctx, cache_dir: Path, voice_id: str) -> Callable[[str], AudioSegment]:
    provider_name = voice_id.split(":")[0]
    cache_dir.mkdir(parents=True, exist_ok=True)

    def synth(text: str, rate: float = 1.0) -> AudioSegment:
        rate = round(float(rate), 3)
        p = cache_dir / f"{_hash(provider_name, voice_id, text, rate if rate != 1.0 else None)}.wav"
        if p.exists():
            data, sr = sf.read(str(p), dtype="float32", always_2d=True)
            return AudioSegment(data, sr)
        seg = get_engines().tts(provider_name).synthesize_with_retry(text, voice_id, rate)
        with ctx.lock:
            ctx.tts_chars[provider_name] = ctx.tts_chars.get(provider_name, 0) + len(text)
        sf.write(str(p), seg.samples, seg.sample_rate, subtype="FLOAT")
        return seg

    return synth


def _rates_file() -> Path:
    return get_settings().data_dir / "voice_rates.json"


def known_voice_rates() -> dict[str, float]:
    """Débits mesurés : valeurs livrées (config/voice_rates.json), affinées par les projets de l'utilisateur."""
    from ..config import CONFIG_DIR

    rates: dict[str, float] = {}
    for path in (CONFIG_DIR / "voice_rates.json", _rates_file()):
        try:
            rates.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return rates


def remember_voice_rates(measured: dict[str, float]) -> None:
    """Moyenne glissante du débit de chaque voix, réutilisée par les projets suivants."""
    if not measured:
        return
    try:
        rates = json.loads(_rates_file().read_text(encoding="utf-8"))
    except Exception:
        rates = {}
    defaults = known_voice_rates()
    for v, r in measured.items():
        if v not in rates and v in defaults:
            rates[v] = defaults[v]
        rates[v] = round(0.7 * rates[v] + 0.3 * r, 3) if v in rates else round(r, 3)
    _rates_file().parent.mkdir(parents=True, exist_ok=True)
    _rates_file().write_text(json.dumps(rates, indent=1), encoding="utf-8")


def _request_for(units: list[Unit], i: int, text: str, source_lang: str, locale: str, register: str,
                 glossary: list[tuple[str, str]], voice_rate: float | None = None) -> TranslationRequest:
    catalog = get_catalog()
    info = catalog.locale_info(locale)
    u = units[i]
    secs = u.end - u.start
    rate = voice_rate or info["syllables_per_sec"]
    return TranslationRequest(
        text=text, source_lang=source_lang or "auto", target_locale=locale, target_seconds=secs,
        max_units=max(1, int(secs * rate * 1.05)), target_units=max(1, int(secs * rate * 0.95)),
        count_unit=info["count_unit"],
        register=register, prev=[x.text for x in units[max(0, i - 2): i]], next=[x.text for x in units[i + 1: i + 3]],
        glossary=glossary,
    )


def _doc_analysis(ctx: Ctx, f: AudioFile, project: Project, locale: str, units: list[Unit], translator: Translator):
    p = locale_dir(f, locale) / "document.json"
    register = project.settings.get("register", "auto")
    glossary = [(g["source"], g.get("target", "")) for g in project.settings.get("glossary", []) if g.get("source")]
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
    else:
        full = "\n".join(u.text for u in units)
        try:
            an = translator.analyze_document(full, project.source_lang or "auto", locale)
            d = {"register": an.register, "terms": an.terms}
        except TranslationError as exc:
            ctx.on_log(f"Analyse du document ignorée : {exc}")
            d = {"register": "conversational", "terms": []}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if register == "auto":
        register = d["register"]
    forced = {s for s, _ in glossary}
    glossary = glossary + [tuple(t) for t in d["terms"] if t[0] not in forced]
    return register, glossary


def _voice_for(speaker_voices: dict[str, dict], seg_speaker: str, locale: str, override: str | None) -> str:
    catalog = get_catalog()
    vid = override or speaker_voices.get(seg_speaker, {}).get(locale)
    if vid:
        v = catalog.get_voice(vid)
        if v.locale != locale:
            raise NoNativeVoiceError(locale)
        return vid
    return catalog.default_voice(locale).id


def _native_rate_threshold(voice_id: str, tolerance: float) -> float:
    """Voix locales : ajuster le débit dès 3 % (gratuit). Voix payantes : seulement si le stretch ne suffit pas."""
    from .tts import LOCAL_PROVIDERS

    return 0.03 if voice_id.split(":")[0] in LOCAL_PROVIDERS else tolerance


def _voice_rates(takes: dict[int, Take], units: list, voices: dict[int, str], locale: str) -> dict[str, float]:
    """Débit réel (syllabes ou caractères / s) de chaque voix, mesuré sur les prises déjà synthétisées."""
    samples: dict[str, list[float]] = {}
    for i, t in takes.items():
        n = count_units(t.text, locale)
        if n >= 4 and t.natural_ms > 400:
            samples.setdefault(voices[i], []).append(n / (t.natural_ms / 1000))
    return {v: float(np.median(r)) for v, r in samples.items() if r}


def dub_file(ctx: Ctx, f: AudioFile, project: Project, locale: str) -> dict:
    """Étapes 6 à 12 pour une langue cible.

    Optimisé : traduction PAR LOTS (un appel pour ~12 lignes), débit natif de la voix avant tout time-stretch,
    retraductions regroupées en lots avec un budget calculé sur le débit réellement mesuré de la voix.
    """
    t0 = time.time()
    catalog = get_catalog()
    catalog.voices_for(locale)  # lève NoNativeVoiceError si aucune voix native
    units = load_transcript(f)
    tolerance = float(project.settings.get("stretch_tolerance", 12)) / 100
    with session() as db:
        speakers = db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all()
    speaker_voices = {s.key: s.voices for s in speakers}
    ldir = locale_dir(f, locale)
    translator = CachedTranslator(get_engines().translator(), ldir / "cache" / "translate", ctx)
    duration_s = f.duration_ms / 1000
    n = len(units)

    ctx.on_step("translate", "running", None)
    register, glossary = _doc_analysis(ctx, f, project, locale, units, translator)
    voices = {i: _voice_for(speaker_voices, u.speaker, locale, None) for i, u in enumerate(units)}
    known = known_voice_rates()
    requests = [_request_for(units, i, u.text, project.source_lang, locale, register, glossary, known.get(voices[i]))
                for i, u in enumerate(units)]
    ctx.check()
    first = translator.translate_many(requests)
    errors: dict[int, str] = {i: "Traduction impossible." for i, r in enumerate(first) if r is None}
    ctx.check()
    ctx.on_step("translate", "done", f"{n} segments")

    ctx.on_step("synthesize", "running", f"0/{n}")
    synths = {v: cached_synth(ctx, ldir / "cache" / "tts", v) for v in set(voices.values())}
    targets = {i: (u.end - u.start) * 1000 for i, u in enumerate(units)}
    best: dict[int, Take] = {}
    latest: dict[int, Take] = {}     # dernière prise (base de la retraduction suivante)
    tried: dict[int, set[str]] = {i: set() for i in range(n)}
    retranslations = {i: 0 for i in range(n)}
    done = [0]

    def do_take(i: int, text: str) -> None:
        ctx.check()
        try:
            t = take(synths[voices[i]], text, targets[i], True, _native_rate_threshold(voices[i], tolerance))
            with ctx.lock:
                best[i] = better(best.get(i), t)
                latest[i] = t
                tried[i].add(text)
        except TTSError as exc:
            errors[i] = str(exc)

    def run_parallel(items: list[tuple[int, str]], count: bool) -> None:
        with ThreadPoolExecutor(max_workers=get_settings().tts_concurrency) as pool:
            for _ in pool.map(lambda it: do_take(*it), items):
                if count:
                    with ctx.lock:
                        done[0] += 1
                        ctx.on_step("synthesize", "running", f"{done[0]}/{n}")

    run_parallel([(i, r.text) for i, r in enumerate(first) if r is not None], True)
    ctx.check()

    # Retraductions groupées pour les segments encore hors tolérance.
    for round_no in range(MAX_RETRANSLATIONS):
        bad = [i for i, t in best.items() if abs(t.ratio - 1) > tolerance]
        if not bad:
            break
        ctx.on_log(f"Ajustement {round_no + 1} : retraduction groupée de {len(bad)} segment(s).")
        rates = _voice_rates(best, units, voices, locale)
        reqs = []
        for i in bad:
            req = retranslation_request(requests[i], latest[i])
            rate = rates.get(voices[i])
            if rate:  # budget recalculé sur le débit réellement mesuré de la voix choisie
                secs = targets[i] / 1000
                req.target_units = max(1, int(secs * rate * 0.97))
                req.max_units = max(req.target_units, int(secs * rate * 1.05))
            reqs.append(req)
        results = translator.translate_many(reqs)
        items = [(i, r.text) for i, r in zip(bad, results) if r is not None and r.text not in tried[i]]
        for i, _ in items:
            retranslations[i] += 1
        if not items:
            break
        run_parallel(items, False)
        ctx.check()
    ctx.on_step("synthesize", "done", f"{n}/{n}")
    remember_voice_rates(_voice_rates(best, units, voices, locale))

    seg_dir = ldir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    with session() as db:
        for old in db.exec(select(Segment).where(Segment.audio_file_id == f.id, Segment.locale == locale)).all():
            db.delete(old)
        for i, u in enumerate(units):
            seg = Segment(audio_file_id=f.id, locale=locale, index=i, speaker_key=u.speaker,
                          start_ms=int(round(u.start * 1000)), end_ms=int(round(u.end * 1000)), source_text=u.text)
            t = best.get(i)
            if t is None:
                seg.status, seg.error, seg.target_text = STATUS_ERROR, errors.get(i), (first[i].text if first[i] else "")
            else:
                gap = (units[i + 1].start if i + 1 < n else duration_s) - u.end
                r = finalize(t, targets[i], WORK_SR, tolerance, gap * 1000, retranslations[i])
                path = seg_dir / f"{i:05d}.wav"
                sf.write(str(path), r.samples, WORK_SR, subtype="FLOAT")
                seg.target_text, seg.tts_ms, seg.final_ms = r.text, r.tts_ms, r.final_ms
                seg.stretch_ratio, seg.retranslations, seg.status = round(r.stretch_ratio, 4), r.retranslations, r.status
                seg.audio_path, seg.voice_id = str(path), voices[i]
                seg.history = [{"target_text_edited": None, "voice_override": None, "rate": round(r.rate, 3)}]
                seg.history_pos = 0
            db.add(seg)
        db.commit()

    ctx.on_step("assemble", "running", None)
    report = assemble_file(f, locale, processing_s=time.time() - t0, cost=ctx.cost_usd())
    ctx.on_step("assemble", "done", None)
    return report


# --- Assemblage ----------------------------------------------------------------

def assemble_file(f: AudioFile, locale: str, processing_s: float | None = None, cost: float | None = None) -> dict:
    ldir = locale_dir(f, locale)
    with session() as db:
        segs = db.exec(select(Segment).where(Segment.audio_file_id == f.id, Segment.locale == locale)
                       .order_by(Segment.index)).all()
    original, sr = A.load(Path(f.path))
    n_total = len(original)
    channels = original.shape[1]
    placed = []
    for s in segs:
        if s.audio_path and Path(s.audio_path).exists():
            data, ssr = sf.read(s.audio_path, dtype="float32", always_2d=True)
            placed.append(PlacedSegment(s.start_ms, A.resample(data, ssr, sr)))
    sep = separation_of(f)
    background = None
    if sep and sep.background is not None:
        background, _ = A.load(sep.background, sample_rate=sr, channels=channels)
    project = _project(f.project_id)
    keep_bg = project.settings.get("keep_background", True)
    tracks = assemble(placed, n_total, sr, channels, background if keep_bg else None, f.loudness_lufs)
    ldir.mkdir(parents=True, exist_ok=True)
    for name, data in tracks.items():
        sf.write(str(ldir / f"{name}.wav"), data, sr, subtype="FLOAT")
    peaks_path = ldir / "peaks.json"
    peaks_path.write_text(json.dumps(A.peaks(tracks["mix"])))

    prev = {}
    rp = ldir / "report.json"
    if rp.exists():
        prev = json.loads(rp.read_text(encoding="utf-8"))
    warnings = list(f.warnings)
    output_ms = len(tracks["mix"]) * 1000 / sr
    if abs(output_ms - f.duration_ms) > 50:
        warnings.append("duration_mismatch")
    report = build_report(
        f.name, locale, f.duration_ms, output_ms,
        [{"index": s.index, "start_ms": s.start_ms, "end_ms": s.end_ms, "speaker": s.speaker_key,
          "source_text": s.source_text, "target_text": s.effective_text, "final_ms": s.final_ms,
          "stretch_ratio": s.stretch_ratio, "retranslations": s.retranslations, "status": s.status} for s in segs],
        processing_s if processing_s is not None else prev.get("processing_seconds", 0),
        cost if cost is not None else prev.get("estimated_cost_usd", 0), warnings,
    )
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _project(pid: str) -> Project:
    with session() as db:
        return db.get(Project, pid)


# --- Régénération ciblée ----------------------------------------------------------

def regenerate_segment(seg_id: str, mode: str = "edit", ctx: Ctx | None = None, reassemble: bool = True,
                       rate: float | None = None, record: bool = False) -> Segment:
    """mode : edit (texte édité), shorter, longer, voice (voix changée). Un seul appel TTS pour un texte édité."""
    ctx = ctx or Ctx()
    with session() as db:
        seg = db.get(Segment, seg_id)
        f = db.get(AudioFile, seg.audio_file_id)
        project = db.get(Project, f.project_id)
        speakers = db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all()
    units = load_transcript(f)
    ldir = locale_dir(f, seg.locale)
    voice = _voice_for({s.key: s.voices for s in speakers}, seg.speaker_key, seg.locale, seg.voice_override)
    tolerance = float(project.settings.get("stretch_tolerance", 12)) / 100
    text = seg.effective_text

    if mode in ("shorter", "longer"):
        translator = CachedTranslator(get_engines().translator(), ldir / "cache" / "translate", ctx)
        register, glossary = _doc_analysis(ctx, f, project, seg.locale, units, translator)
        req = _request_for(units, seg.index, seg.source_text, project.source_lang, seg.locale, register, glossary)
        ratio = 1.15 if mode == "shorter" else 0.87
        req.previous = Attempt(text=text, actual_seconds=req.target_seconds * ratio, ratio=ratio)
        text = translator.translate(req).text
        seg.target_text_edited = text

    target_ms = seg.end_ms - seg.start_ms
    nxt = next((u for u in units if u.start * 1000 > seg.start_ms + 1), None)
    gap = (nxt.start * 1000 if nxt else f.duration_ms) - seg.end_ms
    try:
        if rate is None:
            rate = predicted_rate(text, seg.locale, target_ms, known_voice_rates().get(voice))
        t = take_once(cached_synth(ctx, ldir / "cache" / "tts", voice), text, target_ms, rate)
        r = finalize(t, target_ms, WORK_SR, tolerance, gap, seg.retranslations)
        path = ldir / "segments" / f"{seg.index:05d}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), r.samples, WORK_SR, subtype="FLOAT")
        seg.tts_ms, seg.final_ms, seg.stretch_ratio = r.tts_ms, r.final_ms, round(r.stretch_ratio, 4)
        seg.status, seg.audio_path, seg.voice_id, seg.error = r.status, str(path), voice, None
        if record:
            push_history(seg, r.rate)
    except TTSError as exc:
        seg.status, seg.error = STATUS_ERROR, str(exc)

    with session() as db:
        db.merge(seg)
        db.commit()
    if reassemble:
        assemble_file(f, seg.locale)
    return seg


def push_history(seg: Segment, rate: float = 1.0) -> None:
    """Historique annuler/rétablir ; le débit est gardé pour réutiliser le son en cache."""
    state = {"target_text_edited": seg.target_text_edited, "voice_override": seg.voice_override, "rate": round(rate, 3)}
    hist = list(seg.history[: seg.history_pos + 1]) if seg.history else []
    if not hist or hist[-1] != state:
        hist.append(state)
    seg.history, seg.history_pos = hist, len(hist) - 1


def regenerate_speaker(file_id: str, speaker_key: str, locale: str, ctx: Ctx | None = None) -> int:
    """Changement de voix d'un locuteur : seuls ses segments sont régénérés."""
    with session() as db:
        segs = db.exec(select(Segment).where(Segment.audio_file_id == file_id, Segment.locale == locale,
                                             Segment.speaker_key == speaker_key)).all()
        f = db.get(AudioFile, file_id)
    for s in segs:
        if not s.voice_override:
            regenerate_segment(s.id, "voice", ctx, reassemble=False, record=True)
    if segs:
        assemble_file(f, locale)
    return len(segs)


def preview_speaker(file_id: str, speaker_key: str, locale: str, voice_id: str) -> Path:
    """« Écouter un extrait doublé » : synthèse du premier segment du locuteur avec la voix choisie."""
    with session() as db:
        f = db.get(AudioFile, file_id)
        project = db.get(Project, f.project_id)
    units = load_transcript(f)
    idx = next((i for i, u in enumerate(units) if u.speaker == speaker_key), None)
    if idx is None:
        raise ValueError("Aucun segment pour ce locuteur")
    ctx = Ctx()
    ldir = locale_dir(f, locale)
    translator = CachedTranslator(get_engines().translator(), ldir / "cache" / "translate", ctx)
    register, glossary = _doc_analysis(ctx, f, project, locale, units, translator)
    req = _request_for(units, idx, units[idx].text, project.source_lang, locale, register, glossary)
    text = translator.translate(req).text
    seg = cached_synth(ctx, ldir / "cache" / "tts", voice_id)(text)
    out = ldir / "previews" / f"{speaker_key}-{_hash(voice_id, text)}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), seg.samples, seg.sample_rate)
    return out
