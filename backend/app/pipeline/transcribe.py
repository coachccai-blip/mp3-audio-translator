"""Étape 3 — transcription horodatée (faster-whisper) et regroupement en unités de sens."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

MIN_UNIT_S = 2.0
MAX_UNIT_S = 12.0
PAUSE_BREAK_S = 0.7
_SENTENCE_END = re.compile(r"[.!?…。！？]['\"»”)]*$")
_CLAUSE_END = re.compile(r"[,;:，；：、]['\"»”)]*$")


@dataclass
class Word:
    start: float
    end: float
    word: str


@dataclass
class Unit:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str = "S1"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Transcript:
    language: str
    language_probability: float
    units: list[Unit]
    device: str = ""        # « cuda » ou « cpu » : où Whisper a réellement tourné
    note: str = ""          # raison du repli sur processeur, le cas échéant


class TranscriptionUnavailable(Exception):
    pass


def _join(words: list[Word]) -> str:
    text = "".join(w.word for w in words).strip()
    return re.sub(r"\s+", " ", text)


def group_words(words: list[Word], min_s: float = MIN_UNIT_S, max_s: float = MAX_UNIT_S,
                pause_s: float = PAUSE_BREAK_S) -> list[Unit]:
    """Regroupe les mots en unités de 2 à 12 s, coupées entre deux mots (jamais au milieu)."""
    units: list[Unit] = []
    cur: list[Word] = []

    def flush(ws: list[Word]):
        if ws:
            units.append(Unit(start=ws[0].start, end=ws[-1].end, text=_join(ws), words=list(ws)))

    for i, w in enumerate(words):
        if cur and w.end - cur[0].start > max_s:
            # Couper au meilleur endroit précédent : fin de phrase, puis proposition, puis plus grande pause.
            cut = None
            for pattern in (_SENTENCE_END, _CLAUSE_END):
                for j in range(len(cur) - 1, 0, -1):
                    if pattern.search(cur[j].word.strip()) and cur[j].end - cur[0].start >= min_s:
                        cut = j + 1
                        break
                if cut:
                    break
            if cut is None:
                gaps = [(cur[j + 1].start - cur[j].end, j + 1) for j in range(len(cur) - 1)]
                cut = max(gaps)[1] if gaps else len(cur)
            flush(cur[:cut])
            cur = cur[cut:]
        cur.append(w)
        dur = cur[-1].end - cur[0].start
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt else 0.0
        if dur >= min_s and (_SENTENCE_END.search(w.word.strip()) or gap >= pause_s):
            flush(cur)
            cur = []
        elif nxt is not None and gap >= 2.0:
            # Longue pause : on coupe même si l'unité est courte (on ne fusionne pas à travers un silence).
            flush(cur)
            cur = []
    flush(cur)
    return units


def whisper_available() -> bool:
    # Sans importer CTranslate2 dans le serveur : il ne doit être chargé que dans le processus Whisper.
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def _add_cuda_dlls() -> None:
    """Windows : bibliothèques NVIDIA (cuBLAS, cuDNN 9) installées par pip dans l'environnement.

    CTranslate2 ne les embarque pas ; sans elles, Whisper retombe sur le processeur (très lent).
    Le processus Whisper n'importe jamais PyTorch : pas de conflit avec le cuDNN de PyTorch.
    """
    if os.name != "nt":
        return
    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    dirs = [str(d) for d in sorted(base.glob("*/bin")) if d.is_dir()] if base.is_dir() else []
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])


_gpu_note = ""


@lru_cache(maxsize=2)
def _model(name: str, device: str):
    global _gpu_note
    if device in ("cuda", "auto"):
        _add_cuda_dlls()
    from faster_whisper import WhisperModel

    def make(**kw):
        try:  # modèle déjà téléchargé : pas de requête réseau
            return WhisperModel(name, local_files_only=True, **kw)
        except Exception:
            return WhisperModel(name, **kw)

    if device in ("cuda", "auto"):
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return make(device="cuda", compute_type="float16")
            _gpu_note = "aucune carte graphique NVIDIA utilisable"
        except Exception as exc:  # bibliothèques CUDA absentes ou incompatibles → CPU
            _gpu_note = f"carte graphique inutilisable ({str(exc)[:160]})"
    return make(device="cpu", compute_type="int8")


def _on_gpu(model) -> bool:
    try:
        return model.model.device == "cuda"
    except Exception:
        return False


def transcribe(path: Path, model_name: str = "large-v3", device: str = "auto", language: str | None = None,
               on_unit=None, on_progress=None) -> Transcript:
    """Whisper tourne dans son propre processus (voir worker.py) ; repli sur processeur si la carte plante.

    La progression (texte reconnu, secondes traitées) remonte en direct via un petit fichier.
    """
    if not whisper_available():
        raise TranscriptionUnavailable("faster-whisper n'est pas installé (pip install -e \".[ai]\").")
    from . import worker

    fd, name = tempfile.mkstemp(prefix="doublr-whisper-", suffix=".jsonl")
    os.close(fd)
    progress = Path(name)
    stop = threading.Event()

    def watch():
        pos = 0
        while True:
            finished = stop.wait(1.0)
            try:
                data = progress.read_text(encoding="utf-8")
            except OSError:
                data = ""
            if len(data) < pos:  # relance sur processeur : le fichier repart de zéro
                pos = 0
            end = data.rfind("\n") + 1
            for line in data[pos:end].splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if on_unit and item.get("text"):
                    on_unit(item["text"])
                if on_progress and item.get("duration"):
                    on_progress(float(item["end"]), float(item["duration"]))
            pos = max(pos, end)
            if finished:
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        return worker.run_on_device("transcribe.transcribe_here", str(path), model_name, language, str(progress),
                                    device=device, pool="whisper")
    finally:
        stop.set()
        watcher.join(timeout=5)
        progress.unlink(missing_ok=True)


def transcribe_here(path: str, model_name: str, language: str | None, progress_path: str | None,
                    device: str) -> Transcript:
    model = _model(model_name, device)
    segments = info = None
    if _on_gpu(model):
        # Par lots sur carte graphique uniquement : mesuré 6 fois PLUS LENT sur processeur (CI Windows, 4 cœurs).
        try:
            from faster_whisper import BatchedInferencePipeline

            segments, info = BatchedInferencePipeline(model=model).transcribe(
                str(path), language=language, word_timestamps=True, batch_size=16)
        except Exception:
            segments = None
    if segments is None:
        segments, info = model.transcribe(str(path), language=language, word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    out = open(progress_path, "w", encoding="utf-8") if progress_path else None
    try:
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(start=float(w.start), end=float(w.end), word=w.word))
            if out:
                out.write(json.dumps({"text": seg.text.strip(), "end": float(seg.end),
                                      "duration": float(info.duration)}, ensure_ascii=False) + "\n")
                out.flush()
    finally:
        if out:
            out.close()
    on_gpu = _on_gpu(model)
    return Transcript(language=info.language, language_probability=float(info.language_probability),
                      units=group_words(words), device="cuda" if on_gpu else "cpu",
                      note="" if on_gpu or device == "cpu" else _gpu_note)


def detect_language(path: Path, model_name: str = "large-v3", device: str = "auto") -> tuple[str, float] | None:
    """Détection rapide de la langue source (30 premières secondes)."""
    if not whisper_available():
        return None
    from . import worker

    return worker.run_on_device("transcribe.detect_language_here", str(path), model_name, device=device,
                                pool="whisper")


def detect_language_here(path: str, model_name: str, device: str) -> tuple[str, float]:
    from faster_whisper.audio import decode_audio

    model = _model(model_name, device)
    audio = decode_audio(path, sampling_rate=16000)[: 16000 * 30]
    lang, prob, _ = model.detect_language(audio)
    return lang, float(prob)
