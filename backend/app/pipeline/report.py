"""Étape 12 — rapport de qualité."""
from __future__ import annotations

from pathlib import Path


def build_report(file_name: str, locale: str, input_ms: float, output_ms: float, segments: list[dict],
                 processing_s: float, cost_usd: float, warnings: list[str]) -> dict:
    counts = {"ok": 0, "adjusted": 0, "review": 0, "error": 0}
    for s in segments:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {
        "file": file_name,
        "locale": locale,
        "input_duration_ms": round(input_ms, 1),
        "output_duration_ms": round(output_ms, 1),
        "duration_delta_ms": round(output_ms - input_ms, 1),
        "duration_ok": abs(output_ms - input_ms) <= 50,
        "processing_seconds": round(processing_s, 1),
        "estimated_cost_usd": round(cost_usd, 4),
        "counts": counts,
        "warnings": warnings,
        "segments": [
            {
                "index": s["index"], "start_ms": s["start_ms"], "end_ms": s["end_ms"], "speaker": s["speaker"],
                "source_text": s["source_text"], "target_text": s["target_text"],
                "target_ms": s["end_ms"] - s["start_ms"], "obtained_ms": s.get("final_ms"),
                "stretch_ratio": s.get("stretch_ratio"), "retranslations": s.get("retranslations", 0),
                "status": s["status"],
            }
            for s in segments
        ],
    }


def report_pdf(report: dict, path: Path) -> Path | None:
    """PDF lisible si reportlab est installé, sinon None (le JSON reste disponible)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return None
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"Rapport de doublage — {report['file']} ({report['locale']})")
    y -= 24
    c.setFont("Helvetica", 10)
    for line in [
        f"Durée entrée : {report['input_duration_ms']} ms — sortie : {report['output_duration_ms']} ms "
        f"(écart {report['duration_delta_ms']} ms)",
        f"Segments : {report['counts']}",
        f"Temps de traitement : {report['processing_seconds']} s — coût estimé : {report['estimated_cost_usd']} $",
    ]:
        c.drawString(40, y, line)
        y -= 14
    y -= 10
    for s in report["segments"]:
        if y < 60:
            c.showPage()
            y = h - 50
            c.setFont("Helvetica", 9)
        c.setFont("Helvetica", 9)
        c.drawString(40, y, f"#{s['index'] + 1} [{s['status']}] {s['start_ms'] / 1000:.2f}s  stretch={s['stretch_ratio']}")
        y -= 12
        c.drawString(55, y, (s["target_text"] or "")[:110])
        y -= 16
    c.save()
    return path
