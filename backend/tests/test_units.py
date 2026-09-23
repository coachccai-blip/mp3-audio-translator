"""Tests unitaires : syllabes, regroupement, locuteurs, stretch, ajustement, assemblage."""
import numpy as np
import pytest

from app.pipeline.assemble import PlacedSegment, assemble, ducking_gain
from app.pipeline.diarize import merge_small_speakers
from app.pipeline.fit import STATUS_REVIEW, fit_segment
from app.pipeline.stretch import stretch_to_length, wsola
from app.pipeline.syllables import count_units
from app.pipeline.transcribe import Unit, Word, group_words
from app.pipeline.translate import EchoTranslator, TranslationRequest, build_system_prompt, build_user_prompt, Attempt
from app.pipeline.tts.mock import MockTTS


def test_count_units():
    assert count_units("Bonjour à tous", "fr-FR") == 4
    assert count_units("你好，世界", "zh-CN") == 4
    assert count_units("Hello world", "en-US") == 3


def test_group_words_never_splits_words_and_respects_bounds():
    words, t = [], 0.0
    for i in range(80):
        w = f" mot{i}" + ("." if i % 17 == 16 else "")
        words.append(Word(t, t + 0.3, w))
        t += 0.35
    units = group_words(words)
    assert "".join(u.text.replace(" ", "") for u in units) == "".join(w.word.strip() for w in words)
    for u in units:
        assert u.end - u.start <= 12.0 + 1e-6
    assert all(u.end - u.start >= 2.0 for u in units[:-1])


def test_merge_small_speakers():
    units = [Unit(0, 5, "a", speaker="A"), Unit(5, 6, "b", speaker="B"), Unit(6, 12, "c", speaker="C")]
    out = merge_small_speakers(units)
    assert {u.speaker for u in out} == {"S1", "S2"}


def _dominant_freq(x, sr):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / sr)[np.argmax(spec)]


@pytest.mark.parametrize("factor", [0.88, 1.12])
def test_stretch_keeps_pitch_and_length(factor):
    sr = 24000
    t = np.arange(sr) / sr
    x = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)[:, None]
    n_target = int(len(x) * factor)
    y = stretch_to_length(x, sr, n_target)
    assert len(y) == n_target
    assert abs(_dominant_freq(y[2000:-2000, 0], sr) - 220) < 5


def test_fit_segment_stays_within_tolerance_or_flags_review():
    tts = MockTTS(units_per_sec=5.0)
    tr = EchoTranslator()
    for text, target_ms in [("un deux trois quatre cinq six", 1500), ("bonjour", 4000),
                            ("ceci est une phrase assez longue pour être compressée", 2500)]:
        req = TranslationRequest(text=text, source_lang="fr", target_locale="fr-FR", target_seconds=target_ms / 1000, max_units=10)
        r = fit_segment(req, text, tr, tts, "mock:fr-FR-A", target_ms, 24000, 0.12, gap_after_ms=300)
        assert abs(r.stretch_ratio - 1) <= 0.12 + 1e-3 or r.status == STATUS_REVIEW
        if r.status != STATUS_REVIEW:
            assert abs(r.final_ms - target_ms) < 1
        assert r.retranslations <= 3


def test_ducking_and_exact_length():
    sr = 16000
    n = sr * 3
    bg = np.full((n, 2), 0.1, dtype=np.float32)
    seg = np.full((sr, 1), 0.2, dtype=np.float32)
    out = assemble([PlacedSegment(1000, seg)], n, sr, 2, bg, None)
    assert out["mix"].shape == (n, 2)
    gain = ducking_gain(np.r_[np.zeros(sr, bool), np.ones(sr, bool), np.zeros(sr, bool)], sr)
    assert gain[int(1.5 * sr)] == pytest.approx(10 ** (-6 / 20), rel=0.02)
    assert gain[int(0.5 * sr)] == pytest.approx(1.0, rel=0.01)


def test_prompts_contain_spec_items():
    req = TranslationRequest(text="Hello", source_lang="en", target_locale="fr-CA", target_seconds=2.0, max_units=9,
                             prev=["a", "b"], next=["c", "d"], glossary=[("Doublr", "")],
                             previous=Attempt("Bonjour à vous tous", 2.6, 1.3))
    sys_p, user_p = build_system_prompt(req), build_user_prompt(req)
    assert "native speaker" in sys_p and "Québec" in sys_p and '"translation"' in sys_p and "Doublr" in sys_p
    assert "2.00 s" in user_p and "9 syllables" in user_p and "Shorten" in user_p and "- a" in user_p and "- c" in user_p
