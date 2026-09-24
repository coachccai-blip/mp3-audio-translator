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
from .fit import STATUS_ERROR, FitResult, fit_segment
from .profile import estimate_gender
from .report import build_report
from .separate import Separation
from .syllables import max_units_for
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
    ctx.on_step("separate", "done", None)
    ctx.check()

    ctx.on_step("transcribe", "running", None)
    language = project.source_lang if project.settings.get("source_locked") else None
    try:
        kwargs = {"model": "medium"} if project.settings.get("quality") == "fast" else {}
        tr = eng.transcribe(sep.vocals, language=language, on_unit=ctx.on_text, **kwargs)
    except TranscriptionUnavailable as exc:
        raise RuntimeError(str(exc)) from exc
    ctx.on_step("transcribe", "done", f"{len(tr.units)} segments")
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

    def analyze_document(self, text, source_lang, target_locale):
        return self.inner.analyze_document(text, source_lang, target_locale)


def cached_synth(ctx: Ctx, cache_dir: Path, voice_id: str) -> Callable[[str], AudioSegment]:
    provider_name = voice_id.split(":")[0]
    cache_dir.mkdir(parents=True, exist_ok=True)

    def synth(text: str) -> AudioSegment:
        p = cache_dir / f"{_hash(provider_name, voice_id, text)}.wav"
        if p.exists():
            data, sr = sf.read(str(p), dtype="float32", always_2d=True)
            return AudioSegment(data, sr)
        seg = get_engines().tts(provider_name).synthesize_with_retry(text, voice_id)
        with ctx.lock:
            ctx.tts_chars[provider_name] = ctx.tts_chars.get(provider_name, 0) + len(text)
        sf.write(str(p), seg.samples, seg.sample_rate, subtype="FLOAT")
        return seg

    return synth


def _request_for(units: list[Unit], i: int, text: str, source_lang: str, locale: str, register: str,
                 glossary: list[tuple[str, str]]) -> TranslationRequest:
    catalog = get_catalog()
    info = catalog.locale_info(locale)
    u = units[i]
    secs = u.end - u.start
    return TranslationRequest(
        text=text, source_lang=source_lang or "auto", target_locale=locale, target_seconds=secs,
        max_units=max_units_for(secs, info["syllables_per_sec"]), count_unit=info["count_unit"],
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


def dub_file(ctx: Ctx, f: AudioFile, project: Project, locale: str) -> dict:
    """Étapes 6 à 12 pour une langue cible."""
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

    ctx.on_step("translate", "running", None)
    register, glossary = _doc_analysis(ctx, f, project, locale, units, translator)
    requests = [_request_for(units, i, u.text, project.source_lang, locale, register, glossary) for i, u in enumerate(units)]
    first: list[str | None] = [None] * len(units)
    errors: list[str | None] = [None] * len(units)

    def do_translate(i):
        ctx.check()
        try:
            first[i] = translator.translate(requests[i]).text
        except TranslationError as exc:
            errors[i] = str(exc)

    with ThreadPoolExecutor(max_workers=get_settings().tts_concurrency) as pool:
        list(pool.map(do_translate, range(len(units))))
    ctx.check()
    ctx.on_step("translate", "done", f"{len(units)} segments")

    ctx.on_step("synthesize", "running", f"0/{len(units)}")
    done = [0]
    results: list[FitResult | None] = [None] * len(units)
    duration_s = f.duration_ms / 1000

    def do_fit(i):
        ctx.check()
        if first[i] is None:
            return
        u = units[i]
        gap = (units[i + 1].start if i + 1 < len(units) else duration_s) - u.end
        voice = _voice_for(speaker_voices, u.speaker, locale, None)
        try:
            results[i] = fit_segment(requests[i], first[i], translator, None, voice, (u.end - u.start) * 1000,
                                     WORK_SR, tolerance, gap * 1000, synth=cached_synth(ctx, ldir / "cache" / "tts", voice))
            results[i].history.insert(0, {"voice": voice})
        except (TTSError, TranslationError) as exc:
            errors[i] = str(exc)
        with ctx.lock:
            done[0] += 1
            ctx.on_step("synthesize", "running", f"{done[0]}/{len(units)}")

    with ThreadPoolExecutor(max_workers=get_settings().tts_concurrency) as pool:
        list(pool.map(do_fit, range(len(units))))
    ctx.check()
    ctx.on_step("synthesize", "done", f"{len(units)}/{len(units)}")

    seg_dir = ldir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    with session() as db:
        for old in db.exec(select(Segment).where(Segment.audio_file_id == f.id, Segment.locale == locale)).all():
            db.delete(old)
        for i, u in enumerate(units):
            r = results[i]
            seg = Segment(audio_file_id=f.id, locale=locale, index=i, speaker_key=u.speaker,
                          start_ms=int(round(u.start * 1000)), end_ms=int(round(u.end * 1000)), source_text=u.text)
            if r is None:
                seg.status, seg.error, seg.target_text = STATUS_ERROR, errors[i], first[i] or ""
            else:
                path = seg_dir / f"{i:05d}.wav"
                sf.write(str(path), r.samples, WORK_SR, subtype="FLOAT")
                seg.target_text, seg.tts_ms, seg.final_ms = r.text, r.tts_ms, r.final_ms
                seg.stretch_ratio, seg.retranslations, seg.status = round(r.stretch_ratio, 4), r.retranslations, r.status
                seg.audio_path, seg.voice_id = str(path), r.history[0]["voice"]
                seg.history, seg.history_pos = [{"target_text_edited": None, "voice_override": None}], 0
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

def regenerate_segment(seg_id: str, mode: str = "edit", ctx: Ctx | None = None, reassemble: bool = True) -> Segment:
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
        r = fit_segment(TranslationRequest(text=seg.source_text, source_lang="", target_locale=seg.locale,
                                           target_seconds=target_ms / 1000, max_units=0),
                        text, None, None, voice, target_ms, WORK_SR, tolerance, gap,
                        allow_retranslate=False, synth=cached_synth(ctx, ldir / "cache" / "tts", voice))
        path = ldir / "segments" / f"{seg.index:05d}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), r.samples, WORK_SR, subtype="FLOAT")
        seg.tts_ms, seg.final_ms, seg.stretch_ratio = r.tts_ms, r.final_ms, round(r.stretch_ratio, 4)
        seg.status, seg.audio_path, seg.voice_id, seg.error = r.status, str(path), voice, None
    except TTSError as exc:
        seg.status, seg.error = STATUS_ERROR, str(exc)

    with session() as db:
        db.merge(seg)
        db.commit()
    if reassemble:
        assemble_file(f, seg.locale)
    return seg


def push_history(seg: Segment) -> None:
    state = {"target_text_edited": seg.target_text_edited, "voice_override": seg.voice_override}
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
            regenerate_segment(s.id, "voice", ctx, reassemble=False)
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
