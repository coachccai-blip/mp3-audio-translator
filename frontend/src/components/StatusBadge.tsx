import type { SegmentStatus } from "../api/types";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";

// Statut toujours porté par une icône + un texte (jamais seulement la couleur, brief §8.5).
const STYLE: Record<SegmentStatus, { icon: string; cls: string }> = {
  ok: { icon: "check", cls: "text-success" },
  adjusted: { icon: "wave", cls: "text-primary" },
  review: { icon: "alert", cls: "text-accent" },
  error: { icon: "x", cls: "text-danger" },
  pending: { icon: "info", cls: "text-muted" },
};

export function StatusBadge({ status }: { status: SegmentStatus }) {
  const { t } = useI18n();
  const s = STYLE[status];
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${s.cls}`}>
      <Icon name={s.icon} size={13} /> {t(`seg.${status}` as const)}
    </span>
  );
}
