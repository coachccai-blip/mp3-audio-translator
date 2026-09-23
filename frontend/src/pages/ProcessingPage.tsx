import { useEffect, useRef, useState } from "react";
import type { JobSnapshot, Project } from "../api/types";
import { Banner, useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { StepProgress } from "../components/StepProgress";
import { fmtDuration } from "../format";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

function chime() {
  try {
    if (localStorage.getItem("doublr.sound") === "off") return;
    const ctx = new AudioContext();
    [660, 880].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.12);
      g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + i * 0.12 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.12 + 0.35);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + i * 0.12);
      o.stop(ctx.currentTime + i * 0.12 + 0.4);
    });
  } catch { /* audio indisponible */ }
}

export function ProcessingPage({ project, reload }: { project: Project; reload: () => void }) {
  const { t } = useI18n();
  const { api } = useApp();
  const toast = useToast();
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const redirected = useRef(false);

  useEffect(() => {
    let stop = () => {};
    api.latestJob(project.id).then((j) => {
      if (!j) return;
      setJob(j);
      stop = api.watchJob(j.id, setJob);
    });
    return () => stop();
  }, [api, project.id]);

  useEffect(() => {
    if (job?.status === "done" && job.kind === "run" && !redirected.current) {
      redirected.current = true;
      chime();
      reload();
      const timer = setTimeout(() => go(`/p/${project.id}/review`), 2500);
      return () => clearTimeout(timer);
    }
  }, [job, project.id, reload]);

  const resume = async () => {
    try { const j = await api.run(project.id); setJob(j); redirected.current = false; api.watchJob(j.id, setJob); }
    catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };

  if (!job) return <p className="text-muted">{t("common.loading")}</p>;
  const done = job.status === "done";
  const groups = job.files.reduce<Record<string, typeof job.files>>((acc, f) => { (acc[f.file_id] ||= []).push(f); return acc; }, {});

  return (
    <div className="space-y-6">
      <div className="card space-y-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span aria-live="polite">
            {job.status === "running" && job.eta_s != null ? t("processing.remaining", { t: fmtDuration(job.eta_s * 1000) }) : null}
            {done && job.result && <span className="font-medium text-success">{t("processing.summary", { ms: Math.round(job.result.delta_ms ?? 0), n: job.result.review ?? 0 })}</span>}
          </span>
          <span className="font-mono text-xs text-muted">{t("processing.elapsed", { t: fmtDuration(job.elapsed_s * 1000) })}</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(job.progress * 100)}>
          <div className={`h-full transition-all duration-300 ${done ? "bg-success" : job.status === "error" ? "bg-danger" : "bg-primary"}`} style={{ width: `${Math.max(2, job.progress * 100)}%` }} />
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {(job.status === "running" || job.status === "queued") && (
            <button className="btn-secondary" onClick={() => api.cancelJob(job.id)}>{t("common.cancel")}</button>
          )}
          {done && <>
            <button className="btn-secondary" onClick={() => go(`/p/${project.id}/export`)}>{t("processing.toExport")}</button>
            <button className="btn-primary" onClick={() => go(`/p/${project.id}/review`)}>{t("processing.toReview")}</button>
          </>}
        </div>
      </div>

      {job.status === "error" && (
        <Banner tone="danger" title={t("processing.failed")} action={<button className="btn-secondary btn-sm" onClick={resume}>{t("processing.resume")}</button>}>
          {job.error}
        </Banner>
      )}
      {job.status === "cancelled" && (
        <Banner tone="warning" title={t("processing.cancelled")} action={<button className="btn-secondary btn-sm" onClick={resume}>{t("processing.resume")}</button>}>
          {t("processing.resume")}
        </Banner>
      )}

      <div className="space-y-3">
        {Object.entries(groups).map(([fid, entries]) => {
          const isOpen = open[fid] ?? true;
          const fileDone = entries.every((e) => e.steps.every((s) => s.status === "done"));
          return (
            <section key={fid} className="card">
              <button type="button" aria-expanded={isOpen} onClick={() => setOpen({ ...open, [fid]: !isOpen })}
                className="flex w-full items-center gap-3 px-4 py-3 text-left">
                <Icon name={fileDone ? "check" : "wave"} className={fileDone ? "text-success" : "text-primary"} />
                <span className="flex-1 font-medium">{entries[0].name}</span>
                <Icon name="chevronDown" className={`transition-transform ${isOpen ? "rotate-180" : ""}`} />
              </button>
              {isOpen && <div className="space-y-2 border-t border-border px-2 py-2">{entries.map((e, i) => <StepProgress key={i} file={e} />)}</div>}
            </section>
          );
        })}
      </div>

      {job.transcript_preview.length > 0 && (
        <details className="card p-4">
          <summary className="cursor-pointer text-sm font-medium">{t("processing.live")}</summary>
          <div className="mt-2 max-h-48 space-y-1 overflow-auto text-sm text-muted">{job.transcript_preview.map((l, i) => <p key={i}>{l}</p>)}</div>
        </details>
      )}
      <details className="card p-4">
        <summary className="cursor-pointer text-sm font-medium">{t("processing.details")}</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap font-mono text-xs text-muted">{job.logs.join("\n")}</pre>
      </details>
    </div>
  );
}
