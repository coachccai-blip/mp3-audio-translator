import { useEffect, useState } from "react";
import type { ExportBody, ExportResult, Project, Report } from "../api/types";
import { Banner, useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { PlayButton } from "../components/PlayButton";
import { fmtDuration } from "../format";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

const FORMATS = ["original", "mp3_320", "wav_16", "wav_24", "aac", "flac"] as const;

function load<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
}

export function ExportPage({ project }: { project: Project }) {
  const { t } = useI18n();
  const { api, localeInfo } = useApp();
  const toast = useToast();
  const files = project.files.filter((f) => f.status === "done");
  const hasVideo = files.some((f) => f.is_video);
  const [reports, setReports] = useState<Report[]>([]);
  const [body, setBody] = useState<ExportBody>(() => ({
    format: "original", voice_only: false, background_only: false, subtitles: false, report: false, video: true,
    template: "{nom}_{locale}.{ext}", zip: false, destination: null, ...load<Partial<ExportBody>>("doublr.export", {}),
  }));
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);

  useEffect(() => {
    Promise.all(files.flatMap((f) => project.targets.map((l) => api.report(f.id, l).catch(() => null))))
      .then((rs) => setReports(rs.filter(Boolean) as Report[]));
  }, [api, project.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Partial<ExportBody>) => setBody((b) => ({ ...b, ...patch }));
  const doExport = async () => {
    setBusy(true);
    try {
      try { localStorage.setItem("doublr.export", JSON.stringify({ ...body })); } catch { /* */ }
      setResult(await api.exportProject(project.id, body));
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div className="card fade-in space-y-5 p-6">
        <h2 className="flex items-center gap-2 text-xl font-semibold"><Icon name="check" className="text-success" size={24} />{t("export.done")}</h2>
        <p className="break-all font-mono text-sm text-muted">{t("export.folder", { dir: result.directory })}</p>
        <ul className="space-y-2">
          {result.summary.map((s) => (
            <li key={s.path} className="flex items-center gap-3">
              <PlayButton id={`exp-${s.path}`} label={s.path} size={32}
                load={async () => ({ kind: "url", url: api.exportFileUrl(result.id, s.path.split(/[\\/]/).pop()!) })} />
              <span className="flex-1 truncate text-sm">{localeInfo(s.locale).flag} {s.path.split(/[\\/]/).pop()}</span>
              <span className="font-mono text-xs text-muted">{t("export.delta", { ms: s.delta_ms })}</span>
            </li>
          ))}
        </ul>
        <details>
          <summary className="cursor-pointer text-sm">{t("export.files", { n: result.files.length })}</summary>
          <ul className="mt-2 space-y-1 text-sm">
            {result.files.map((f) => (
              <li key={f.path} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs">{f.name}</span>
                <a className="text-primary underline" href={api.exportFileUrl(result.id, f.name)} download>{t("export.download")}</a>
              </li>
            ))}
          </ul>
        </details>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => setResult(null)}>{t("common.back")}</button>
          <button className="btn-primary" onClick={() => go("/")}>{t("export.newProject")}</button>
        </div>
      </div>
    );
  }

  const opt = (key: keyof ExportBody, label: string) => (
    <label className="flex items-center gap-3 text-sm">
      <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={Boolean(body[key])} onChange={(e) => set({ [key]: e.target.checked })} />
      {label}
    </label>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
      <section className="card space-y-3 p-5">
        <h2 className="label">{t("export.summary")}</h2>
        <ul className="space-y-2 text-sm">
          {reports.map((r) => (
            <li key={`${r.file}-${r.locale}`} className="flex flex-wrap items-center gap-x-3">
              <span>{localeInfo(r.locale).flag}</span>
              <span className="flex-1 truncate">{r.file} · {r.locale}</span>
              <span className="font-mono text-xs text-muted">{fmtDuration(r.output_duration_ms)}</span>
              <span className={`inline-flex items-center gap-1 font-mono text-xs ${r.duration_ok ? "text-success" : "text-danger"}`}>
                <Icon name={r.duration_ok ? "check" : "alert"} size={12} />{t("export.delta", { ms: r.duration_delta_ms })}
              </span>
            </li>
          ))}
        </ul>
        {api.mode === "demo" && <Banner tone="info">{t("mode.demo.body")}</Banner>}
      </section>

      <section className="card space-y-6 p-5">
        <fieldset>
          <legend className="label">{t("export.format")}</legend>
          <div className="flex flex-wrap gap-2">
            {FORMATS.map((f) => (
              <label key={f} className={`btn-secondary btn-sm cursor-pointer ${body.format === f ? "border-primary text-primary" : ""}`}>
                <input type="radio" name="format" className="sr-only" checked={body.format === f} onChange={() => set({ format: f })} />
                {t(`format.${f}`)}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted">{t("export.keepProps")}</p>
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="label">{t("export.options")}</legend>
          {opt("voice_only", t("opt.voice_only"))}
          {opt("background_only", t("opt.background_only"))}
          {opt("subtitles", t("opt.subtitles"))}
          {opt("report", t("opt.report"))}
          {hasVideo && opt("video", t("opt.video"))}
          {files.length * project.targets.length > 1 && opt("zip", t("export.zip"))}
        </fieldset>
        <label className="block">
          <span className="label">{t("export.naming")}</span>
          <input className="input font-mono" value={body.template} onChange={(e) => set({ template: e.target.value })} />
          <span className="mt-1 block text-xs text-muted">{t("export.namingHelp")} → {files[0] ? `${files[0].name.replace(/\.[^.]+$/, "")}_${project.targets[0]}` : ""}</span>
        </label>
        <label className="block">
          <span className="label">{t("export.destination")}</span>
          <input className="input font-mono" placeholder="exports/…" value={body.destination || ""} onChange={(e) => set({ destination: e.target.value || null })} />
        </label>
        <button className="btn-primary w-full" disabled={busy || !files.length} onClick={doExport}>
          {busy ? <Icon name="refresh" className="animate-spin" size={16} /> : <Icon name="download" size={16} />}{t("export.go")}
        </button>
      </section>
    </div>
  );
}
