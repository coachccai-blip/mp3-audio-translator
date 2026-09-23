"""Azure Neural TTS via l'API REST.

Doc de référence (à revérifier au moment du déploiement) :
https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
- Liste des voix : GET https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list
- Synthèse : POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1 (SSML)
Le contrôle de débit se fait via <prosody rate>. Un contrôle de durée cible natif n'est pas
utilisé ici (À CONFIRMER dans la doc Azure) : la boucle d'ajustement (fit.py) s'en charge.
"""
from __future__ import annotations

import os
from xml.sax.saxutils import escape

import httpx

from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider, native_voice_name

OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"


class AzureTTS(TTSProvider):
    name = "azure"

    def __init__(self, key: str | None = None, region: str | None = None, timeout: float = 30.0):
        self.key = key or os.environ.get("AZURE_SPEECH_KEY", "")
        self.region = region or os.environ.get("AZURE_SPEECH_REGION", "westeurope")
        self.timeout = timeout
        if not self.key:
            raise TTSError("Clé Azure Speech manquante (AZURE_SPEECH_KEY). Renseignez-la dans Réglages.")

    @property
    def base(self) -> str:
        return f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices"

    def _headers(self) -> dict[str, str]:
        return {"Ocp-Apim-Subscription-Key": self.key, "User-Agent": "doublr"}

    def list_all_voices(self) -> list[dict]:
        r = httpx.get(f"{self.base}/voices/list", headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            raise TTSError(f"Azure voices/list HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def list_voices(self, locale: str) -> list[ProviderVoice]:
        out = []
        for v in self.list_all_voices():
            if v.get("Locale") != locale:
                continue
            short = v.get("ShortName", "")
            # Voix natives uniquement : on exclut les voix multilingues.
            if "Multilingual" in short or v.get("SecondaryLocaleList"):
                continue
            out.append(ProviderVoice(id=f"azure:{short}", locale=locale,
                                     display_name=v.get("DisplayName", short), gender=(v.get("Gender") or "").lower()))
        return out

    @staticmethod
    def build_ssml(text: str, voice: str, rate: float) -> str:
        locale = "-".join(voice.split("-")[:2])
        pct = round((rate - 1.0) * 100)
        rate_attr = f"{pct:+d}%"
        return (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale}'>"
            f"<voice name='{voice}'><prosody rate='{rate_attr}'>{escape(text)}</prosody></voice></speak>"
        )

    def synthesize(self, text, voice_id, rate=1.0, target_duration_ms=None) -> AudioSegment:
        voice = native_voice_name(voice_id)
        headers = {**self._headers(), "Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": OUTPUT_FORMAT}
        try:
            r = httpx.post(f"{self.base}/v1", headers=headers,
                           content=self.build_ssml(text, voice, rate).encode("utf-8"), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TTSError(f"Azure injoignable : {exc}") from exc
        if r.status_code != 200:
            raise TTSError(f"Azure TTS HTTP {r.status_code}: {r.text[:200]}")
        return AudioSegment.from_bytes(r.content)
