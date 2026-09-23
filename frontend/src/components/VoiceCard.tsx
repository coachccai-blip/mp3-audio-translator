import type { Voice } from "../api/types";
import { useI18n } from "../i18n";
import { useApp } from "../store";
import { Icon } from "./Icon";
import { PlayButton } from "./PlayButton";

export function VoiceCard({ voice, selected, recommended, onSelect }: {
  voice: Voice; selected: boolean; recommended: boolean; onSelect: () => void;
}) {
  const { t } = useI18n();
  const { api } = useApp();
  const gender = voice.gender === "female" || voice.gender === "male" ? voice.gender : "unknown";
  return (
    <div className={`relative flex w-44 shrink-0 snap-start flex-col gap-2 rounded-md border-2 bg-surface p-3 ${selected ? "border-primary" : "border-border"}`}>
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onSelect} aria-pressed={selected} className="min-w-0 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
          <div className="truncate font-semibold">{voice.display_name}</div>
          <div className="text-xs text-muted">{t(`gender.${gender}` as const)} · {t(`age.${voice.age_range}` as "age.adult") || voice.age_range}</div>
        </button>
        <PlayButton id={`sample-${voice.id}`} label={voice.display_name} size={30} variant="outline" load={() => api.voiceSample(voice)} />
      </div>
      <div className="flex flex-wrap gap-1">
        {voice.styles.map((s) => <span key={s} className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">{t(`style.${s}` as "style.neutral") || s}</span>)}
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {recommended && <span className="rounded-sm bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">{t("speakers.recommended")}</span>}
        {!voice.validated && <span className="rounded-sm bg-accent/15 px-1.5 py-0.5 text-[11px] text-text" title={voice.status}>{t("voice.toConfirm")}</span>}
      </div>
      {selected && (
        <span className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-white" aria-hidden>
          <Icon name="check" size={12} strokeWidth={3} />
        </span>
      )}
    </div>
  );
}
