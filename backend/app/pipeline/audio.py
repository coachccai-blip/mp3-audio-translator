"""Lecture, écriture et conversion audio.

Représentation interne : tableau numpy float32 de forme (n_échantillons, n_canaux).
FFmpeg est utilisé pour les formats compressés (binaire système ou celui d'imageio-ffmpeg).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".mov"}
SOUNDFILE_EXTS = {".wav", ".flac", ".ogg"}


class AudioError(Exception):
    pass


@dataclass
class AudioInfo:
    format: str          # extension sans point : mp3, wav…
    codec: str
    sample_rate: int
    channels: int
    duration_ms: int
    subtype: str | None = None    # sous-type PCM pour WAV/FLAC (PCM_16, PCM_24…)
    bitrate_kbps: int | None = None
    is_video: bool = False


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise AudioError("FFmpeg est introuvable. Installez-le (brew/apt/winget) ou `pip install imageio-ffmpeg`.") from exc


def _run(args: list[str], input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=input_bytes, capture_output=True, check=False)


_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+).*?, (\d+) Hz, ([^,]+)")
_BITRATE_RE = re.compile(r"Audio:.*?(\d+) kb/s")
_DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")


def _channels_from_layout(layout: str) -> int:
    layout = layout.strip()
    named = {"mono": 1, "stereo": 2, "2.1": 3, "quad": 4, "5.0": 5, "5.1": 6, "7.1": 8}
    for key, n in named.items():
        if layout.startswith(key):
            return n
    m = re.match(r"(\d+) channels", layout)
    return int(m.group(1)) if m else 2


def probe(path: Path) -> AudioInfo:
    path = Path(path)
    ext = path.suffix.lower()
    if not path.exists():
        raise AudioError(f"Fichier introuvable : {path.name}")
    if ext in SOUNDFILE_EXTS:
        try:
            info = sf.info(str(path))
            return AudioInfo(
                format=ext[1:], codec=info.format, sample_rate=info.samplerate, channels=info.channels,
                duration_ms=int(round(info.frames * 1000 / info.samplerate)), subtype=info.subtype,
            )
        except Exception:
            pass
    proc = _run([ffmpeg_exe(), "-hide_banner", "-i", str(path)])
    err = proc.stderr.decode("utf-8", "replace")
    m = _STREAM_RE.search(err)
    if not m:
        raise AudioError(f"Fichier illisible ou sans piste audio : {path.name}")
    codec, sr, layout = m.group(1), int(m.group(2)), m.group(3)
    br = _BITRATE_RE.search(err)
    d = _DURATION_RE.search(err)
    duration_ms = 0
    if d:
        duration_ms = int(round((int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) * 1000))
    return AudioInfo(
        format=ext[1:], codec=codec, sample_rate=sr, channels=_channels_from_layout(layout),
        duration_ms=duration_ms, bitrate_kbps=int(br.group(1)) if br else None, is_video=ext in VIDEO_EXTS,
    )


def load(path: Path, sample_rate: int | None = None, channels: int | None = None) -> tuple[np.ndarray, int]:
    """Charge un fichier audio en float32 (n, ch). Rééchantillonne/mixe si demandé."""
    path = Path(path)
    data: np.ndarray | None = None
    sr = 0
    if path.suffix.lower() in SOUNDFILE_EXTS:
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception:
            data = None
    if data is None:
        info = probe(path)
        sr = info.sample_rate
        proc = _run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn",
                     "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sr), "-ac", str(info.channels), "-"])
        if proc.returncode != 0:
            raise AudioError(f"Décodage impossible : {proc.stderr.decode('utf-8', 'replace')[-300:]}")
        data = np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, info.channels).copy()
    if sample_rate and sample_rate != sr:
        data = resample(data, sr, sample_rate)
        sr = sample_rate
    if channels:
        data = set_channels(data, channels)
    return data, sr


def resample(data: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to:
        return data
    g = gcd(sr_from, sr_to)
    out = resample_poly(data, sr_to // g, sr_from // g, axis=0)
    return out.astype(np.float32)


def set_channels(data: np.ndarray, channels: int) -> np.ndarray:
    if data.ndim == 1:
        data = data[:, None]
    cur = data.shape[1]
    if cur == channels:
        return data
    mono = data.mean(axis=1, keepdims=True)
    return np.repeat(mono, channels, axis=1).astype(np.float32)


def to_mono(data: np.ndarray) -> np.ndarray:
    return data.mean(axis=1) if data.ndim == 2 else data


def fit_length(data: np.ndarray, n: int) -> np.ndarray:
    if len(data) == n:
        return data
    if len(data) > n:
        return data[:n]
    pad = np.zeros((n - len(data),) + data.shape[1:], dtype=data.dtype)
    return np.concatenate([data, pad])


def duration_ms(data: np.ndarray, sr: int) -> float:
    return len(data) * 1000.0 / sr


# --- Export -----------------------------------------------------------------

EXPORT_FORMATS = {
    # clé : (extension, arguments ffmpeg)
    "mp3_320": ("mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    "wav_16": ("wav", None),
    "wav_24": ("wav", None),
    "aac": ("m4a", ["-c:a", "aac", "-b:a", "256k"]),
    "flac": ("flac", None),
}


def save(data: np.ndarray, sr: int, path: Path, like: AudioInfo | None = None, fmt: str | None = None) -> Path:
    """Écrit `data` dans `path`. `like` = conserver le format de l'original ; `fmt` = format explicite."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(data, -1.0, 1.0).astype(np.float32)
    ext = path.suffix.lower()

    if fmt == "wav_16" or (fmt is None and ext == ".wav" and (like is None or like.subtype in (None, "PCM_16"))):
        sf.write(str(path), data, sr, subtype="PCM_16")
        return path
    if fmt == "wav_24" or (fmt is None and ext == ".wav"):
        subtype = "PCM_24" if fmt == "wav_24" else (like.subtype if like and like.subtype else "PCM_24")
        sf.write(str(path), data, sr, subtype=subtype)
        return path
    if ext == ".flac":
        subtype = like.subtype if like and like.subtype in ("PCM_16", "PCM_24") else "PCM_16"
        sf.write(str(path), data, sr, subtype=subtype, format="FLAC")
        return path

    if fmt and fmt in EXPORT_FORMATS and EXPORT_FORMATS[fmt][1]:
        codec_args = EXPORT_FORMATS[fmt][1]
    elif ext == ".mp3":
        kbps = (like.bitrate_kbps if like and like.bitrate_kbps else 192)
        codec_args = ["-c:a", "libmp3lame", "-b:a", f"{kbps}k"]
    elif ext in (".m4a", ".aac", ".mp4", ".mov"):
        kbps = (like.bitrate_kbps if like and like.bitrate_kbps else 192)
        codec_args = ["-c:a", "aac", "-b:a", f"{kbps}k"]
    elif ext == ".ogg":
        codec_args = ["-c:a", "libvorbis", "-q:a", "6"]
    else:
        raise AudioError(f"Format d'export non supporté : {ext}")

    if ext in (".mp4", ".mov"):
        path = path.with_suffix(".m4a")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        sf.write(str(tmp_path), data, sr, subtype="FLOAT")
        proc = _run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp_path),
                     *codec_args, "-ar", str(sr), "-ac", str(data.shape[1] if data.ndim == 2 else 1), str(path)])
        if proc.returncode != 0:
            raise AudioError(f"Export FFmpeg échoué : {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    finally:
        tmp_path.unlink(missing_ok=True)
    return path


def replace_video_audio(video: Path, audio: Path, out: Path) -> Path:
    proc = _run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio),
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)])
    if proc.returncode != 0:
        raise AudioError(f"Réinjection vidéo échouée : {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    return out


def peaks(data: np.ndarray, n_bins: int = 1000) -> list[float]:
    """Pics normalisés (0–1) pour dessiner une forme d'onde côté frontend."""
    mono = np.abs(to_mono(data))
    if len(mono) == 0:
        return [0.0] * n_bins
    edges = np.linspace(0, len(mono), n_bins + 1).astype(int)
    out = [float(mono[a:b].max()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    top = max(out) or 1.0
    return [round(v / top, 3) for v in out]
