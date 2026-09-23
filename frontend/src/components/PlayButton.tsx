import type { AudioSource } from "../api/types";
import { usePreview } from "../hooks/useAudio";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";

// Bouton lecture : passe en pause et affiche un anneau de progression circulaire (brief §9.4).
export function PlayButton({ id, load, label, size = 36, range, variant = "filled" }: {
  id: string; load: () => Promise<AudioSource>; label: string; size?: number;
  range?: { start: number; end: number }; variant?: "filled" | "outline";
}) {
  const { t } = useI18n();
  const p = usePreview();
  const playing = p.playingId === id;
  const loading = p.loadingId === id;
  const r = size / 2 - 2;
  const c = 2 * Math.PI * r;
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); p.toggle(id, load, range); }}
      aria-label={`${playing ? t("common.pause") : t("common.play")} — ${label}`} aria-pressed={playing}
      className={`relative inline-flex shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
        variant === "filled" ? "bg-primary text-white hover:bg-primary-hover" : "border border-border bg-surface text-primary hover:bg-surface-2"}`}
      style={{ width: size, height: size }}>
      <svg className="pointer-events-none absolute inset-0 -rotate-90" width={size} height={size} aria-hidden>
        {(playing || loading) && (
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={variant === "filled" ? "rgba(255,255,255,.9)" : "var(--color-primary)"}
            strokeWidth={2} strokeDasharray={c} strokeDashoffset={loading ? c * 0.75 : c * (1 - p.progress)}
            className={loading ? "origin-center animate-spin" : ""} style={{ transition: "stroke-dashoffset 120ms linear" }} />
        )}
      </svg>
      <Icon name={playing ? "pause" : "play"} size={size * 0.45} />
    </button>
  );
}
