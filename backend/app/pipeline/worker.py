"""Processus dédiés aux modèles lourds : « torch » (Demucs, pyannote) et « whisper » (faster-whisper).

- PyTorch et CTranslate2 (Whisper) embarquent chacun leur runtime OpenMP : dans un même processus,
  ils se gênent et Whisper devient jusqu'à 8× plus lent (mesuré sur la CI Windows : 38 s → 323 s).
- Sur carte NVIDIA, chacun charge aussi sa propre version de cuDNN : mélangées dans un même processus,
  elles font planter Python sans exception (« Could not load symbol cudnnGetLibConfig »).

Chaque moteur tourne donc dans son propre processus, démarré une fois et réutilisé (modèle gardé en
mémoire). Si ce processus plante sur carte graphique, le serveur reste debout et l'étape est relancée
sur processeur ; la carte graphique n'est plus utilisée pour ce moteur jusqu'au redémarrage.
"""
from __future__ import annotations

import logging
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

log = logging.getLogger("doublr.worker")

_pools: dict[str, ProcessPoolExecutor] = {}
_gpu_broken: set[str] = set()
_lock = threading.Lock()


class WorkerCrashed(RuntimeError):
    pass


def _get_pool(pool: str = "torch") -> ProcessPoolExecutor:
    with _lock:
        if pool not in _pools:
            _pools[pool] = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return _pools[pool]


def _reset(pool: str) -> None:
    with _lock:
        old = _pools.pop(pool, None)
    if old is not None:
        old.shutdown(wait=False, cancel_futures=True)


def run(function: str, *args, pool: str = "torch"):
    """Exécute `app.pipeline.<module>.<fonction>` dans le processus `pool` et renvoie son résultat."""
    try:
        return _get_pool(pool).submit(_dispatch, function, *args).result()
    except BrokenProcessPool as exc:
        _reset(pool)
        raise WorkerCrashed(f"Le processus « {pool} » s'est arrêté brutalement.") from exc


def run_on_device(function: str, *args, device: str, pool: str):
    """Comme `run`, le dernier argument étant le périphérique ; repli sur processeur si la carte plante."""
    if device != "cpu" and pool not in _gpu_broken:
        try:
            return run(function, *args, device, pool=pool)
        except WorkerCrashed:
            _gpu_broken.add(pool)
            log.warning("%s a planté sur carte graphique : relance sur processeur.", function)
    try:
        return run(function, *args, "cpu", pool=pool)
    except WorkerCrashed:  # plantage ponctuel : une seconde chance dans un processus neuf
        return run(function, *args, "cpu", pool=pool)


def gpu_broken(pool: str) -> bool:
    return pool in _gpu_broken


def _dispatch(function: str, *args):
    import importlib

    module, name = function.rsplit(".", 1)
    return getattr(importlib.import_module(f"app.pipeline.{module}"), name)(*args)


def _crash_on_gpu(value, device: str):  # tests : simule le plantage natif de cuDNN sur carte graphique
    import os

    if device != "cpu":
        os._exit(127)
    return value
