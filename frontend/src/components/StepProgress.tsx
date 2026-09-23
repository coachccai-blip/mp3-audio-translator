import type { JobFile, StepStatus } from "../api/types";
import { useI18n } from "../i18n";
import { useApp } from "../store";
import { Icon } from "./Icon";

const ICON: Record<StepStatus, { name: string; cls: string }> = {
  pending: { name: "info", cls: "text-muted" },
  running: { name: "refresh", cls: "text-primary animate-spin" },
  done: { name: "check", cls: "text-success" },
  error: { name: "x", cls: "text-danger" },
  skipped: { name: "chevronRight", cls: "text-muted" },
};

export function StepProgress({ file }: { file: JobFile }) {
  const { t } = useI18n();
  const { localeInfo } = useApp();
  return (
    <ol className="space-y-1">
      {file.steps.map((s) => (
        <li key={s.key} className="flex items-center gap-3 rounded-sm px-2 py-1.5">
          <Icon name={ICON[s.status].name} size={16} className={ICON[s.status].cls} />
          <span className={`flex-1 text-sm ${s.status === "pending" ? "text-muted" : ""}`}>
            {t(`step.${s.key}` as "step.translate")}
            {s.key === "synthesize" && s.detail ? ` (${s.detail})` : ""}
            {s.key === "translate" && file.locale ? ` → ${localeInfo(file.locale).flag} ${file.locale}` : ""}
          </span>
          <span className="text-xs text-muted">{t(`status.${s.status}` as "status.done")}</span>
          <span className="w-12 text-right font-mono text-xs text-muted">{s.duration_s != null ? `${s.duration_s}s` : ""}</span>
        </li>
      ))}
    </ol>
  );
}
