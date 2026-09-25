"""Routes REST : projets, fichiers, locuteurs, segments, jobs, exports."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_settings
from ..models import AudioFile, Export, Project, Segment, Speaker, select, session
from ..pipeline import runner
from ..pipeline.analyze import analyze
from ..pipeline.audio import AUDIO_EXTS, VIDEO_EXTS, AudioError, load, peaks
from ..services import jobs as jobs_service
from ..services.catalog import NoNativeVoiceError, get_catalog
from ..services.cost import estimate
from ..services.engines import get_engines
from ..services.export import DEFAULT_TEMPLATE, export_project

router = APIRouter(prefix="/api")


def _project_or_404(pid: str) -> Project:
    with session() as db:
        p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    return p


def _file_or_404(fid: str) -> AudioFile:
    with session() as db:
        f = db.get(AudioFile, fid)
    if not f:
        raise HTTPException(404, "Fichier introuvable")
    return f


def _project_payload(p: Project) -> dict:
    with session() as db:
        files = db.exec(select(AudioFile).where(AudioFile.project_id == p.id)).all()
    return {**p.model_dump(mode="json"), "files": [f.model_dump(mode="json") for f in files]}


# --- Projets ------------------------------------------------------------------

@router.get("/projects")
def list_projects():
    with session() as db:
        projects = db.exec(select(Project).order_by(Project.created_at.desc())).all()
    return [_project_payload(p) for p in projects[:30]]


@router.post("/projects")
async def create_project(files: list[UploadFile] = File(...), name: str = Form("")):
    if not files:
        raise HTTPException(400, "Aucun fichier")
    project = Project(name=name or Path(files[0].filename or "Projet").stem)
    with session() as db:
        db.add(project)
        db.commit()
    for up in files:
        await _store_upload(project, up)
    return _project_payload(project)


@router.post("/projects/{pid}/files")
async def add_files(pid: str, files: list[UploadFile] = File(...)):
    p = _project_or_404(pid)
    for up in files:
        await _store_upload(p, up)
    return _project_payload(p)


async def _store_upload(project: Project, up: UploadFile) -> AudioFile:
    name = Path(up.filename or "audio").name
    f = AudioFile(project_id=project.id, name=name, path="")
    dest_dir = runner.project_dir(project.id) / "files" / f.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original{Path(name).suffix.lower()}"
    with dest.open("wb") as out:
        shutil.copyfileobj(up.file, out)
    f.path = str(dest)
    try:
        if Path(name).suffix.lower() not in AUDIO_EXTS | VIDEO_EXTS:
            raise AudioError("Format non pris en charge. Formats acceptés : MP3, WAV, M4A, AAC, FLAC, OGG, MP4, MOV.")
        an = analyze(dest)
        f.duration_ms, f.format = an.info.duration_ms, an.info.format
        f.sample_rate, f.channels, f.is_video = an.info.sample_rate, an.info.channels, an.info.is_video
        f.loudness_lufs, f.snr_db, f.warnings, f.info = an.loudness_lufs, an.snr_db, an.warnings, an.to_dict()
        try:
            det = get_engines().detect_language(dest)
            if det:
                f.detected_lang = det[0]
        except Exception:  # la détection rapide est optionnelle
            pass
        data, _ = load(dest)
        (dest_dir / "peaks.json").write_text(json.dumps(peaks(data, 400)))
    except AudioError as exc:
        f.status, f.error = "invalid", str(exc)
    with session() as db:
        db.add(f)
        if f.detected_lang and not project.source_lang:
            p = db.get(Project, project.id)
            p.source_lang = f.detected_lang
        db.commit()
    return f


@router.get("/projects/{pid}")
def get_project(pid: str):
    return _project_payload(_project_or_404(pid))


class ProjectPatch(BaseModel):
    name: str | None = None
    source_lang: str | None = None
    targets: list[str] | None = None
    settings: dict | None = None


@router.patch("/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch):
    catalog = get_catalog()
    available = set(catalog.available_locales())
    if body.targets is not None:
        for loc in body.targets:
            if loc not in available:
                raise HTTPException(422, f"Aucune voix native validée pour {loc}")
    with session() as db:
        p = db.get(Project, pid)
        if not p:
            raise HTTPException(404, "Projet introuvable")
        if body.name is not None:
            p.name = body.name
        if body.source_lang is not None:
            p.source_lang = body.source_lang
            p.settings = {**p.settings, "source_locked": True}
        if body.targets is not None:
            p.targets = body.targets
            # compléter les voix par défaut des locuteurs déjà détectés
            files = db.exec(select(AudioFile).where(AudioFile.project_id == pid)).all()
            for f in files:
                for s in db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all():
                    voices = dict(s.voices)
                    for loc in body.targets:
                        voices.setdefault(loc, catalog.default_voice(loc, s.gender).id)
                    s.voices = voices
        if body.settings is not None:
            p.settings = {**p.settings, **body.settings}
        db.commit()
    return _project_payload(_project_or_404(pid))


@router.delete("/projects/{pid}/files/{fid}")
def remove_file(pid: str, fid: str):
    with session() as db:
        f = db.get(AudioFile, fid)
        if f and f.project_id == pid:
            db.delete(f)
            db.commit()
            shutil.rmtree(runner.file_dir(f), ignore_errors=True)
    return _project_payload(_project_or_404(pid))


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    with session() as db:
        p = db.get(Project, pid)
        if p:
            for model in (AudioFile, Export):
                for row in db.exec(select(model).where(model.project_id == pid)).all():
                    db.delete(row)
            db.delete(p)
            db.commit()
    shutil.rmtree(runner.project_dir(pid), ignore_errors=True)
    return {"ok": True}


@router.get("/projects/{pid}/estimate")
def get_estimate(pid: str):
    p = _project_or_404(pid)
    with session() as db:
        files = db.exec(select(AudioFile).where(AudioFile.project_id == pid, AudioFile.status != "invalid")).all()
    s = get_settings()
    provider = "kokoro"
    for loc in p.targets:
        try:
            provider = get_catalog().default_voice(loc).provider
            break
        except NoNativeVoiceError:
            continue
    model = s.claude_model if s.translator_engine == "claude" else None
    return estimate(sum(f.duration_ms for f in files) / 1000, max(1, len(p.targets)), model, provider, s.device)


# --- Jobs -----------------------------------------------------------------------

def missing_requirements() -> list[str]:
    """Ce qui manque pour lancer un doublage avec les réglages actuels (vide = prêt)."""
    if _engines_overridden():
        return []
    s = get_settings()
    if s.translator_engine == "claude":
        return [] if s.has_key("ANTHROPIC_API_KEY") else ["ANTHROPIC_API_KEY"]
    from ..pipeline.translate import ollama_status

    return [] if ollama_status()["model_ready"] else ["LOCAL_LLM"]


def _require_keys(need_translation: bool = True):
    missing = missing_requirements() if need_translation else []
    if missing:
        msg = ("Le traducteur local gratuit n'est pas prêt (Ollama et son modèle). Lancez Doublr avec son raccourci, "
               "ou relancez l'installateur." if missing == ["LOCAL_LLM"]
               else "Clé API manquante : renseignez-la dans Réglages.")
        raise HTTPException(412, {"code": "missing_keys", "keys": missing, "message": msg})


def _engines_overridden() -> bool:
    from ..services import engines

    return engines._engines is not None and getattr(engines._engines, "is_test", False)


@router.post("/projects/{pid}/prepare")
def prepare(pid: str):
    _project_or_404(pid)
    return jobs_service.run_prepare(pid).snapshot()


@router.post("/projects/{pid}/run")
def run(pid: str):
    p = _project_or_404(pid)
    if not p.targets:
        raise HTTPException(422, "Choisissez au moins une langue cible.")
    for loc in p.targets:
        try:
            get_catalog().voices_for(loc)
        except NoNativeVoiceError as exc:
            raise HTTPException(422, str(exc))
    _require_keys()
    return jobs_service.run_dub(pid).snapshot()


@router.get("/projects/{pid}/job")
def latest_job(pid: str):
    return jobs_service.manager.snapshot(project_id=pid)


@router.get("/jobs/{jid}")
def get_job(jid: str):
    snap = jobs_service.manager.snapshot(job_id=jid)
    if snap is None:
        raise HTTPException(404, "Job introuvable")
    return snap


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    st = jobs_service.manager.get(jid)
    if not st:  # traitement d'avant un redémarrage : déjà arrêté
        snap = jobs_service.manager.snapshot(job_id=jid)
        if snap is None:
            raise HTTPException(404, "Job introuvable")
        return snap
    st.cancel.set()
    return st.snapshot()


# --- Locuteurs --------------------------------------------------------------------

@router.get("/files/{fid}/speakers")
def list_speakers(fid: str):
    f = _file_or_404(fid)
    with session() as db:
        speakers = db.exec(select(Speaker).where(Speaker.audio_file_id == fid)).all()
    units = runner.load_transcript(f)
    out = []
    for s in sorted(speakers, key=lambda s: int(s.key[1:])):
        first = next((u for u in units if u.speaker == s.key), None)
        out.append({**s.model_dump(), "first_start_ms": int(first.start * 1000) if first else None,
                    "first_text": first.text if first else None})
    return out


class SpeakerPatch(BaseModel):
    label: str | None = None
    locale: str | None = None
    voice_id: str | None = None
    regenerate: bool = False


@router.patch("/speakers/{sid}")
def patch_speaker(sid: str, body: SpeakerPatch):
    with session() as db:
        s = db.get(Speaker, sid)
        if not s:
            raise HTTPException(404, "Locuteur introuvable")
        if body.label is not None:
            s.label = body.label
        if body.locale and body.voice_id:
            v = get_catalog().get_voice(body.voice_id)
            if v.locale != body.locale:
                raise HTTPException(422, "Cette voix n'est pas native de la locale choisie.")
            s.voices = {**s.voices, body.locale: body.voice_id}
        db.commit()
    regenerated = 0
    if body.regenerate and body.locale:
        regenerated = runner.regenerate_speaker(s.audio_file_id, s.key, body.locale)
    return {**s.model_dump(), "regenerated": regenerated}


class MergeBody(BaseModel):
    source_id: str
    target_id: str


@router.post("/files/{fid}/speakers/merge")
def merge_speakers(fid: str, body: MergeBody):
    f = _file_or_404(fid)
    with session() as db:
        src, dst = db.get(Speaker, body.source_id), db.get(Speaker, body.target_id)
        if not src or not dst:
            raise HTTPException(404, "Locuteur introuvable")
        units = runner.load_transcript(f)
        for u in units:
            if u.speaker == src.key:
                u.speaker = dst.key
        runner.save_transcript(f, units, f.detected_lang)
        for seg in db.exec(select(Segment).where(Segment.audio_file_id == fid, Segment.speaker_key == src.key)).all():
            seg.speaker_key = dst.key
        dst.speech_ms += src.speech_ms
        db.delete(src)
        db.commit()
    return list_speakers(fid)


@router.post("/speakers/{sid}/split")
def split_speaker(sid: str, segment_indexes: list[int]):
    """Scinder : les unités indiquées passent à un nouveau locuteur."""
    with session() as db:
        s = db.get(Speaker, sid)
        if not s:
            raise HTTPException(404, "Locuteur introuvable")
        f = db.get(AudioFile, s.audio_file_id)
        existing = db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all()
        new_key = f"S{max(int(x.key[1:]) for x in existing) + 1}"
        units = runner.load_transcript(f)
        moved = 0
        for i in segment_indexes:
            if 0 <= i < len(units) and units[i].speaker == s.key:
                units[i].speaker = new_key
                moved += int((units[i].end - units[i].start) * 1000)
        runner.save_transcript(f, units, f.detected_lang)
        for seg in db.exec(select(Segment).where(Segment.audio_file_id == f.id)).all():
            if seg.index in segment_indexes and seg.speaker_key == s.key:
                seg.speaker_key = new_key
        s.speech_ms -= moved
        db.add(Speaker(audio_file_id=f.id, key=new_key, label=f"Locuteur {len(existing) + 1}", gender=s.gender,
                       speech_ms=moved, voices=dict(s.voices)))
        db.commit()
    return list_speakers(f.id)


@router.post("/speakers/{sid}/preview")
def speaker_preview(sid: str, locale: str, voice_id: str):
    with session() as db:
        s = db.get(Speaker, sid)
    if not s:
        raise HTTPException(404, "Locuteur introuvable")
    _require_keys()
    try:
        path = runner.preview_speaker(s.audio_file_id, s.key, locale, voice_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Aperçu impossible : {exc}")
    return FileResponse(path, media_type="audio/wav")


# --- Segments ---------------------------------------------------------------------

@router.get("/files/{fid}/segments")
def list_segments(fid: str, locale: str):
    with session() as db:
        segs = db.exec(select(Segment).where(Segment.audio_file_id == fid, Segment.locale == locale)
                       .order_by(Segment.index)).all()
    return [{**s.model_dump(), "effective_text": s.effective_text,
             "can_undo": s.history_pos > 0, "can_redo": s.history_pos < len(s.history) - 1} for s in segs]


class SegmentPatch(BaseModel):
    target_text: str | None = None
    voice_id: str | None = None
    action: str | None = None  # regenerate | shorter | longer | undo | redo | reset


@router.patch("/segments/{sid}")
def patch_segment(sid: str, body: SegmentPatch):
    with session() as db:
        seg = db.get(Segment, sid)
    if not seg:
        raise HTTPException(404, "Segment introuvable")
    mode = "edit"
    rate = None
    if body.action in ("undo", "redo"):
        pos = seg.history_pos + (-1 if body.action == "undo" else 1)
        if not 0 <= pos < len(seg.history):
            raise HTTPException(409, "Rien à annuler / rétablir")
        state = seg.history[pos]
        seg.target_text_edited, seg.voice_override, seg.history_pos = state["target_text_edited"], state["voice_override"], pos
        rate = state.get("rate")
    else:
        if body.target_text is not None:
            seg.target_text_edited = body.target_text if body.target_text != seg.target_text else None
        if body.voice_id is not None:
            if body.voice_id and get_catalog().get_voice(body.voice_id).locale != seg.locale:
                raise HTTPException(422, "Cette voix n'est pas native de la locale choisie.")
            seg.voice_override = body.voice_id or None
            mode = "voice"
        if body.action == "reset":
            seg.target_text_edited, seg.voice_override = None, None
        if body.action in ("shorter", "longer"):
            _require_keys()
            mode = body.action
    with session() as db:
        db.merge(seg)
        db.commit()
    try:
        seg = runner.regenerate_segment(sid, mode, rate=rate, record=body.action not in ("undo", "redo"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Régénération impossible : {exc}")
    with session() as db:
        db.merge(seg)
        db.commit()
    return {**seg.model_dump(), "effective_text": seg.effective_text,
            "can_undo": seg.history_pos > 0, "can_redo": seg.history_pos < len(seg.history) - 1}


# --- Audio -------------------------------------------------------------------------

@router.get("/files/{fid}/audio/original")
def original_audio(fid: str):
    f = _file_or_404(fid)
    return FileResponse(f.path)


@router.get("/files/{fid}/audio/{track}")
def dubbed_audio(fid: str, track: str, locale: str):
    if track not in ("mix", "voice", "background"):
        raise HTTPException(404)
    p = runner.locale_dir(_file_or_404(fid), locale) / f"{track}.wav"
    if not p.exists():
        raise HTTPException(404, "Piste non générée")
    return FileResponse(p, media_type="audio/wav")


@router.get("/segments/{sid}/audio")
def segment_audio(sid: str):
    with session() as db:
        seg = db.get(Segment, sid)
    if not seg or not seg.audio_path:
        raise HTTPException(404)
    return FileResponse(seg.audio_path, media_type="audio/wav")


@router.get("/files/{fid}/peaks")
def file_peaks(fid: str, locale: str | None = None):
    f = _file_or_404(fid)
    p = (runner.locale_dir(f, locale) / "peaks.json") if locale else (runner.file_dir(f) / "peaks.json")
    if not p.exists():
        if locale:
            raise HTTPException(404)
        data, _ = load(Path(f.path))
        p.write_text(json.dumps(peaks(data, 1000)))
    return json.loads(p.read_text())


@router.get("/files/{fid}/report")
def file_report(fid: str, locale: str):
    p = runner.locale_dir(_file_or_404(fid), locale) / "report.json"
    if not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


# --- Export --------------------------------------------------------------------------

class ExportBody(BaseModel):
    format: str = "original"
    voice_only: bool = False
    background_only: bool = False
    subtitles: bool = False
    report: bool = False
    video: bool = True
    template: str = DEFAULT_TEMPLATE
    destination: str | None = None
    zip: bool = False


@router.post("/projects/{pid}/export")
def export(pid: str, body: ExportBody):
    _project_or_404(pid)
    try:
        return export_project(pid, body.format, {"voice_only": body.voice_only, "background_only": body.background_only,
                                                 "subtitles": body.subtitles, "report": body.report, "video": body.video},
                              body.template, body.destination, body.zip)
    except (ValueError, AudioError) as exc:
        raise HTTPException(422, str(exc))


@router.get("/exports/{eid}/files/{name}")
def download_export(eid: str, name: str):
    with session() as db:
        exp = db.get(Export, eid)
    if not exp:
        raise HTTPException(404)
    for p in exp.paths:
        if Path(p).name == name and Path(p).exists():
            return FileResponse(p, filename=name)
    raise HTTPException(404)
