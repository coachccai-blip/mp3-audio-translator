"""Sous-titres SRT / VTT."""
from __future__ import annotations


def _ts(ms: float, sep: str) -> str:
    ms = int(round(ms))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(items: list[tuple[float, float, str]]) -> str:
    return "\n".join(f"{i}\n{_ts(a, ',')} --> {_ts(b, ',')}\n{t}\n" for i, (a, b, t) in enumerate(items, 1))


def to_vtt(items: list[tuple[float, float, str]]) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(a, '.')} --> {_ts(b, '.')}\n{t}\n" for a, b, t in items)
