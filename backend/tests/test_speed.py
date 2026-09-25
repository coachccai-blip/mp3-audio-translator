"""Optimisations : traduction par lots, débit natif avant time-stretch, débit des voix mémorisé."""
import json
from pathlib import Path

from app.pipeline.fit import RATE_MAX, RATE_MIN, finalize, predicted_rate, take
from app.pipeline.translate import (BATCH_SIZE, TranslationRequest, _BatchOut, _Item, translate_in_batches)
from app.pipeline.tts.mock import MockTTS
from conftest import wait_job


def _synth(tts, voice):
    return lambda text, rate=1.0: tts.synthesize(text, voice, rate)


def test_native_rate_absorbs_mismatch_before_stretch():
    tts = MockTTS(units_per_sec=5.0)
    text = "un deux trois quatre cinq six sept huit neuf dix"
    natural = tts.synthesize(text, "mock:fr-FR-A").duration_ms
    target = natural / 1.10                       # texte 10 % trop long
    t = take(_synth(tts, "mock:fr-FR-A"), text, target)
    assert abs(t.rate - 1.10) < 0.02              # la voix parle plus vite…
    assert abs(t.ratio - 1) < 0.03                # …et tient presque exactement la durée
    r = finalize(t, target, 24000)
    assert abs(r.stretch_ratio - 1) < 0.03        # quasi pas de time-stretch
    assert r.status == "adjusted" and abs(r.final_ms - target) < 1


def test_native_rate_stays_in_natural_range():
    tts = MockTTS(units_per_sec=5.0)
    text = "un deux trois quatre cinq six sept huit neuf dix onze douze"
    natural = tts.synthesize(text, "mock:fr-FR-A").duration_ms
    t = take(_synth(tts, "mock:fr-FR-A"), text, natural / 1.6)
    assert RATE_MIN <= t.rate <= RATE_MAX and t.ratio > 1.3   # trop long : à retraduire, pas à accélérer
    assert predicted_rate(text, "fr-FR", natural, None) == 1.0


def test_batches_cover_all_lines_and_fall_back_on_missing_ids():
    reqs = [TranslationRequest(text=f"line {i}", source_lang="en", target_locale="fr-FR", target_seconds=2,
                               max_units=10) for i in range(BATCH_SIZE + 3)]
    calls = []

    class T:
        def translate(self, req):
            calls.append(("single", req.text))
            from app.pipeline.translate import TranslationResult
            return TranslationResult("seul " + req.text, 2)

    def call(system, user, n):
        calls.append(("batch", n))
        items = [_Item(id=i, translation=f"ligne {i}") for i in range(1, n + 1) if i != 2]  # l'id 2 est « oublié »
        return _BatchOut(items=items)

    out = translate_in_batches(T(), reqs, call)
    assert [c for c in calls if c[0] == "batch"] == [("batch", BATCH_SIZE), ("batch", 3)]
    assert out[1].text == "seul line 1" and out[0].text == "ligne 1"
    assert all(o is not None for o in out)


def test_pipeline_translates_in_few_batched_calls_and_remembers_voice_rate(app_env):
    client, samples, tr = app_env["client"], app_env["samples"], app_env["translator"]
    with open(samples / "sample_fr_interview.mp3", "rb") as fh:
        proj = client.post("/api/projects", files=[("files", ("a.mp3", fh, "audio/mpeg"))]).json()
    client.patch(f"/api/projects/{proj['id']}", json={"targets": ["de-DE"]})
    snap = wait_job(client, client.post(f"/api/projects/{proj['id']}/run").json()["id"])
    assert snap["status"] == "done", snap
    assert 1 <= tr.batch_calls <= 4                     # 1 lot + au plus 3 tours de retraduction groupée
    rates = json.loads((Path(app_env["tmp"]) / "data" / "voice_rates.json").read_text())
    assert rates and all(2 < r < 12 for r in rates.values())


def test_torch_models_run_in_a_separate_reused_process():
    """Demucs/pyannote hors du processus de Whisper (runtimes OpenMP concurrents : Whisper 8× plus lent)."""
    import os

    from app.pipeline import worker

    assert worker.run("syllables.count_units", "Bonjour à tous", "fr-FR") == 4
    pids = set(worker._get_pool()._processes)
    assert pids and os.getpid() not in pids
    worker.run("syllables.count_units", "encore", "fr-FR")
    assert set(worker._get_pool()._processes) == pids  # même processus : modèle gardé en mémoire
