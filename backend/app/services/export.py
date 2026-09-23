"""Écran 6 — export des pistes, sous-titres, rapports, vidéo."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import soundfile as sf

from ..config import get_settings
from ..models import AudioFile, Export, Project, Segment, select, session
from ..pipeline import audio as A
from ..pipeline.report import report_pdf
from ..pipeline.runner import load_transcript, locale_dir
from ..pipeline.subtitles import to_srt, to_vtt

DEFAULT_TEMPLATE = "{nom}_{locale}.{ext}"


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", name).strip() or "export"


def render_name(template: str, nom: str, locale: str, ext: str, suffix: str = "") -> str:
    base = (template or DEFAULT_TEMPLATE).replace("{ext}", "__EXT__")
    base = base.replace("{nom}", nom).replace("{locale}", locale).replace("{langue}", locale.split("-")[0])
    if suffix:
        base = base.replace(".__EXT__", f"_{suffix}.__EXT__")
    return _safe(base.replace("__EXT__", ext))


def export_project(project_id: str, fmt: str = "original", options: dict | None = None,
                   template: str = DEFAULT_TEMPLATE, destination: str | None = None, zip_all: bool = False) -> dict:
    options = options or {}
    with session() as db:
        project = db.get(Project, project_id)
        files = db.exec(select(AudioFile).where(AudioFile.project_id == project_id, AudioFile.status == "done")).all()
    if not files:
        raise ValueError("Rien à exporter : aucun fichier doublé.")
    out_dir = Path(destination) if destination else get_settings().output_dir / _safe(project.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    summary = []

    for f in files:
        info = A.AudioInfo(**{k: f.info[k] for k in A.AudioInfo.__dataclass_fields__ if k in f.info})
        nom = Path(f.name).stem
        for loc in project.targets:
            ldir = locale_dir(f, loc)
            mix_path = ldir / "mix.wav"
            if not mix_path.exists():
                continue
            if fmt == "original":
                ext = "m4a" if info.is_video else info.format
                explicit = None
            else:
                ext, explicit = A.EXPORT_FORMATS[fmt][0], fmt

            def write(track: str, suffix: str = "") -> Path:
                data, sr = sf.read(str(ldir / f"{track}.wav"), dtype="float32", always_2d=True)
                return A.save(data, sr, out_dir / render_name(template, nom, loc, ext, suffix), like=info, fmt=explicit)

            main = write("mix")
            written.append(main)
            out_data, out_sr = sf.read(str(ldir / "mix.wav"), frames=-1, dtype="float32", always_2d=True)
            summary.append({"file": f.name, "locale": loc, "path": str(main),
                            "delta_ms": round(len(out_data) * 1000 / out_sr - f.duration_ms, 1)})
            if options.get("voice_only"):
                written.append(write("voice", "voix"))
            if options.get("background_only") and (ldir / "background.wav").exists():
                written.append(write("background", "fond"))
            if options.get("subtitles"):
                with session() as db:
                    segs = db.exec(select(Segment).where(Segment.audio_file_id == f.id, Segment.locale == loc)
                                   .order_by(Segment.index)).all()
                items = [(s.start_ms, s.end_ms, s.effective_text) for s in segs]
                src_items = [(u.start * 1000, u.end * 1000, u.text) for u in load_transcript(f)]
                for kind, fn in (("srt", to_srt), ("vtt", to_vtt)):
                    p = out_dir / render_name(template, nom, loc, kind)
                    p.write_text(fn(items), encoding="utf-8")
                    written.append(p)
                    ps = out_dir / render_name(template, nom, f.detected_lang or "source", kind)
                    if not ps.exists():
                        ps.write_text(fn(src_items), encoding="utf-8")
                        written.append(ps)
            if options.get("report"):
                report = json.loads((ldir / "report.json").read_text(encoding="utf-8"))
                p = out_dir / render_name(template, nom, loc, "json", "rapport")
                p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                written.append(p)
                pdf = report_pdf(report, out_dir / render_name(template, nom, loc, "pdf", "rapport"))
                if pdf:
                    written.append(pdf)
            if info.is_video and options.get("video", True):
                video_out = out_dir / render_name(template, nom, loc, Path(f.path).suffix[1:])
                written.append(A.replace_video_audio(Path(f.path), main, video_out))

    if zip_all:
        zpath = out_dir / f"{_safe(project.name)}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in written:
                z.write(p, p.name)
        written.append(zpath)

    with session() as db:
        exp = Export(project_id=project_id, format=fmt, options={**options, "template": template, "zip": zip_all},
                     paths=[str(p) for p in written])
        db.add(exp)
        db.commit()
    return {"id": exp.id, "directory": str(out_dir), "files": [{"name": p.name, "path": str(p)} for p in written],
            "summary": summary}
