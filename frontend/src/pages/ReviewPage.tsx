import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Locale, Project, SegmentT, Voice } from "../api/types";
import { Banner, useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { fmtClock, speakerColor } from "../format";
import { useABPlayer } from "../hooks/useABPlayer";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

type Filter = "all" | "review" | "modified";

export function ReviewPage({ project }: { project: Project }) {
  const { t } = useI18n();
  const { api, localeInfo } = useApp();
  const toast = useToast();
  const files = project.files.filter((f) => f.status === "done");
  const [fileId, setFileId] = useState(files[0]?.id || "");
  const [locale, setLocale] = useState<Locale>(project.targets[0] || "");
  const [segments, setSegments] = useState<SegmentT[]>([]);
  const [origPeaks, setOrigPeaks] = useState<number[]>([]);
  const [dubPeaks, setDubPeaks] = useState<number[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [version, setVersion] = useState(0);
  const [voices, setVoices] = useState<Voice[]>([]);
  const file = files.find((f) => f.id === fileId);

  const dubbedUrl = fileId && locale ? `${api.trackUrl(fileId, "mix", locale)}${api.mode === "local" ? `&v=${version}` : ""}` : null;
  const player = useABPlayer(fileId ? api.originalUrl(fileId) : null, dubbedUrl);

  useEffect(() => {
    if (!fileId || !locale) return;
    api.segments(fileId, locale).then(setSegments).catch(() => setSegments([]));
    api.peaks(fileId).then(setOrigPeaks).catch(() => setOrigPeaks([]));
    api.voices(locale).then(setVoices).catch(() => setVoices([]));
  }, [api, fileId, locale]);
  useEffect(() => {
    if (fileId && locale) api.peaks(fileId, locale).then(setDubPeaks).catch(() => setDubPeaks([]));
  }, [api, fileId, locale, version]);

  const shown = useMemo(() => segments.filter((s) =>
    filter === "all" || (filter === "review" ? s.status === "review" || s.status === "error" : s.target_text_edited !== null || s.voice_override)), [segments, filter]);
  const toCheck = segments.filter((s) => s.status === "review" || s.status === "error").length;

  const selectSeg = useCallback((s: SegmentT) => {
    setSelected(s.id);
    player.seek(s.start_ms / 1000);
    document.getElementById(`seg-${s.id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [player]);

  const update = async (s: SegmentT, body: Parameters<typeof api.patchSegment>[1]) => {
    try {
      const next = await api.patchSegment(s.id, body);
      setSegments((xs) => xs.map((x) => (x.id === s.id ? next : x)));
      setVersion((v) => v + 1);
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    }
  };

  // Raccourcis : Espace lecture/pause, Tab bascule A/B, ←/→ segment précédent/suivant.
  const keys = useRef({ player, segments, selected, selectSeg });
  keys.current = { player, segments, selected, selectSeg };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      const k = keys.current;
      if (e.key === " " && tag !== "BUTTON") { e.preventDefault(); k.player.playPause(); }
      else if (e.key === "Tab" && !e.shiftKey && tag === "BODY") { e.preventDefault(); k.player.toggleMode(); }
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const idx = k.segments.findIndex((s) => s.id === k.selected);
        const next = k.segments[Math.min(k.segments.length - 1, Math.max(0, idx + (e.key === "ArrowRight" ? 1 : -1)))];
        if (next) k.selectSeg(next);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const current = segments.find((s) => player.time * 1000 >= s.start_ms && player.time * 1000 < s.end_ms);

  return (
    <div className="space-y-4 pb-24">
      {api.mode === "demo" && <Banner tone="info">{t("review.demoNote")}</Banner>}
      <div className="flex flex-wrap items-end gap-3">
        {files.length > 1 && (
          <label><span className="label">{t("review.file")}</span>
            <select className="input" value={fileId} onChange={(e) => setFileId(e.target.value)}>{files.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>
          </label>
        )}
        {project.targets.length > 1 && (
          <label><span className="label">{t("review.language")}</span>
            <select className="input" value={locale} onChange={(e) => setLocale(e.target.value)}>
              {project.targets.map((l) => <option key={l} value={l}>{localeInfo(l).flag} {localeInfo(l).native} ({l})</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="sticky top-0 z-10 -mx-4 space-y-3 bg-bg/95 px-4 pb-3 pt-1 backdrop-blur">
        <div className="card flex flex-wrap items-center gap-4 p-3">
          <button type="button" onClick={player.playPause} className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-white hover:bg-primary-hover"
            aria-label={player.playing ? t("common.pause") : t("common.play")}>
            <Icon name={player.playing ? "pause" : "play"} size={22} />
          </button>
          <div role="radiogroup" aria-label="A/B" className="inline-flex rounded-full border border-border bg-surface-2 p-1 text-sm">
            {(["original", "dubbed"] as const).map((m) => (
              <button key={m} role="radio" aria-checked={player.mode === m} onClick={() => player.mode !== m && player.toggleMode()}
                className={`rounded-full px-4 py-1.5 font-medium transition-colors ${player.mode === m ? "bg-surface text-text shadow-sm" : "text-muted"}`}>
                {t(m === "original" ? "review.original" : "review.dubbed")}
              </button>
            ))}
          </div>
          <span className="font-mono text-sm">{fmtClock(player.time * 1000, true)} / {fmtClock(player.duration * 1000)}</span>
          {current && <span className="hidden truncate text-sm text-muted lg:inline">« {current.effective_text} »</span>}
          <span className="ml-auto hidden text-xs text-muted md:inline">{t("review.shortcuts")}</span>
        </div>
        <div className="hidden md:block">
          <Timeline originalPeaks={origPeaks} dubbedPeaks={dubPeaks} segments={segments} durationMs={file?.duration_ms || 1}
            timeMs={player.time * 1000} selectedId={selected} onSeek={(ms) => player.seek(ms / 1000)} onSelect={selectSeg} />
        </div>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist">
        {(["all", "review", "modified"] as Filter[]).map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
            className={`chip ${filter === f ? "border-primary text-primary" : ""}`}>
            {t(`review.filter.${f}`)}{f === "review" && toCheck ? ` (${toCheck})` : ""}
          </button>
        ))}
      </div>

      <ul className="space-y-2">
        {shown.map((s) => (
          <SegmentRow key={s.id} seg={s} voices={voices} active={selected === s.id} playing={current?.id === s.id}
            onSelect={() => selectSeg(s)} onUpdate={(body) => update(s, body)} />
        ))}
      </ul>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-end gap-4 px-4 py-3">
          {toCheck > 0 && <span className="inline-flex items-center gap-1 text-sm text-muted"><Icon name="alert" size={14} className="text-accent" />{t("review.remaining", { n: toCheck })}</span>}
          <button className="btn-primary" onClick={() => go(`/p/${project.id}/export`)}>{t("review.toExport")}</button>
        </div>
      </div>
    </div>
  );
}

function StretchGauge({ ratio }: { ratio: number | null }) {
  const { t } = useI18n();
  if (ratio == null) return null;
  const pct = Math.round((ratio - 1) * 1000) / 10;
  const abs = Math.abs(pct);
  const color = abs <= 6 ? "bg-success" : abs <= 12 ? "bg-accent" : "bg-danger";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted" title={t("review.stretch", { p: pct })}>
      <span className="relative h-1.5 w-16 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <span className={`absolute inset-y-0 left-0 ${color}`} style={{ width: `${Math.min(100, (abs / 15) * 100)}%` }} />
      </span>
      <span className="font-mono">{pct > 0 ? "+" : ""}{pct}%</span>
    </span>
  );
}

function SegmentRow({ seg, voices, active, playing, onSelect, onUpdate }: {
  seg: SegmentT; voices: Voice[]; active: boolean; playing: boolean; onSelect: () => void;
  onUpdate: (body: { target_text?: string; voice_id?: string; action?: string }) => Promise<void>;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(seg.effective_text);
  const [busy, setBusy] = useState(false);
  useEffect(() => setText(seg.effective_text), [seg.effective_text]);
  const run = async (body: Parameters<typeof onUpdate>[0]) => { setBusy(true); await onUpdate(body); setBusy(false); };
  const edited = seg.target_text_edited !== null || Boolean(seg.voice_override);

  return (
    <li id={`seg-${seg.id}`} className={`scroll-mt-4 md:scroll-mt-80 rounded-md border bg-surface transition-colors ${active ? "border-primary" : "border-border"} ${playing ? "shadow-md" : ""}`}>
      <button type="button" onClick={onSelect} aria-expanded={active} className="flex w-full flex-wrap items-start gap-x-4 gap-y-1 p-3 text-left">
        <span className="font-mono text-xs text-muted">{fmtClock(seg.start_ms, true)}</span>
        <span className="inline-flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full" style={{ background: speakerColor(seg.speaker_key) }} />{seg.speaker_key}</span>
        <StatusBadge status={seg.status} />
        <StretchGauge ratio={seg.stretch_ratio} />
        {edited && <span className="text-xs text-primary"><Icon name="edit" size={12} className="inline" /> {t("review.filter.modified")}</span>}
        <span className="basis-full text-sm text-muted">{seg.source_text}</span>
        {!active && <span className="basis-full text-sm">{seg.effective_text}</span>}
      </button>
      {active && (
        <div className="space-y-3 border-t border-border p-3">
          {seg.error && <p className="text-sm text-danger">{seg.error}</p>}
          <label className="block">
            <span className="sr-only">{t("review.target")}</span>
            <textarea className="input text-md" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary btn-sm" disabled={busy} onClick={() => run({ target_text: text })}>
              <Icon name="refresh" size={14} className={busy ? "animate-spin" : ""} />{t("review.regenerate")}
            </button>
            <button className="btn-secondary btn-sm" disabled={busy} onClick={() => run({ action: "shorter" })}><Icon name="shorter" size={14} />{t("review.shorter")}</button>
            <button className="btn-secondary btn-sm" disabled={busy} onClick={() => run({ action: "longer" })}><Icon name="longer" size={14} />{t("review.longer")}</button>
            <button className="btn-ghost btn-sm" disabled={busy || !seg.can_undo} onClick={() => run({ action: "undo" })} aria-label={t("review.undo")}><Icon name="undo" size={14} />{t("review.undo")}</button>
            <button className="btn-ghost btn-sm" disabled={busy || !seg.can_redo} onClick={() => run({ action: "redo" })} aria-label={t("review.redo")}><Icon name="redo" size={14} />{t("review.redo")}</button>
            <label className="ml-auto inline-flex items-center gap-2 text-xs">
              {t("review.voice")}
              <select className="rounded-sm border border-border bg-surface px-2 py-1" value={seg.voice_override || ""} disabled={busy}
                onChange={(e) => run({ voice_id: e.target.value })}>
                <option value="">{t("review.speakerVoice")}</option>
                {voices.map((v) => <option key={v.id} value={v.id}>{v.display_name} ({t(`gender.${v.gender as "male"}`)})</option>)}
              </select>
            </label>
          </div>
        </div>
      )}
    </li>
  );
}
