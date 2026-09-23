import { useEffect, useState } from "react";
import type { AudioFileT } from "../api/types";
import { fmtDuration } from "../format";
import { useI18n } from "../i18n";
import { useApp } from "../store";
import { Icon } from "./Icon";
import { PlayButton } from "./PlayButton";
import { Waveform } from "./Waveform";

export function FileRow({ file, onRemove }: { file: AudioFileT; onRemove?: () => void }) {
  const { t } = useI18n();
  const { api, langName } = useApp();
  const [peaks, setPeaks] = useState<number[]>([]);
  const invalid = file.status === "invalid";
  useEffect(() => {
    if (!invalid) api.peaks(file.id).then(setPeaks).catch(() => setPeaks([]));
  }, [api, file.id, invalid]);
  return (
    <li className={`flex items-center gap-3 rounded-md border px-3 py-2 ${invalid ? "border-danger/50 bg-danger/5" : "border-border bg-surface"}`}>
      {invalid ? (
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger"><Icon name="alert" /></span>
      ) : (
        <PlayButton id={`orig-${file.id}`} label={file.name} size={36} variant="outline"
          load={async () => ({ kind: "url", url: api.originalUrl(file.id) })} />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="truncate font-medium">{file.name}</span>
          {!invalid && (
            <span className="font-mono text-xs text-muted">
              {fmtDuration(file.duration_ms)} · {file.format.toUpperCase()} · {(file.sample_rate / 1000).toFixed(1)} kHz · {file.channels} ch
            </span>
          )}
        </div>
        {invalid ? (
          <p className="text-sm text-danger">{file.error}</p>
        ) : (
          <div className="mt-1 flex items-center gap-3">
            <div className="hidden w-40 sm:block md:w-64"><Waveform peaks={peaks} color="var(--color-wave-original)" height={20} /></div>
            {file.detected_lang && <span className="chip">{t("import.detected", { lang: langName(file.detected_lang) })}</span>}
            {file.warnings.includes("noisy") && (
              <span className="inline-flex items-center gap-1 text-xs text-accent"><Icon name="alert" size={13} />{t("import.noisy")}</span>
            )}
          </div>
        )}
      </div>
      {onRemove && (
        <button type="button" onClick={onRemove} className="btn-ghost h-9 w-9 p-0" aria-label={t("import.remove", { name: file.name })}>
          <Icon name="x" />
        </button>
      )}
    </li>
  );
}
