"""Critères d'acceptation du brief (§13.1), de bout en bout via l'API."""
import json
from pathlib import Path

import pytest
import soundfile as sf

from app.pipeline import audio as A
from conftest import wait_job

SAMPLES = ["sample_fr_interview.mp3", "sample_en_voiceover.wav", "sample_de_ad.flac"]
TARGET = {"sample_fr_interview.mp3": "de-DE", "sample_en_voiceover.wav": "fr-FR", "sample_de_ad.flac": "es-ES"}


def _create(client, samples, name):
    with open(samples / name, "rb") as fh:
        r = client.post("/api/projects", files=[("files", (name, fh, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, pid, targets):
    r = client.patch(f"/api/projects/{pid}", json={"targets": targets})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/run")
    assert r.status_code == 200, r.text
    snap = wait_job(client, r.json()["id"])
    assert snap["status"] == "done", snap
    return snap


@pytest.mark.parametrize("name", SAMPLES)
def test_duration_format_and_sync(app_env, name):
    client, samples = app_env["client"], app_env["samples"]
    proj = _create(client, samples, name)
    f = proj["files"][0]
    assert f["status"] == "ready"
    loc = TARGET[name]
    _run(client, proj["id"], [loc])

    # Chaque segment commence à ±20 ms de l'horodatage original
    ref = json.loads((samples / (Path(name).stem + ".json")).read_text())["units"]
    segs = client.get(f"/api/files/{f['id']}/segments", params={"locale": loc}).json()
    assert len(segs) == len(ref)
    for s, u in zip(segs, ref):
        assert abs(s["start_ms"] - u["start"] * 1000) <= 20
        # Aucun stretch > 12 % sans statut « à vérifier »
        if s["stretch_ratio"] and abs(s["stretch_ratio"] - 1) > 0.12 + 1e-3:
            assert s["status"] == "review"

    # Export identique à l'original : durée ±50 ms, format, sample rate, canaux
    exp = client.post(f"/api/projects/{proj['id']}/export", json={"format": "original", "subtitles": True, "report": True})
    assert exp.status_code == 200, exp.text
    out = Path(exp.json()["files"][0]["path"])
    assert out.suffix == Path(name).suffix
    src_info, out_info = A.probe(samples / name), A.probe(out)
    assert out_info.sample_rate == src_info.sample_rate
    assert out_info.channels == src_info.channels
    src_data, sr = A.load(samples / name)
    out_data, sr2 = A.load(out)
    assert abs(len(out_data) / sr2 - len(src_data) / sr) * 1000 <= 50
    names = [x["name"] for x in exp.json()["files"]]
    assert any(n.endswith(".srt") for n in names) and any(n.endswith("_rapport.json") for n in names)

    report = client.get(f"/api/files/{f['id']}/report", params={"locale": loc}).json()
    assert report["duration_ok"]


def test_voice_track_starts_at_segment_start(app_env):
    client, samples = app_env["client"], app_env["samples"]
    proj = _create(client, samples, "sample_en_voiceover.wav")
    f = proj["files"][0]
    _run(client, proj["id"], ["fr-FR"])
    data_dir = Path(app_env["tmp"]) / "data" / "projects" / proj["id"] / "files" / f["id"] / "fr-FR"
    voice, sr = sf.read(str(data_dir / "voice.wav"), always_2d=True)
    env = abs(voice[:, 0])
    segs = client.get(f"/api/files/{f['id']}/segments", params={"locale": "fr-FR"}).json()
    for s in segs:
        i = int(s["start_ms"] * sr / 1000)
        before = env[max(0, i - int(0.05 * sr)): max(0, i - int(0.005 * sr))]
        after = env[i: i + int(0.05 * sr)]
        assert after.max() > 0.01
        assert before.size == 0 or before.max() < after.max()


def test_locale_without_native_voice_is_refused(app_env, monkeypatch):
    client, samples = app_env["client"], app_env["samples"]
    proj = _create(client, samples, "sample_de_ad.flac")
    r = client.patch(f"/api/projects/{proj['id']}", json={"targets": ["sv-FI"]})
    assert r.status_code == 422
    assert "Aucune voix native validée pour sv-FI" in r.text
    # Catalogue exigeant des voix validées humainement : aucune n'est encore validée → refus explicite.
    client.patch(f"/api/projects/{proj['id']}", json={"targets": ["fr-FR"]})
    monkeypatch.setenv("DOUBLR_REQUIRE_VALIDATED_VOICES", "true")
    from app import config
    config.reload_settings()
    r = client.post(f"/api/projects/{proj['id']}/run")
    assert r.status_code == 422
    assert client.get("/api/languages").json() == []
    exports = Path(app_env["tmp"]) / "exports"
    assert not exports.exists() or not any(exports.rglob("*.flac"))


def test_edit_segment_single_tts_call(app_env):
    client, samples, tts = app_env["client"], app_env["samples"], app_env["tts"]
    proj = _create(client, samples, "sample_en_voiceover.wav")
    f = proj["files"][0]
    _run(client, proj["id"], ["fr-FR"])
    seg = client.get(f"/api/files/{f['id']}/segments", params={"locale": "fr-FR"}).json()[1]
    before = len(tts.calls)
    r = client.patch(f"/api/segments/{seg['id']}", json={"target_text": "Dans quelques minutes vous apprendrez trois règles."})
    assert r.status_code == 200, r.text
    assert len(tts.calls) - before == 1
    assert r.json()["effective_text"].startswith("Dans quelques")
    assert r.json()["can_undo"]
    # annuler : texte original, pas de nouvel appel TTS (cache)
    before = len(tts.calls)
    r = client.patch(f"/api/segments/{seg['id']}", json={"action": "undo"})
    assert r.json()["target_text_edited"] is None
    assert len(tts.calls) == before


def test_speaker_voice_change_regenerates_only_their_segments(app_env):
    client, samples, tts = app_env["client"], app_env["samples"], app_env["tts"]
    proj = _create(client, samples, "sample_fr_interview.mp3")
    f = proj["files"][0]
    _run(client, proj["id"], ["en-GB"])
    speakers = client.get(f"/api/files/{f['id']}/speakers").json()
    assert len(speakers) == 2
    s2 = next(s for s in speakers if s["key"] == "S2")
    new_voice = next(v["id"] for v in client.get("/api/voices", params={"locale": "en-GB"}).json()
                     if v["id"] != s2["voices"]["en-GB"])
    before = len(tts.calls)
    r = client.patch(f"/api/speakers/{s2['id']}", json={"locale": "en-GB", "voice_id": new_voice, "regenerate": True})
    assert r.status_code == 200, r.text
    n_s2 = sum(1 for s in client.get(f"/api/files/{f['id']}/segments", params={"locale": "en-GB"}).json()
               if s["speaker_key"] == "S2")
    assert r.json()["regenerated"] == n_s2
    new_calls = tts.calls[before:]
    assert new_calls and all(voice == new_voice for _, voice in new_calls)


def test_batch_multi_language(app_env):
    client, samples = app_env["client"], app_env["samples"]
    files = []
    handles = [open(samples / n, "rb") for n in ("sample_en_voiceover.wav", "sample_de_ad.flac")]
    try:
        files = [("files", (Path(h.name).name, h, "application/octet-stream")) for h in handles]
        proj = client.post("/api/projects", files=files).json()
    finally:
        for h in handles:
            h.close()
    snap = _run(client, proj["id"], ["fr-FR", "it-IT", "pl-PL"])
    assert len(snap["files"]) == 6
    exp = client.post(f"/api/projects/{proj['id']}/export", json={"zip": True}).json()
    assert any(x["name"].endswith(".zip") for x in exp["files"])
    assert len(exp["summary"]) == 6


def test_invalid_file_is_reported(app_env, tmp_path):
    client = app_env["client"]
    bad = tmp_path / "broken.mp3"
    bad.write_bytes(b"not audio at all")
    with open(bad, "rb") as fh:
        proj = client.post("/api/projects", files=[("files", ("broken.mp3", fh, "audio/mpeg"))]).json()
    assert proj["files"][0]["status"] == "invalid"
    assert proj["files"][0]["error"]
