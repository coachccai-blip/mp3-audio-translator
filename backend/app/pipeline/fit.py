"""Ajustement de durée (brief §5.1, étape 9), optimisé vitesse + naturel.

Ordre des leviers, du plus naturel au moins naturel :
  1. débit natif de la voix (le moteur TTS parle un peu plus vite/lentement : 0,90×–1,15×) ;
  2. time-stretch du résidu, sans changement de hauteur (≤ tolérance, 12 % par défaut) ;
  3. retraduction plus courte/longue — faite PAR LOTS par l'appelant (runner), pas phrase par phrase ;
  4. sinon segment « à vérifier » : débordement sur le silence suivant, ou étirement maximal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .audio import resample
from .stretch import stretch_to_length
from .translate import Attempt, TranslationRequest, Translator
from .tts.base import AudioSegment, TTSProvider

MAX_RETRANSLATIONS = 3
RATE_MIN, RATE_MAX = 0.90, 1.15   # plage de débit natif qui reste naturelle

STATUS_OK = "ok"
STATUS_ADJUSTED = "adjusted"
STATUS_REVIEW = "review"
STATUS_ERROR = "error"

Synth = Callable[..., AudioSegment]  # synth(text, rate=1.0)


@dataclass
class Take:
    """Une prise : texte synthétisé, débit natif appliqué, rapport durée obtenue / durée cible."""
    text: str
    seg: AudioSegment
    natural_ms: float      # durée au débit normal (sert aux retraductions et au calibrage)
    rate: float
    ratio: float           # après débit natif
    tts_calls: int


@dataclass
class FitResult:
    text: str
    samples: np.ndarray
    sample_rate: int
    tts_ms: float
    final_ms: float
    stretch_ratio: float
    retranslations: int
    status: str
    tts_calls: int = 0
    rate: float = 1.0
    history: list[dict] = field(default_factory=list)


def take(synth: Synth, text: str, target_ms: float, native_rate: bool = True, rate_threshold: float = 0.03) -> Take:
    first = synth(text, 1.0)
    r0 = first.duration_ms / target_ms
    if native_rate and abs(r0 - 1) > rate_threshold:
        rate = min(RATE_MAX, max(RATE_MIN, r0))
        if abs(rate - 1) > 0.01:
            second = synth(text, rate)
            return Take(text, second, first.duration_ms, rate, second.duration_ms / target_ms, 2)
    return Take(text, first, first.duration_ms, 1.0, r0, 1)


def take_once(synth: Synth, text: str, target_ms: float, rate: float = 1.0) -> Take:
    """Une seule synthèse, au débit prédit (régénération après édition : un seul appel TTS)."""
    rate = min(RATE_MAX, max(RATE_MIN, rate))
    seg = synth(text, rate)
    return Take(text, seg, seg.duration_ms * rate, rate, seg.duration_ms / target_ms, 1)


def predicted_rate(text: str, locale: str, target_ms: float, voice_rate: float | None) -> float:
    """Débit natif à demander, d'après le débit connu de la voix (syllabes ou caractères / s)."""
    from .syllables import count_units

    if not voice_rate or target_ms <= 0:
        return 1.0
    natural_s = count_units(text, locale) / voice_rate
    return min(RATE_MAX, max(RATE_MIN, natural_s / (target_ms / 1000)))


def better(a: Take | None, b: Take) -> Take:
    return b if a is None or abs(b.ratio - 1) < abs(a.ratio - 1) else a


def finalize(t: Take, target_ms: float, sample_rate: int, tolerance: float = 0.12,
             gap_after_ms: float = 0.0, retranslations: int = 0, tts_calls: int | None = None) -> FitResult:
    data = resample(t.seg.samples, t.seg.sample_rate, sample_rate)
    n_tts = len(data)
    n_target = int(round(target_ms * sample_rate / 1000))
    ratio = t.ratio
    if abs(ratio - 1) <= tolerance:
        out = stretch_to_length(data, sample_rate, n_target)
        natural = t.natural_ms / target_ms
        status = STATUS_OK if abs(natural - 1) <= 0.05 else STATUS_ADJUSTED
    elif ratio > 1:
        # Trop long : débordement sur le silence suivant si possible, sinon compression maximale.
        n_allowed = int(round((target_ms + max(gap_after_ms, 0)) * sample_rate / 1000))
        if n_tts <= n_allowed:
            out = data
        else:
            out = stretch_to_length(data, sample_rate, max(int(round(n_tts / (1 + tolerance))), n_allowed))
        status = STATUS_REVIEW
    else:
        out = stretch_to_length(data, sample_rate, int(round(n_tts * (1 + tolerance))))
        status = STATUS_REVIEW
    return FitResult(
        text=t.text, samples=out.astype(np.float32), sample_rate=sample_rate, tts_ms=t.seg.duration_ms,
        final_ms=len(out) * 1000 / sample_rate, stretch_ratio=len(out) / max(n_tts, 1),
        retranslations=retranslations, status=status, tts_calls=tts_calls if tts_calls is not None else t.tts_calls,
        rate=t.rate,
    )


def retranslation_request(req: TranslationRequest, t: Take) -> TranslationRequest:
    natural_ratio = t.natural_ms / (req.target_seconds * 1000)
    return TranslationRequest(**{**req.__dict__, "previous": Attempt(text=t.text, actual_seconds=t.natural_ms / 1000,
                                                                     ratio=natural_ratio)})


def fit_segment(
    request: TranslationRequest,
    first_text: str,
    translator: Translator | None,
    tts: TTSProvider | None,
    voice_id: str,
    target_ms: float,
    sample_rate: int,
    tolerance: float = 0.12,
    gap_after_ms: float = 0.0,
    allow_retranslate: bool = True,
    synth: Synth | None = None,
    native_rate: bool = True,
    rate_threshold: float = 0.03,
) -> FitResult:
    """Ajustement d'un segment isolé (régénération, tests). Le pipeline principal traite par lots."""
    synth = synth or (lambda text, rate=1.0: tts.synthesize_with_retry(text, voice_id, rate))
    best = take(synth, first_text, target_ms, native_rate, rate_threshold)
    calls = best.tts_calls
    history = [{"text": best.text, "tts_ms": round(best.natural_ms), "rate": round(best.rate, 3), "ratio": round(best.ratio, 3)}]
    current = best
    n = 0
    while (allow_retranslate and translator is not None and abs(best.ratio - 1) > tolerance
           and n < MAX_RETRANSLATIONS):
        text = translator.translate(retranslation_request(request, current)).text
        current = take(synth, text, target_ms, native_rate, rate_threshold)
        calls += current.tts_calls
        n += 1
        history.append({"text": text, "tts_ms": round(current.natural_ms), "rate": round(current.rate, 3),
                        "ratio": round(current.ratio, 3)})
        best = better(best, current)
    res = finalize(best, target_ms, sample_rate, tolerance, gap_after_ms, n, calls)
    res.history = history
    return res
