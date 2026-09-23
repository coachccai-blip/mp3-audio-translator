"""Modèle de données (brief §6.3) — SQLite via SQLModel."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine, select

from ..config import get_settings


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def JSONField(default: Any = None):
    factory = (lambda: list(default)) if isinstance(default, list) else (lambda: dict(default or {}))
    return Field(default_factory=factory, sa_column=Column(JSON))


class Project(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=_now)
    source_lang: Optional[str] = None
    targets: list = JSONField([])          # locales cibles
    settings: dict = JSONField({})         # registre, glossaire, tolérance, fond…
    status: str = "draft"                  # draft | prepared | processing | done | error


class AudioFile(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str = Field(index=True)
    name: str
    path: str
    duration_ms: int = 0
    format: str = ""
    sample_rate: int = 0
    channels: int = 0
    loudness_lufs: Optional[float] = None
    snr_db: Optional[float] = None
    detected_lang: Optional[str] = None
    is_video: bool = False
    info: dict = JSONField({})
    warnings: list = JSONField([])
    status: str = "ready"                  # ready | invalid | prepared | done | error
    error: Optional[str] = None


class Speaker(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    audio_file_id: str = Field(index=True)
    key: str                               # S1, S2…
    label: str
    gender: str = "unknown"
    speech_ms: int = 0
    voices: dict = JSONField({})           # locale → voice_id


class Segment(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    audio_file_id: str = Field(index=True)
    locale: str = Field(index=True)
    index: int
    speaker_key: str = "S1"
    start_ms: int
    end_ms: int
    source_text: str = ""
    target_text: str = ""
    target_text_edited: Optional[str] = None
    voice_override: Optional[str] = None
    voice_id: Optional[str] = None
    tts_ms: Optional[float] = None
    final_ms: Optional[float] = None
    stretch_ratio: Optional[float] = None
    retranslations: int = 0
    status: str = "pending"                # pending | ok | adjusted | review | error
    audio_path: Optional[str] = None
    history: list = JSONField([])          # [{target_text, voice_override}]
    history_pos: int = -1
    error: Optional[str] = None

    @property
    def effective_text(self) -> str:
        return self.target_text_edited if self.target_text_edited is not None else self.target_text


class Job(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str = Field(index=True)
    kind: str                              # prepare | run | regenerate | export
    status: str = "queued"                 # queued | running | done | error | cancelled
    step: Optional[str] = None
    progress: float = 0.0
    steps: list = JSONField([])
    logs: list = JSONField([])
    error: Optional[str] = None
    eta_s: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class Export(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    project_id: str = Field(index=True)
    format: str
    options: dict = JSONField({})
    paths: list = JSONField([])
    created_at: datetime = Field(default_factory=_now)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        s.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(s.db_url, connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(_engine)
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None


def session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


__all__ = ["Project", "AudioFile", "Speaker", "Segment", "Job", "Export", "session", "select", "get_engine", "reset_engine"]
