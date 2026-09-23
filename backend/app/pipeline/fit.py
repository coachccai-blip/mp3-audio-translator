"""Boucle d'ajustement de durée (brief §5.1, étape 9).

pour chaque segment :
    synthèse → écart = durée / durée cible
    tant que |écart − 1| > tolérance et itération < 3 : retraduire (plus court / plus long) puis resynthétiser
    si |écart − 1| ≤ tolérance : time-stretch (pitch conservé) à la durée cible exacte
    sinon : segment « à vérifier », on utilise le silence suivant si possible, sinon stretch au max.
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

STATUS_OK = "ok"
STATUS_ADJUSTED = "adjusted"
STATUS_REVIEW = "review"
STATUS_ERROR = "error"


@dataclass
class FitResult:
    text: str
    samples: np.ndarray         # float32 (n, 1) au sample rate demandé
    sample_rate: int
    tts_ms: float               # durée brute de la dernière synthèse
    final_ms: float
    stretch_ratio: float        # durée finale / durée synthèse (1.0 = pas d'étirement)
    retranslations: int
    status: str
    tts_calls: int = 0
    history: list[dict] = field(default_factory=list)


def fit_segment(
    request: TranslationRequest,
    first_text: str,
    translator: Translator | None,
    tts: TTSProvider,
    voice_id: str,
    target_ms: float,
    sample_rate: int,
    tolerance: float = 0.12,
    gap_after_ms: float = 0.0,
    allow_retranslate: bool = True,
    synth: Callable[[str], AudioSegment] | None = None,
) -> FitResult:
    """Ajuste un segment. `synth` permet d'injecter un appel TTS mis en cache."""
    synth = synth or (lambda t: tts.synthesize_with_retry(t, voice_id))
    text = first_text
    seg = synth(text)
    calls = 1
    ratio = seg.duration_ms / target_ms
    history = [{"text": text, "tts_ms": round(seg.duration_ms), "ratio": round(ratio, 3)}]
    iteration = 0
    best_text, best_seg, best_ratio = text, seg, ratio

    while allow_retranslate and translator is not None and abs(ratio - 1) > tolerance and iteration < MAX_RETRANSLATIONS:
        req = TranslationRequest(**{**request.__dict__,
                                    "previous": Attempt(text=text, actual_seconds=seg.duration_ms / 1000, ratio=ratio)})
        text = translator.translate(req).text
        seg = synth(text)
        calls += 1
        ratio = seg.duration_ms / target_ms
        iteration += 1
        history.append({"text": text, "tts_ms": round(seg.duration_ms), "ratio": round(ratio, 3)})
        if abs(ratio - 1) < abs(best_ratio - 1):
            best_text, best_seg, best_ratio = text, seg, ratio

    text, seg, ratio = best_text, best_seg, best_ratio
    data = resample(seg.samples, seg.sample_rate, sample_rate)
    n_tts = len(data)
    n_target = int(round(target_ms * sample_rate / 1000))

    if abs(ratio - 1) <= tolerance:
        out = stretch_to_length(data, sample_rate, n_target)
        status = STATUS_OK if abs(ratio - 1) <= 0.02 else STATUS_ADJUSTED
    elif ratio > 1:
        # Trop long : on déborde sur le silence suivant si possible, sinon compression maximale.
        n_allowed = int(round((target_ms + max(gap_after_ms, 0)) * sample_rate / 1000))
        if n_tts <= n_allowed:
            out = data
        else:
            n_min = int(round(n_tts / (1 + tolerance)))
            out = stretch_to_length(data, sample_rate, max(n_min, n_allowed))
        status = STATUS_REVIEW
    else:
        # Trop court : ralentissement maximal, le reste est du silence.
        out = stretch_to_length(data, sample_rate, int(round(n_tts * (1 + tolerance))))
        status = STATUS_REVIEW

    final_ms = len(out) * 1000 / sample_rate
    return FitResult(
        text=text, samples=out.astype(np.float32), sample_rate=sample_rate, tts_ms=seg.duration_ms,
        final_ms=final_ms, stretch_ratio=len(out) / max(n_tts, 1), retranslations=iteration,
        status=status, tts_calls=calls, history=history,
    )
