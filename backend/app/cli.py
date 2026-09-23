"""Doublage en ligne de commande (tranche verticale sans interface).

    python -m app.cli dub episode.mp3 --to de-DE [--to es-ES] [--out exports/] [--voice azure:de-DE-KatjaNeural]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from .models import AudioFile, Project, session
from .pipeline import runner
from .pipeline.analyze import analyze
from .services.catalog import NoNativeVoiceError, get_catalog
from .services.export import export_project


def _print_step(prefix):
    def on_step(key, status, detail=None):
        if status in ("running", "done"):
            print(f"  {prefix} {key:<11} {status}{' · ' + detail if detail else ''}", flush=True)
    return on_step


def cmd_dub(args) -> int:
    src = Path(args.input).resolve()
    catalog = get_catalog()
    try:
        for loc in args.to:
            catalog.voices_for(loc)
    except NoNativeVoiceError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    project = Project(name=src.stem, targets=args.to, settings={"stretch_tolerance": args.tolerance,
                                                                 "keep_background": not args.no_background})
    if args.source:
        project.source_lang = args.source
        project.settings["source_locked"] = True
    f = AudioFile(project_id=project.id, name=src.name, path="")
    dest = runner.project_dir(project.id) / "files" / f.id / f"original{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    an = analyze(dest)
    f.path, f.duration_ms, f.format = str(dest), an.info.duration_ms, an.info.format
    f.sample_rate, f.channels, f.loudness_lufs, f.info, f.warnings = (an.info.sample_rate, an.info.channels,
                                                                      an.loudness_lufs, an.to_dict(), an.warnings)
    if "noisy" in an.warnings:
        print("Attention : audio bruité, la transcription risque d'être dégradée.")
    with session() as db:
        db.add(project)
        db.add(f)
        db.commit()
    t0 = time.time()
    ctx = runner.Ctx(on_step=_print_step("·"), on_log=lambda m: print("  ", m))
    runner.prepare_file(ctx, f, project)
    if args.voice:
        from .models import Speaker, select
        with session() as db:
            for s in db.exec(select(Speaker).where(Speaker.audio_file_id == f.id)).all():
                s.voices = {**s.voices, **{catalog.get_voice(v).locale: v for v in args.voice}}
            db.commit()
    for loc in args.to:
        print(f"→ {loc}")
        rep = runner.dub_file(runner.Ctx(on_step=_print_step("·")), f, project, loc)
        print(f"  durée {rep['output_duration_ms']} ms (écart {rep['duration_delta_ms']} ms) · {rep['counts']}")
    with session() as db:
        db.get(AudioFile, f.id).status = "done"
        db.commit()
    out = export_project(project.id, "original", {"subtitles": True, "report": True}, destination=args.out)
    print(f"Terminé en {time.time() - t0:.0f} s. Fichiers :")
    for x in out["files"]:
        print("  ", x["path"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="doublr")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dub", help="Doubler un fichier audio")
    d.add_argument("input")
    d.add_argument("--to", action="append", required=True, help="Locale cible (répétable), ex. de-DE")
    d.add_argument("--source", help="Langue source (sinon détectée)")
    d.add_argument("--voice", action="append", help="Voix à utiliser (id du catalogue)")
    d.add_argument("--out", help="Dossier de sortie")
    d.add_argument("--tolerance", type=float, default=12, help="Tolérance de stretch en %% (5–12)")
    d.add_argument("--no-background", action="store_true")
    args = ap.parse_args(argv)
    return cmd_dub(args)


if __name__ == "__main__":
    raise SystemExit(main())
