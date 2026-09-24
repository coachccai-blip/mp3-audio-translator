"""Estimation de coût et de temps (affichage transparent, valeurs indicatives)."""
from __future__ import annotations

# Tarifs publics (USD) — À CONFIRMER / mettre à jour selon votre contrat.
CLAUDE_PRICES = {  # $ par million de tokens (entrée, sortie)
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
TTS_PRICE_PER_MCHAR = {"azure": 16.0, "elevenlabs": 180.0, "kokoro": 0.0, "piper": 0.0, "mock": 0.0}  # à confirmer

CHARS_PER_SPOKEN_SECOND = 14.0
TOKENS_PER_SEGMENT_IN = 900     # prompt système + contexte
TOKENS_PER_SEGMENT_OUT = 250    # réponse (+ réflexion légère)
SEGMENT_SECONDS = 6.0
RETRY_FACTOR = 1.35             # retraductions / resynthèses moyennes


def claude_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = CLAUDE_PRICES.get(model, (5.0, 25.0))
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout


def estimate(total_seconds: float, n_targets: int, model: str | None, tts_provider: str, device: str = "cpu") -> dict:
    """model=None : traduction locale gratuite. tts_provider local : voix gratuites."""
    n_seg = max(1, total_seconds / SEGMENT_SECONDS) * n_targets
    chars = total_seconds * CHARS_PER_SPOKEN_SECOND * n_targets * RETRY_FACTOR
    translate = 0.0 if model is None else claude_cost(model, int(n_seg * TOKENS_PER_SEGMENT_IN * RETRY_FACTOR),
                                                      int(n_seg * TOKENS_PER_SEGMENT_OUT * RETRY_FACTOR))
    tts = chars / 1e6 * TTS_PRICE_PER_MCHAR.get(tts_provider, 16.0)
    # Objectifs du brief : 10 min → < 6 min sur GPU, < 15 min sur CPU.
    speed = 0.6 if device in ("cuda", "mps", "gpu") else 1.5
    if model is None:  # le modèle de langage local est plus lent qu'une API
        speed *= 2
    processing = total_seconds * speed * (1 + 0.25 * (n_targets - 1))
    return {"total_seconds": round(total_seconds, 1), "processing_seconds": round(processing),
            "cost_usd": round(translate + tts, 2), "translation_usd": round(translate, 2), "tts_usd": round(tts, 2)}
