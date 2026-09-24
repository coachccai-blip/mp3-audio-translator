"""Mode gratuit : voix locales (Kokoro, Piper), traduction locale (Ollama), aucune clé requise."""
import json

import httpx
import pytest

from app import config
from app.pipeline import tts as tts_pkg
from app.pipeline.translate import OllamaTranslator, TranslationRequest, make_translator
from app.services.catalog import Catalog, NoNativeVoiceError


@pytest.fixture()
def catalog(monkeypatch, tmp_path):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DOUBLR_REQUIRE_VALIDATED_VOICES", "false")
    config.reload_settings()
    return Catalog(config.CONFIG_DIR / "languages.yaml", config.CONFIG_DIR / "voices.yaml")


def _only(monkeypatch, *providers):
    monkeypatch.setattr(tts_pkg, "provider_available", lambda name: name in providers)


def test_free_mode_offers_only_local_native_voices(catalog, monkeypatch):
    _only(monkeypatch, "kokoro", "piper")
    locales = set(catalog.available_locales())
    # Les 8 langues restent disponibles gratuitement…
    assert {"fr-FR", "en-US", "en-GB", "zh-CN", "de-DE", "sv-SE", "es-ES", "it-IT", "pl-PL"} <= locales
    # …mais une variante sans voix native gratuite est masquée, jamais doublée avec un accent.
    assert not {"fr-CA", "de-AT", "zh-TW", "en-AU"} & locales
    with pytest.raises(NoNativeVoiceError):
        catalog.voices_for("fr-CA")
    for loc in locales:
        assert all(v.free for v in catalog.voices_for(loc))
    assert len(catalog.voices_for("en-US")) >= 25


def test_default_voice_prefers_hd_then_cloud_when_key(catalog, monkeypatch):
    _only(monkeypatch, "kokoro", "piper")
    assert catalog.default_voice("fr-FR", "female").provider == "kokoro"
    assert catalog.default_voice("de-DE", "male").id == "piper:de_DE-thorsten-high"
    _only(monkeypatch, "kokoro", "piper", "azure")
    assert catalog.default_voice("fr-FR", "female").provider == "azure"


def test_no_catalog_voice_is_multilingual_or_multispeaker(catalog):
    banned = ("multilingual", "libritts", "vctk", "arctic", "mls", "upmc", "sharvard")
    for voices in catalog.voices.values():
        for v in voices:
            assert not any(b in v.id.lower() for b in banned), v.id


def test_translator_is_local_without_key(catalog):
    assert isinstance(make_translator(), OllamaTranslator)


def test_ollama_translator_uses_json_schema(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, body=json)
        content = '{"translation": "Bonjour à tous", "estimated_syllables": 4}'
        return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 50, "eval_count": 9})

    monkeypatch.setattr(httpx, "post", fake_post)
    tr = OllamaTranslator(model="gemma3:4b", url="http://127.0.0.1:11434")
    req = TranslationRequest(text="Hello everyone", source_lang="en", target_locale="fr-FR", target_seconds=1.2, max_units=6)
    res = tr.translate(req)
    assert res.text == "Bonjour à tous"
    assert sent["url"].endswith("/api/chat") and sent["body"]["model"] == "gemma3:4b"
    assert sent["body"]["format"]["properties"]["translation"]["type"] == "string"
    assert "native speaker of French" in sent["body"]["messages"][0]["content"]
    assert tr.input_tokens == 50


def test_run_is_refused_clearly_when_local_translator_missing(app_env, monkeypatch):
    client = app_env["client"]
    from app.services import engines
    monkeypatch.setattr(engines._engines, "is_test", False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    config.reload_settings()
    with open(app_env["samples"] / "sample_de_ad.flac", "rb") as fh:
        proj = client.post("/api/projects", files=[("files", ("a.flac", fh, "audio/flac"))]).json()
    client.patch(f"/api/projects/{proj['id']}", json={"targets": ["fr-FR"]})
    r = client.post(f"/api/projects/{proj['id']}/run")
    assert r.status_code == 412
    assert r.json()["detail"]["keys"] == ["LOCAL_LLM"]
    assert client.get("/api/settings").json()["missing"] == ["LOCAL_LLM"]
    est = client.get(f"/api/projects/{proj['id']}/estimate").json()
    assert est["translation_usd"] == 0


@pytest.mark.skipif(not (config.get_settings().models_dir / "kokoro" / "kokoro-v1.0.onnx").exists(),
                    reason="modèle Kokoro non téléchargé")
@pytest.mark.parametrize("voice,text", [("kokoro:ff_siwis", "Bonjour à tous et bienvenue."),
                                        ("kokoro:zf_xiaoxiao", "欢迎大家。")])
def test_kokoro_real_synthesis(voice, text):
    pytest.importorskip("kokoro_onnx", reason="Kokoro non installé")
    from app.pipeline.tts.kokoro import KokoroTTS

    seg = KokoroTTS().synthesize(text, voice)
    assert seg.sample_rate == 24000 and 0.5 < seg.duration_ms / 1000 < 6
    assert float(abs(seg.samples).max()) > 0.05
