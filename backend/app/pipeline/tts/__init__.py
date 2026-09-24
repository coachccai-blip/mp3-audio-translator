from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider


def get_provider(name: str) -> TTSProvider:
    """Instancie le fournisseur correspondant au préfixe de l'identifiant de voix."""
    if name == "azure":
        from .azure import AzureTTS
        return AzureTTS()
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsTTS
        return ElevenLabsTTS()
    if name == "kokoro":
        from .kokoro import KokoroTTS
        return KokoroTTS()
    if name == "piper":
        from .piper import PiperTTS
        return PiperTTS()
    if name == "mock":
        from .mock import MockTTS
        return MockTTS()
    raise TTSError(f"Fournisseur TTS inconnu : {name}")


LOCAL_PROVIDERS = ("kokoro", "piper")
CLOUD_KEYS = {"azure": "AZURE_SPEECH_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


def provider_available(name: str) -> bool:
    """Une voix n'est proposée que si son moteur est utilisable ici (installé, ou clé renseignée)."""
    import os

    if name in CLOUD_KEYS:
        return bool(os.environ.get(CLOUD_KEYS[name]))
    if name == "kokoro":
        from .kokoro import available
        return available()
    if name == "piper":
        from .piper import available
        return available()
    return name == "mock"


__all__ = ["AudioSegment", "ProviderVoice", "TTSError", "TTSProvider", "get_provider"]
