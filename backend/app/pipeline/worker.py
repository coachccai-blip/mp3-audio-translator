"""Processus dédié aux modèles PyTorch (Demucs, pyannote).

PyTorch et CTranslate2 (Whisper) embarquent chacun leur runtime OpenMP : dans un même processus,
ils se gênent et Whisper devient jusqu'à 8× plus lent (mesuré sur la CI Windows : 38 s → 323 s).
Les modèles PyTorch tournent donc dans un processus séparé, démarré une fois et réutilisé
(le modèle reste chargé entre deux fichiers).
"""
from __future__ import annotations

import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor

_pool: ProcessPoolExecutor | None = None
_lock = threading.Lock()


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return _pool


def run(function: str, *args):
    """Exécute `app.pipeline.<module>.<fonction>` dans le processus PyTorch et renvoie son résultat."""
    try:
        return _get_pool().submit(_dispatch, function, *args).result()
    except Exception as exc:
        if exc.__class__.__name__ == "BrokenProcessPool":  # processus tombé : on en relance un
            global _pool
            with _lock:
                _pool = None
            return _get_pool().submit(_dispatch, function, *args).result()
        raise


def _dispatch(function: str, *args):
    import importlib

    module, name = function.rsplit(".", 1)
    return getattr(importlib.import_module(f"app.pipeline.{module}"), name)(*args)
