"""Fixtures : moteurs factices (pas de modèles lourds ni d'appels réseau)."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def samples_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("samples")
    spec = importlib.util.spec_from_file_location("make_samples", ROOT / "scripts" / "make_samples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(out, out / "stems")
    return out


@pytest.fixture()
def app_env(tmp_path, monkeypatch, samples_dir):
    """Application isolée (base, données, exports dans tmp) avec moteurs factices."""
    monkeypatch.setenv("DOUBLR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOUBLR_OUTPUT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("DOUBLR_TTS_PROVIDER", "azure")
    monkeypatch.setenv("DOUBLR_REQUIRE_VALIDATED_VOICES", "false")
    from app import config
    config.reload_settings()
    from app import models
    models.reset_engine()
    from app.services.catalog import get_catalog
    get_catalog.cache_clear()

    from app.pipeline.separate import Separation
    from app.pipeline.transcribe import Transcript, Unit
    from app.pipeline.translate import EchoTranslator
    from app.pipeline.tts.mock import MockTTS
    from app.pipeline import audio as A
    from app.services import engines as eng_mod

    tts = MockTTS(units_per_sec=5.0)
    translator = EchoTranslator()

    def find_sample(path: Path) -> str:
        # le fichier importé s'appelle original.<ext> ; on retrouve l'échantillon par sa durée
        info = A.probe(path)
        for js in samples_dir.glob("*.json"):
            if abs(info.duration_ms / 1000 - _duration(samples_dir, js.stem)) < 0.2:
                return js.stem
        raise AssertionError("échantillon inconnu")

    def separate(src: Path, out: Path):
        name = find_sample(src)
        out.mkdir(parents=True, exist_ok=True)
        stems = samples_dir / "stems" / name
        data, sr = A.load(stems / "vocals.wav")
        A.save(data, sr, out / "vocals.wav")
        bg, _ = A.load(stems / "background.wav")
        A.save(bg, sr, out / "background.wav")
        (out / "name.txt").write_text(name)
        return Separation(out / "vocals.wav", out / "background.wav", "test")

    def transcribe(path: Path, language=None, on_unit=None, model=None):
        name = (Path(path).parent / "name.txt").read_text()
        d = json.loads((samples_dir / f"{name}.json").read_text())
        units = [Unit(start=u["start"], end=u["end"], text=u["text"], speaker=u["speaker"]) for u in d["units"]]
        for u in units:
            on_unit and on_unit(u.text)
        return Transcript(language=d["language"], language_probability=0.99, units=units)

    def diarize(path: Path):
        name = (Path(path).parent / "name.txt").read_text()
        d = json.loads((samples_dir / f"{name}.json").read_text())
        return [(u["start"], u["end"], u["speaker"]) for u in d["units"]]

    engines = eng_mod.Engines(
        separate=separate, transcribe=transcribe, diarize=diarize,
        detect_language=lambda p: None, translator=lambda: translator, tts=lambda name: tts,
    )
    engines.is_test = True
    eng_mod.set_engines(engines)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield {"client": client, "tts": tts, "translator": translator, "samples": samples_dir, "tmp": tmp_path}
    eng_mod.set_engines(None)


_durations: dict[str, float] = {}


def _duration(samples_dir: Path, name: str) -> float:
    if name not in _durations:
        from app.pipeline import audio as A
        f = next(p for p in samples_dir.glob(f"{name}.*") if p.suffix in (".mp3", ".wav", ".flac"))
        _durations[name] = A.probe(f).duration_ms / 1000
    return _durations[name]


def wait_job(client, job_id: str, timeout: float = 120) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "error", "cancelled"):
            return snap
        time.sleep(0.1)
    raise TimeoutError(job_id)

