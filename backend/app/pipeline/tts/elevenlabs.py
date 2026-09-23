"""ElevenLabs (second fournisseur).

Règle voix natives : on n'utilise que des voix de la Voice Library dont la langue ET
l'accent correspondent à la locale ciblée, et le modèle est appelé avec `language_code`.
Endpoints (à revérifier dans la doc ElevenLabs) :
- GET  https://api.elevenlabs.io/v1/shared-voices?language=fr&accent=parisian
- POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_24000
"""
from __future__ import annotations

import os

import httpx
import numpy as np

from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider, native_voice_name

API = "https://api.elevenlabs.io/v1"
MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")  # modèle ; la VOIX reste native
# Accents « natifs » acceptés par locale (valeurs de la Voice Library, À CONFIRMER).
NATIVE_ACCENTS = {
    "fr-FR": ["parisian", "standard", "french"], "fr-CA": ["canadian", "quebecois"],
    "en-US": ["american"], "en-GB": ["british"], "en-AU": ["australian"], "en-IE": ["irish"],
    "de-DE": ["standard", "german"], "de-AT": ["austrian"], "de-CH": ["swiss"],
    "es-ES": ["peninsular", "castilian", "spanish"], "es-MX": ["mexican"], "es-AR": ["argentine", "argentinian"],
    "it-IT": ["standard", "italian"], "pl-PL": ["standard", "polish"], "sv-SE": ["standard", "swedish"],
    "zh-CN": ["standard", "mandarin"], "zh-TW": ["taiwanese"],
}


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    def __init__(self, key: str | None = None, timeout: float = 60.0):
        self.key = key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.timeout = timeout
        if not self.key:
            raise TTSError("Clé ElevenLabs manquante (ELEVENLABS_API_KEY).")

    def list_voices(self, locale: str) -> list[ProviderVoice]:
        lang = locale.split("-")[0]
        r = httpx.get(f"{API}/shared-voices", params={"language": lang, "page_size": 100},
                      headers={"xi-api-key": self.key}, timeout=self.timeout)
        if r.status_code != 200:
            raise TTSError(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
        accents = NATIVE_ACCENTS.get(locale, [])
        out = []
        for v in r.json().get("voices", []):
            if (v.get("accent") or "").lower() not in accents:
                continue
            out.append(ProviderVoice(id=f"elevenlabs:{v['voice_id']}", locale=locale,
                                     display_name=v.get("name", v["voice_id"]), gender=v.get("gender")))
        return out

    def synthesize(self, text, voice_id, rate=1.0, target_duration_ms=None, language_code: str | None = None) -> AudioSegment:
        body = {"text": text, "model_id": MODEL_ID, "voice_settings": {"speed": max(0.7, min(1.2, rate))}}
        if language_code:
            body["language_code"] = language_code
        try:
            r = httpx.post(f"{API}/text-to-speech/{native_voice_name(voice_id)}", params={"output_format": "pcm_24000"},
                           headers={"xi-api-key": self.key}, json=body, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TTSError(f"ElevenLabs injoignable : {exc}") from exc
        if r.status_code != 200:
            raise TTSError(f"ElevenLabs HTTP {r.status_code}: {r.text[:200]}")
        pcm = np.frombuffer(r.content, dtype="<i2").astype(np.float32) / 32768.0
        return AudioSegment(pcm[:, None], 24000)
