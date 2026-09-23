"""Exécution des traitements longs hors du thread HTTP (mode mono-utilisateur)."""
from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from ..config import get_settings
from ..models import AudioFile, Job, Project, select, session
from ..pipeline.runner import Cancelled, Ctx, dub_file, prepare_file
from .catalog import NoNativeVoiceError

PREPARE_STEPS = ["separate", "transcribe", "diarize"]
DUB_STEPS = ["translate", "synthesize", "assemble"]


class JobState:
    def __init__(self, job: Job):
        self.id = job.id
        self.project_id = job.project_id
        self.kind = job.kind
        self.status = "queued"
        self.error: str | None = None
        self.cancel = threading.Event()
        self.files: list[dict] = []
        self.logs: list[str] = []
        self.transcript_preview: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self.result: dict = {}
        self.lock = threading.Lock()

    def progress(self) -> float:
        steps = [s for f in self.files for s in f["steps"]]
        if not steps:
            return 0.0 if self.status != "done" else 1.0
        weight = {"done": 1.0, "error": 1.0, "skipped": 1.0, "running": 0.5}
        total = 0.0
        for s in steps:
            w = weight.get(s["status"], 0.0)
            if s["status"] == "running" and s.get("detail") and "/" in s["detail"]:
                a, b = s["detail"].split("/")
                try:
                    w = int(a) / max(int(b), 1)
                except ValueError:
                    pass
            total += w
        return total / len(steps)

    def snapshot(self) -> dict:
        with self.lock:
            p = self.progress()
            elapsed = (self.finished or time.time()) - self.started
            eta = (elapsed / p - elapsed) if 0.02 < p < 1 and self.status == "running" else None
            return {
                "id": self.id, "project_id": self.project_id, "kind": self.kind, "status": self.status,
                "error": self.error, "progress": round(p, 4), "elapsed_s": round(elapsed, 1),
                "eta_s": round(eta) if eta is not None else None, "files": self.files,
                "logs": self.logs[-200:], "transcript_preview": self.transcript_preview[-30:], "result": self.result,
            }

    def log(self, msg: str):
        with self.lock:
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")


