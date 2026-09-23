from .base import AudioSegment, ProviderVoice, TTSError, TTSProvider


def get_provider(name: str) -> TTSProvider:
    """Instancie le fournisseur correspondant au préfixe de l'identifiant de voix."""
    if name == "azure":
        from .azure import AzureTTS
        return AzureTTS()
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsTTS
        return ElevenLabsTTS()
    if name == "mock":
        from .mock import MockTTS
        return MockTTS()
    raise TTSError(f"Fournisseur TTS inconnu : {name}")


__all__ = ["AudioSegment", "ProviderVoice", "TTSError", "TTSProvider", "get_provider"]
