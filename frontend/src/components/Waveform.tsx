import { useEffect, useRef } from "react";

// Forme d'onde dessinée sur canvas. `view` = fenêtre visible [0..1] (zoom de la timeline).
export function Waveform({ peaks, color, height = 32, view = [0, 1], progress, className = "" }: {
  peaks: number[]; color: string; height?: number; view?: [number, number]; progress?: number; className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const w = canvas.clientWidth;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = height * dpr;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, height);
      const style = getComputedStyle(canvas);
      const fill = color.startsWith("var(") ? style.getPropertyValue(color.slice(4, -1)).trim() || "#888" : color;
      if (!peaks.length) return;
      const [a, b] = view;
      const bar = 2, gap = 1;
      const n = Math.max(1, Math.floor(w / (bar + gap)));
      for (let i = 0; i < n; i++) {
        const pos = a + ((b - a) * i) / n;
        const idx = Math.min(peaks.length - 1, Math.floor(pos * peaks.length));
        const v = Math.max(0.04, peaks[idx]);
        const h = v * (height - 2);
        const played = progress !== undefined && pos <= progress;
        ctx.fillStyle = fill;
        ctx.globalAlpha = progress === undefined || played ? 1 : 0.45;
        ctx.fillRect(i * (bar + gap), (height - h) / 2, bar, h);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [peaks, color, height, view, progress]);
  return <canvas ref={ref} className={`block w-full ${className}`} style={{ height }} aria-hidden />;
}