class JobManager:
    def __init__(self):
        self.jobs: dict[str, JobState] = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")

    def get(self, job_id: str) -> JobState | None:
        return self.jobs.get(job_id)

    def latest_for(self, project_id: str) -> JobState | None:
        states = [j for j in self.jobs.values() if j.project_id == project_id]
        return states[-1] if states else None

    def submit(self, project_id: str, kind: str, fn: Callable[[JobState], dict | None]) -> JobState:
        with session() as db:
            job = Job(project_id=project_id, kind=kind, status="queued")
            db.add(job)
            db.commit()
        state = JobState(job)
        self.jobs[job.id] = state

        def run():
            state.status = "running"
            try:
                state.result = fn(state) or {}
                state.status = "cancelled" if state.cancel.is_set() else "done"
            except Cancelled:
                state.status = "cancelled"
                state.log("Traitement annulé.")
            except NoNativeVoiceError as exc:
                state.status, state.error = "error", str(exc)
            except Exception as exc:  # noqa: BLE001
                state.status, state.error = "error", str(exc)
                state.log(traceback.format_exc())
            if state.status in ("error", "cancelled"):
                with state.lock:
                    for f in state.files:
                        for st in f["steps"]:
                            if st["status"] == "running":
                                st["status"] = "error" if state.status == "error" else "pending"
            state.finished = time.time()
            self._persist(state)

        self.pool.submit(run)
        return state

    def _persist(self, state: JobState):
        snap = state.snapshot()
        with session() as db:
            job = db.get(Job, state.id)
            job.status, job.error, job.progress = state.status, state.error, snap["progress"]
            job.steps, job.logs = snap["files"], snap["logs"]
            job.started_at = datetime.fromtimestamp(state.started, timezone.utc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()


manager = JobManager()


def _file_entry(f: AudioFile, locale: str | None, steps: list[str]) -> dict:
    return {"file_id": f.id, "name": f.name, "locale": locale,
            "steps": [{"key": k, "status": "pending", "detail": None, "duration_s": None} for k in steps]}


def _ctx_for(state: JobState, entry: dict) -> Ctx:
    started: dict[str, float] = {}

    def on_step(key, status, detail=None):
        with state.lock:
            for s in entry["steps"]:
                if s["key"] == key:
                    if status == "running" and key not in started:
                        started[key] = time.time()
                    s["status"], s["detail"] = status, detail
                    if status in ("done", "error") and key in started:
                        s["duration_s"] = round(time.time() - started[key], 1)
        if status == "done":
            state.log(f"{entry['name']} · {key} terminé" + (f" ({detail})" if detail else ""))

    def on_text(text):
        with state.lock:
            state.transcript_preview.append(text)

    return Ctx(on_step=on_step, on_log=state.log, on_text=on_text, cancel=state.cancel)


def run_prepare(project_id: str) -> JobState:
    """Séparation + transcription + diarisation (avant l'écran Locuteurs)."""
    def fn(state: JobState):
        project, files = _load(project_id)
        entries = [(f, _file_entry(f, None, PREPARE_STEPS)) for f in files if f.status != "prepared"]
        state.files = [e for _, e in entries]
        _parallel(state, [(lambda f=f, e=e: prepare_file(_ctx_for(state, e), f, project)) for f, e in entries],
                  [e for _, e in entries])
        _set_status(project_id, "prepared")
    return manager.submit(project_id, "prepare", fn)


def run_dub(project_id: str) -> JobState:
    """Traitement complet : préparation si besoin, puis doublage de chaque langue cible."""
    def fn(state: JobState):
        project, files = _load(project_id)
        if not project.targets:
            raise ValueError("Aucune langue cible sélectionnée.")
        from .catalog import get_catalog
        for loc in project.targets:
            get_catalog().voices_for(loc)  # refus explicite si pas de voix native
        _set_status(project_id, "processing")
        tasks, entries = [], []
        for f in files:
            steps = ([] if f.status in ("prepared", "done") else PREPARE_STEPS)
            per_locale = [_file_entry(f, loc, (steps if i == 0 else []) + DUB_STEPS) for i, loc in enumerate(project.targets)]
            entries.extend(per_locale)

            def task(f=f, per_locale=per_locale):
                if f.status not in ("prepared", "done"):
                    prepare_file(_ctx_for(state, per_locale[0]), f, project)
                reports = {}
                for loc, entry in zip(project.targets, per_locale):
                    reports[loc] = dub_file(_ctx_for(state, entry), f, project, loc)
                with session() as db:
                    db.get(AudioFile, f.id).status = "done"
                    db.commit()
                return reports
            tasks.append(task)
        state.files = entries
        results = _parallel(state, tasks, entries)
        _set_status(project_id, "done")
        summary = {"delta_ms": 0.0, "review": 0, "errors": 0}
        for rep in results:
            for r in (rep or {}).values():
                summary["delta_ms"] = max(summary["delta_ms"], abs(r["duration_delta_ms"]))
                summary["review"] += r["counts"].get("review", 0)
                summary["errors"] += r["counts"].get("error", 0)
        return summary
    return manager.submit(project_id, "run", fn)


def _parallel(state: JobState, tasks: list[Callable], entries: list[dict]) -> list:
    """Lots : 2 fichiers traités simultanément par défaut."""
    out = []
    with ThreadPoolExecutor(max_workers=max(1, get_settings().file_concurrency)) as pool:
        futures = [pool.submit(t) for t in tasks]
        for fut in futures:
            out.append(fut.result())
    return out


def _load(project_id: str):
    with session() as db:
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError("Projet introuvable")
        files = db.exec(select(AudioFile).where(AudioFile.project_id == project_id, AudioFile.status != "invalid")).all()
    if not files:
        raise ValueError("Aucun fichier valide dans ce projet.")
    return project, files


def _set_status(project_id: str, status: str):
    with session() as db:
        db.get(Project, project_id).status = status
        db.commit()
