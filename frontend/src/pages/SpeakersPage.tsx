import { useCallback, useEffect, useState } from "react";
import type { AudioFileT, JobSnapshot, Locale, Project, Speaker, Voice } from "../api/types";
import { useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { PlayButton } from "../components/PlayButton";
import { VoiceCard } from "../components/VoiceCard";
import { fmtDuration, speakerColor } from "../format";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

export function SpeakersPage({ project, reload }: { project: Project; reload: () => void }) {
  const { t } = useI18n();
  const { api, missingKeys } = useApp();
  const toast = useToast();
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const files = project.files.filter((f) => f.status !== "invalid");
  const preparing = job && (job.status === "running" || job.status === "queued") && job.kind === "prepare";

  useEffect(() => {
    let stop = () => {};
    api.latestJob(project.id).then((j) => {
      if (!j) return;
      setJob(j);
      stop = api.watchJob(j.id, (s) => { setJob(s); if (s.status === "done") reload(); });
    });
    return () => stop();
  }, [api, project.id, reload]);

  const launch = async () => {
    if (missingKeys.length) {
      toast({ tone: "danger", text: (missingKeys.includes("LOCAL_LLM") ? t("banner.localLlm") : t("banner.missingKeys", { keys: missingKeys.join(", ") })), action: { label: t("banner.goSettings"), run: () => go("/settings") } });
      return;
    }
    try { await api.run(project.id); go(`/p/${project.id}/processing`); } catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };

  if (preparing && job) {
    return (
      <div className="card space-y-4 p-6" role="status" aria-live="polite">
        <p className="font-medium">{t("speakers.preparing")}</p>
        <div className="h-2 overflow-hidden rounded-full bg-surface-2"><div className="h-full bg-primary transition-all" style={{ width: `${job.progress * 100}%` }} /></div>
        {job.transcript_preview.length > 0 && (
          <div>
            <p className="label">{t("processing.live")}</p>
            <div className="max-h-60 space-y-1 overflow-auto text-sm text-muted">{job.transcript_preview.map((l, i) => <p key={i} className="fade-in">{l}</p>)}</div>
          </div>
        )}
      </div>
    );
  }
  if (job?.status === "error") {
    return <div className="card p-6 text-danger" role="alert">{t("processing.failed")} : {job.error}</div>;
  }

  return (
    <div className="space-y-8 pb-24">
      <p className="text-sm text-muted">{t("speakers.dragHint")}</p>
      {files.map((f) => <FileSpeakers key={f.id} file={f} targets={project.targets} />)}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl justify-end px-4 py-3">
          <button className="btn-primary" onClick={launch}>{t("speakers.launch")}</button>
        </div>
      </div>
    </div>
  );
}

function FileSpeakers({ file, targets }: { file: AudioFileT; targets: Locale[] }) {
  const { t } = useI18n();
  const { api } = useApp();
  const toast = useToast();
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [dragId, setDragId] = useState<string | null>(null);
  const load = useCallback(() => api.speakers(file.id).then(setSpeakers).catch(() => setSpeakers([])), [api, file.id]);
  useEffect(() => { load(); }, [load]);

  const merge = async (source: string, target: string) => {
    if (source === target) return;
    try { setSpeakers(await api.mergeSpeakers(file.id, source, target)); } catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };

  return (
    <section className="space-y-3">
      <h2 className="font-semibold">{file.name}</h2>
      {speakers.map((s) => (
        <article key={s.id} draggable onDragStart={() => setDragId(s.id)} onDragEnd={() => setDragId(null)}
          onDragOver={(e) => dragId && dragId !== s.id && e.preventDefault()} onDrop={() => dragId && merge(dragId, s.id)}
          className={`card space-y-3 p-4 ${dragId && dragId !== s.id ? "outline-dashed outline-2 outline-primary/50" : ""}`}>
          <header className="flex flex-wrap items-center gap-3">
            <span className="h-3 w-3 rounded-full" style={{ background: speakerColor(s.key) }} aria-hidden />
            <input aria-label={t("speakers.rename")} defaultValue={s.label}
              className="rounded-sm border border-transparent bg-transparent px-1 font-semibold hover:border-border focus:border-border"
              onBlur={(e) => {
                const label = e.target.value.trim();
                if (!label || label === s.label) return;
                api.patchSpeaker(s.id, { label }).catch((err) => toast({ tone: "danger", text: errMsg(err) }));
                setSpeakers((xs) => xs.map((x) => (x.id === s.id ? { ...x, label } : x)));
              }} />
            <span className="text-sm text-muted">
              {t("speakers.speech", { t: fmtDuration(s.speech_ms) })} · {t("speakers.gender", { g: t(`gender.${(s.gender as "male") || "unknown"}` as "gender.male") })}
            </span>
            {s.first_start_ms != null && (
              <PlayButton id={`spk-orig-${s.id}`} label={`${t("speakers.listenOriginal")} — ${s.label}`} size={30} variant="outline"
                load={async () => ({ kind: "url", url: api.originalUrl(file.id) })}
                range={{ start: s.first_start_ms / 1000, end: s.first_start_ms / 1000 + 5 }} />
            )}
            {speakers.length > 1 && (
              <select aria-label={t("speakers.mergeInto")} className="ml-auto rounded-sm border border-border bg-surface px-2 py-1 text-xs" value=""
                onChange={(e) => e.target.value && merge(s.id, e.target.value)}>
                <option value="">{t("speakers.mergeInto")}</option>
                {speakers.filter((x) => x.id !== s.id).map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            )}
          </header>
          {targets.map((loc) => (
            <VoicePicker key={loc} speaker={s} locale={loc}
              onPick={async (voiceId) => {
                try {
                  await api.patchSpeaker(s.id, { locale: loc, voice_id: voiceId });
                  setSpeakers((xs) => xs.map((x) => (x.id === s.id ? { ...x, voices: { ...x.voices, [loc]: voiceId } } : x)));
                } catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
              }} />
          ))}
        </article>
      ))}
    </section>
  );
}

function VoicePicker({ speaker, locale, onPick }: { speaker: Speaker; locale: Locale; onPick: (id: string) => void }) {
  const { t } = useI18n();
  const { api, localeInfo } = useApp();
  const [voices, setVoices] = useState<Voice[]>([]);
  const [gender, setGender] = useState("all");
  const [style, setStyle] = useState("all");
  const [recommended, setRecommended] = useState<string | null>(null);
  useEffect(() => {
    api.voices(locale).then((vs) => {
      setVoices(vs);
      const same = vs.filter((v) => v.gender === speaker.gender);
      setRecommended((same.find((v) => v.default) || same[0] || vs.find((v) => v.default) || vs[0])?.id || null);
    }).catch(() => setVoices([]));
  }, [api, locale, speaker.gender]);
  const current = speaker.voices[locale] || recommended;
  const styles = [...new Set(voices.flatMap((v) => v.styles))];
  const shown = voices.filter((v) => (gender === "all" || v.gender === gender) && (style === "all" || v.styles.includes(style)));
  const info = localeInfo(locale);

  return (
    <div className="space-y-2 rounded-md bg-surface-2 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{info.flag} {info.native} <span className="font-mono text-xs text-muted">{locale}</span></span>
        <select aria-label={t("speakers.filterGender")} className="rounded-sm border border-border bg-surface px-2 py-0.5 text-xs" value={gender} onChange={(e) => setGender(e.target.value)}>
          <option value="all">{t("speakers.filterGender")} : {t("common.all")}</option>
          <option value="female">{t("gender.female")}</option><option value="male">{t("gender.male")}</option>
        </select>
        <select aria-label={t("speakers.filterStyle")} className="rounded-sm border border-border bg-surface px-2 py-0.5 text-xs" value={style} onChange={(e) => setStyle(e.target.value)}>
          <option value="all">{t("speakers.filterStyle")} : {t("common.all")}</option>
          {styles.map((s) => <option key={s} value={s}>{t(`style.${s}` as "style.neutral") || s}</option>)}
        </select>
        {current && (
          <span className="ml-auto inline-flex items-center gap-2">
            <PlayButton id={`dubprev-${speaker.id}-${locale}-${current}`} label={t("speakers.previewDub")} size={30}
              load={() => api.speakerPreview(speaker.id, locale, current)} />
            <span className="text-xs">{t("speakers.previewDub")}</span>
          </span>
        )}
      </div>
      <div className="flex snap-x gap-3 overflow-x-auto pb-2 pt-2">
        {shown.map((v) => <VoiceCard key={v.id} voice={v} selected={current === v.id} recommended={recommended === v.id} onSelect={() => onPick(v.id)} />)}
        {!shown.length && <p className="flex items-center gap-2 text-sm text-muted"><Icon name="info" size={14} />—</p>}
      </div>
    </div>
  );
}
