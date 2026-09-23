"""Routes : langues, catalogue de voix, échantillons."""
from __future__ import annotations

import hashlib

import soundfile as sf
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import ROOT_DIR, get_settings
from ..services.catalog import NoNativeVoiceError, get_catalog
from ..services.engines import get_engines

router = APIRouter(prefix="/api")

SAMPLE_TEXT = {
    "fr": "Bonjour, je serai votre voix pour ce projet. Écoutez comme je parle naturellement.",
    "en": "Hello, I'll be your voice for this project. Listen to how naturally I speak.",
    "zh": "你好，我将为这个项目配音。听听我说话有多自然。",
    "de": "Hallo, ich bin Ihre Stimme für dieses Projekt. Hören Sie, wie natürlich ich spreche.",
    "sv": "Hej, jag blir din röst i det här projektet. Lyssna på hur naturligt jag pratar.",
    "es": "Hola, seré tu voz para este proyecto. Escucha lo natural que hablo.",
    "it": "Ciao, sarò la tua voce per questo progetto. Ascolta quanto parlo in modo naturale.",
    "pl": "Dzień dobry, będę Twoim głosem w tym projekcie. Posłuchaj, jak naturalnie mówię.",
}


@router.get("/languages")
def languages():
    return get_catalog().languages_payload()


@router.get("/voices")
def voices(locale: str | None = None, include_disabled: bool = False):
    catalog = get_catalog()
    if locale:
        try:
            vs = catalog.voices_for(locale) if not include_disabled else catalog.voices.get(locale, [])
        except NoNativeVoiceError as exc:
            raise HTTPException(422, str(exc))
        return [v.to_dict() for v in vs]
    return {loc: [v.to_dict() for v in vs] for loc, vs in catalog.voices.items()}


@router.get("/voices/{voice_id}/sample")
def voice_sample(voice_id: str):
    catalog = get_catalog()
    try:
        v = catalog.get_voice(voice_id)
    except KeyError:
        raise HTTPException(404, "Voix inconnue")
    if v.sample and (ROOT_DIR / v.sample).exists():
        return FileResponse(ROOT_DIR / v.sample)
    cache = get_settings().data_dir / "voice_samples" / f"{hashlib.sha1(voice_id.encode()).hexdigest()[:16]}.wav"
    if not cache.exists():
        try:
            seg = get_engines().tts(v.provider).synthesize_with_retry(SAMPLE_TEXT[v.locale.split("-")[0]], voice_id, attempts=2)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Échantillon indisponible : {exc}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(cache), seg.samples, seg.sample_rate)
    return FileResponse(cache, media_type="audio/wav")


class VoiceToggle(BaseModel):
    disabled: bool


@router.patch("/voices/{voice_id}")
def toggle_voice(voice_id: str, body: VoiceToggle):
    try:
        get_catalog().set_disabled(voice_id, body.disabled)
    except KeyError:
        raise HTTPException(404, "Voix inconnue")
    return get_catalog().get_voice(voice_id).to_dict()
