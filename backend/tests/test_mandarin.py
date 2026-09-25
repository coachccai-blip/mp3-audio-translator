"""Chinois mandarin (Chine continentale) : prononciation native avec Kokoro, consignes de traduction."""
import numpy as np
import pytest

from app.pipeline.translate import REGION_HINTS


class _FakeKokoro:
    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed=1.0, lang="en-us", is_phonemes=False):
        self.calls.append((text, lang, is_phonemes))
        return np.zeros(2400, dtype=np.float32), 24000


def test_kokoro_uses_official_mandarin_converter(monkeypatch):
    pytest.importorskip("misaki.zh")
    from app.pipeline.tts import kokoro

    fake = _FakeKokoro()
    monkeypatch.setattr(kokoro, "_load", lambda: fake)
    monkeypatch.setattr(kokoro, "available", lambda: True)
    kokoro.KokoroTTS().synthesize("今天我们学习三条安全规则。", "kokoro:zf_xiaoxiao")
    text, lang, is_phonemes = fake.calls[-1]
    assert lang == "cmn" and is_phonemes and "↗" in text      # pinyin avec tons, pas les caractères bruts


def test_kokoro_falls_back_to_espeak_without_converter(monkeypatch):
    from app.pipeline.tts import kokoro

    fake = _FakeKokoro()
    monkeypatch.setattr(kokoro, "_load", lambda: fake)
    monkeypatch.setattr(kokoro, "available", lambda: True)
    monkeypatch.setattr(kokoro, "_mandarin_phonemes", lambda text: None)
    kokoro.KokoroTTS().synthesize("你好。", "kokoro:zf_xiaoxiao")
    assert fake.calls[-1] == ("你好。", "cmn", False)


def test_mainland_mandarin_is_the_default_and_explicit():
    from app.services.catalog import get_catalog

    assert get_catalog().languages["zh"]["default_locale"] == "zh-CN"
    assert "Putonghua" in REGION_HINTS["zh-CN"] and "Simplified" in REGION_HINTS["zh-CN"]
