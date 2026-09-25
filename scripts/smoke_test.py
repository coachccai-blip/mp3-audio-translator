"""Test de bout en bout avec les VRAIS modèles locaux (Demucs, Whisper, pyannote si HF_TOKEN).

Par défaut, tout est réel et gratuit : traduction locale (Ollama), voix locales (Kokoro, Piper).
Avec --mock, traduction et voix sont simulées.

    python scripts/smoke_test.py parole.wav [--to fr-FR --to de-DE] [--mock]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    # La console Windows (cp1252) ne sait pas afficher tous les caractères.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--to", action="append", help="locale cible (répétable), défaut fr-FR")
    ap.add_argument("--mock", action="store_true", help="simuler traduction et voix")
    args = ap.parse_args()

    import os
    tmp = Path(tempfile.mkdtemp(prefix="doublr-smoke-"))
    os.environ["DOUBLR_DATA_DIR"] = str(tmp / "data")
    os.environ["DOUBLR_OUTPUT_DIR"] = str(tmp / "exports")
    from app import config
    config.reload_settings()

    from app.models import AudioFile, Project, session
    from app.pipeline import audio as A
    from app.pipeline import runner
    from app.pipeline.analyze import analyze
    from app.pipeline.diarize import pyannote_available
    from app.pipeline.separate import demucs_available
    from app.pipeline.transcribe import whisper_available
    from app.services import engines as E
    from app.services.export import export_project

    print(f"Modèles : whisper={whisper_available()} demucs={demucs_available()} pyannote={pyannote_available()}")
    if not (whisper_available() and demucs_available()):
        print("ÉCHEC : Whisper et Demucs doivent être installés.")
        return 1
    targets = args.to or ["fr-FR"]
    if args.mock:
        from app.pipeline.translate import EchoTranslator
        from app.pipeline.tts.mock import MockTTS
        base = E.default_engines()
        tts, tr = MockTTS(), EchoTranslator()
        E.set_engines(E.Engines(base.separate, base.transcribe, base.diarize, base.detect_language,
                                lambda: tr, lambda name: tts))

    src = Path(args.audio).resolve()
    project = Project(name=src.stem, targets=targets)
    f = AudioFile(project_id=project.id, name=src.name, path="")
    dest = runner.project_dir(project.id) / "files" / f.id / f"original{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    an = analyze(dest)
    f.path, f.duration_ms, f.format = str(dest), an.info.duration_ms, an.info.format
    f.sample_rate, f.channels, f.loudness_lufs, f.info = an.info.sample_rate, an.info.channels, an.loudness_lufs, an.to_dict()
    with session() as db:
        db.add(project)
        db.add(f)
        db.commit()

    t0 = time.time()
    ts = time.time()
    ctx = runner.Ctx(on_step=lambda k, s, d=None: print(f"  {time.time() - ts:7.1f}s  {k:<11} {s} {d or ''}", flush=True),
                     on_log=lambda m: print(m, flush=True))
    runner.prepare_file(ctx, f, project)
    units = runner.load_transcript(f)
    print(f"Langue détectée : {project.source_lang} — {len(units)} segment(s) en {time.time() - t0:.0f} s")
    for u in units:
        print(f"  [{u.start:6.2f} → {u.end:6.2f}] {u.speaker} : {u.text}")
    if not units:
        print("ÉCHEC : aucune parole transcrite.")
        return 1

    from app.models import Segment, Speaker, select

    with session() as db:
        for sp in db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all():
            print(f"Locuteur {sp.key} ({sp.gender}) → voix {sp.voices}")
    ok = True
    for loc in targets:
        t1 = time.time()
        rep = runner.dub_file(ctx, f, project, loc)
        with session() as db:
            segs = db.exec(select(Segment).where(Segment.audio_file_id == f.id, Segment.locale == loc)).all()
        for sg in segs:
            print(f"  [{loc}] {sg.status:<8} {sg.voice_id} : {sg.effective_text} {('— ' + sg.error) if sg.error else ''}")
        print(f"  [{loc}] {rep['counts']} en {time.time() - t1:.0f} s")
        if rep["counts"].get("error"):
            ok = False
    with session() as db:
        db.get(AudioFile, f.id).status = "done"
        db.commit()
    out = export_project(project.id, "original", {"subtitles": True, "report": True})
    src_data, sr = A.load(src)
    for item in out["summary"]:
        out_data, sr2 = A.load(Path(item["path"]))
        delta = abs(len(out_data) / sr2 - len(src_data) / sr) * 1000
        good = delta <= 50 and sr2 == sr and out_data.shape[1] == src_data.shape[1]
        ok = ok and good
        print(f"Sortie {Path(item['path']).name} : écart {delta:.1f} ms, {sr2} Hz, {out_data.shape[1]} canal(aux) {'OK' if good else 'KO'}")
    print("SUCCÈS" if ok else "ÉCHEC")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
