import { useRef, useState, type PointerEvent, type WheelEvent } from "react";
import type { SegmentT } from "../api/types";
import { fmtClock, speakerColor } from "../format";
import { useI18n } from "../i18n";
import { Waveform } from "./Waveform";

// Timeline : deux formes d'onde superposées + segments colorés par locuteur, zoom molette, déplacement.
export function Timeline({ originalPeaks, dubbedPeaks, segments, durationMs, timeMs, selectedId, onSeek, onSelect }: {
  originalPeaks: number[]; dubbedPeaks: number[]; segments: SegmentT[]; durationMs: number; timeMs: number;
  selectedId: string | null; onSeek: (ms: number) => void; onSelect: (s: SegmentT) => void;
}) {
  const { t } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<[number, number]>([0, 1]);
  const drag = useRef<{ x: number; view: [number, number]; moved: boolean } | null>(null);
  const span = view[1] - view[0];
  const toX = (ms: number) => ((ms / durationMs - view[0]) / span) * 100;

  const onWheel = (e: WheelEvent) => {
    if (!box.current || !durationMs) return;
    const rect = box.current.getBoundingClientRect();
    const f = (e.clientX - rect.left) / rect.width;
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      const d = ((e.deltaX || e.deltaY) / rect.width) * span;
      const a = Math.min(Math.max(0, view[0] + d), 1 - span);
      setView([a, a + span]);
      return;
    }
    const center = view[0] + f * span;
    const ns = Math.min(1, Math.max(0.01, span * (e.deltaY > 0 ? 1.2 : 1 / 1.2)));
    const a = Math.min(Math.max(0, center - f * ns), 1 - ns);
    setView([a, a + ns]);
  };
  const onDown = (e: PointerEvent) => { drag.current = { x: e.clientX, view, moved: false }; (e.target as Element).setPointerCapture?.(e.pointerId); };
  const onMove = (e: PointerEvent) => {
    if (!drag.current || !box.current) return;
    const dx = e.clientX - drag.current.x;
    if (Math.abs(dx) > 3) drag.current.moved = true;
    if (!drag.current.moved) return;
    const d = (-dx / box.current.clientWidth) * span;
    const a = Math.min(Math.max(0, drag.current.view[0] + d), 1 - span);
    setView([a, a + span]);
  };
  const onUp = (e: PointerEvent) => {
    if (drag.current && !drag.current.moved && box.current) {
      const rect = box.current.getBoundingClientRect();
      onSeek((view[0] + ((e.clientX - rect.left) / rect.width) * span) * durationMs);
    }
    drag.current = null;
  };

  return (
    <div className="card select-none p-3" role="group" aria-label={t("review.timeline")}>
      <div className="mb-1 flex justify-between font-mono text-[11px] text-muted">
        <span>{fmtClock(view[0] * durationMs)}</span>
        <span>{fmtClock(timeMs, true)}</span>
        <span>{fmtClock(view[1] * durationMs)}</span>
      </div>
      <div ref={box} className="relative cursor-crosshair touch-none overflow-hidden rounded-sm bg-surface-2"
        onWheel={onWheel} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}>
        <div className="px-0 pt-2"><Waveform peaks={originalPeaks} color="var(--color-wave-original)" height={48} view={view} /></div>
        <div className="relative h-6">
          {segments.map((s) => {
            const left = toX(s.start_ms), width = toX(s.end_ms) - left;
            if (left > 100 || left + width < 0) return null;
            return (
              <button key={s.id} type="button" tabIndex={-1} aria-hidden
                onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => { e.stopPropagation(); onSelect(s); }}
                className={`absolute top-1 h-4 rounded-sm ${s.status === "review" ? "hatched" : ""} ${selectedId === s.id ? "ring-2 ring-text" : ""}`}
                style={{ left: `${left}%`, width: `${Math.max(width, 0.3)}%`, backgroundColor: speakerColor(s.speaker_key), opacity: 0.85 }} />
            );
          })}
        </div>
        <div className="pb-2 fade-in" key={dubbedPeaks.length ? dubbedPeaks[0] + dubbedPeaks.length : 0}>
          <Waveform peaks={dubbedPeaks} color="var(--color-wave-dubbed)" height={48} view={view} />
        </div>
        <div className="pointer-events-none absolute inset-y-0 w-px bg-danger" style={{ left: `${toX(timeMs)}%` }} />
      </div>
    </div>
  );
}
