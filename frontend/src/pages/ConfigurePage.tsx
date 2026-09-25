import { useEffect, useMemo, useState } from "react";
import type { Estimate, Project, ProjectSettings } from "../api/types";
import { Banner, useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { LanguageGrid } from "../components/LanguageGrid";
import { fmtDuration } from "../format";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

export function ConfigurePage({ project, onChange }: { project: Project; onChange: (p: Project) => void }) {
  const { t } = useI18n();
  const { api, languages, langName, missingKeys } = useApp();
  const toast = useToast();
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [glossaryText, setGlossaryText] = useState(
    (project.settings.glossary || []).map((g) => `${g.source};${g.target}`).join("\n"));
  const s = project.settings;
  const detected = project.source_lang || project.files.find((f) => f.detected_lang)?.detected_lang || null;
  const noisy = project.files.some((f) => f.warnings.includes("noisy"));

  useEffect(() => { api.estimate(project.id).then(setEstimate).catch(() => setEstimate(null)); }, [api, project.id, project.targets.length]);

  const patch = async (body: Parameters<typeof api.patchProject>[1]) => {
    try { onChange(await api.patchProject(project.id, body)); } catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };
  const setSetting = (patchS: ProjectSettings) => patch({ settings: patchS });

  const saveGlossary = (text: string) => {
    const glossary = text.split("\n").map((l) => l.split(/[;,\t]/)).filter((p) => p[0]?.trim())
      .map(([source, target = ""]) => ({ source: source.trim(), target: target.trim() }));
    setSetting({ glossary });
  };

  const launch = async (direct: boolean) => {
    if (!project.targets.length) { toast({ tone: "warning", text: t("configure.pickTarget") }); return; }
    if (noisy && !window.confirm(t("configure.noisyConfirm"))) return;
    if (missingKeys.length && direct) {
      toast({ tone: "danger", text: (missingKeys.includes("LOCAL_LLM") ? t("banner.localLlm") : t("banner.missingKeys", { keys: missingKeys.join(", ") })), action: { label: t("banner.goSettings"), run: () => go("/settings") } });
      return;
    }
    try {
      if (direct) { await api.run(project.id); go(`/p/${project.id}/processing`); }
      else { await api.prepare(project.id); go(`/p/${project.id}/speakers`); }
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    }
  };

  const sourceOptions = useMemo(() => languages.map((l) => l.code), [languages]);

  return (
    <div className="space-y-8 pb-32">
      <section className="space-y-2">
        <h2 className="label">{t("configure.source")}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip text-sm">{detected ? t("configure.detected", { lang: langName(detected) }) : t("configure.autodetect")}</span>
          <select aria-label={t("configure.source")} className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
            value={project.settings.source_locked ? project.source_lang || "" : ""}
            onChange={(e) => e.target.value && patch({ source_lang: e.target.value })}>
            <option value="">{t("configure.autodetect")}</option>
            {sourceOptions.map((c) => <option key={c} value={c}>{langName(c)}</option>)}
          </select>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="label mb-0">{t("configure.targets")}</h2>
          {project.targets.length > 0 && <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-white">{t("configure.selected", { n: project.targets.length })}</span>}
        </div>
        <LanguageGrid languages={languages} selected={project.targets} exclude={detected} onChange={(targets) => patch({ targets })} />
      </section>

      <section className="card">
        <button type="button" className="flex w-full items-center justify-between px-4 py-3 text-left font-medium" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
          {t("configure.advanced")}
          <Icon name="chevronDown" className={`transition-transform ${advanced ? "rotate-180" : ""}`} />
        </button>
        {advanced && (
          <div className="grid gap-6 border-t border-border p-4 md:grid-cols-2">
            <label className="block">
              <span className="label">{t("configure.register")}</span>
              <select className="input" value={s.register || "auto"} onChange={(e) => setSetting({ register: e.target.value as ProjectSettings["register"] })}>
                {(["auto", "formal", "conversational", "advertising", "educational"] as const).map((r) => <option key={r} value={r}>{t(`register.${r}`)}</option>)}
              </select>
            </label>
            <fieldset>
              <legend className="label">{t("configure.quality")}</legend>
              <div className="flex gap-2">
                {(["fast", "precise"] as const).map((q) => (
                  <label key={q} className={`btn-secondary btn-sm cursor-pointer ${ (s.quality || "fast") === q ? "border-primary text-primary" : ""}`}>
                    <input type="radio" name="quality" className="sr-only" checked={(s.quality || "fast") === q} onChange={() => setSetting({ quality: q })} />
                    {t(`quality.${q}`)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="block md:col-span-2">
              <span className="label">{t("configure.glossary")}</span>
              <textarea className="input font-mono" rows={3} value={glossaryText} placeholder="Doublr;&#10;podcast;balado"
                onChange={(e) => setGlossaryText(e.target.value)} onBlur={() => saveGlossary(glossaryText)} />
              <span className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
                {t("configure.glossaryHelp")}
                <label className="cursor-pointer text-primary underline">
                  {t("configure.importCsv")}
                  <input type="file" accept=".csv,text/csv" className="sr-only" onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (f) { const txt = await f.text(); setGlossaryText(txt); saveGlossary(txt); }
                  }} />
                </label>
              </span>
            </label>
            <label className="flex items-center gap-3">
              <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={s.keep_background ?? true} onChange={(e) => setSetting({ keep_background: e.target.checked })} />
              <span className="text-sm">{t("configure.keepBg")}</span>
            </label>
            <label className="block">
              <span className="label">{t("configure.tolerance", { n: s.stretch_tolerance ?? 12 })}</span>
              <input type="range" min={5} max={12} step={1} className="w-full accent-[var(--color-primary)]" value={s.stretch_tolerance ?? 12}
                onChange={(e) => setSetting({ stretch_tolerance: Number(e.target.value) })} />
            </label>
          </div>
        )}
      </section>

      {missingKeys.length > 0 && (
        <Banner tone="warning" action={<button className="btn-secondary btn-sm" onClick={() => go("/settings")}>{t("banner.goSettings")}</button>}>
          {(missingKeys.includes("LOCAL_LLM") ? t("banner.localLlm") : t("banner.missingKeys", { keys: missingKeys.join(", ") }))}
        </Banner>
      )}

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <dl className="flex flex-1 flex-wrap gap-x-6 gap-y-1 text-sm">
            <div><dt className="text-xs text-muted">{t("estimate.duration")}</dt><dd className="font-mono">{estimate ? fmtDuration(estimate.total_seconds * 1000) : "—"}</dd></div>
            <div><dt className="text-xs text-muted">{t("estimate.time")}</dt><dd className="font-mono">{estimate ? `≈ ${fmtDuration(estimate.processing_seconds * 1000)}` : "—"}</dd></div>
            <div><dt className="text-xs text-muted">{t("estimate.cost")}</dt><dd className="font-mono">{estimate ? (estimate.cost_usd === 0 ? t("estimate.free") : `≈ ${estimate.cost_usd.toFixed(2)} $`) : "—"}</dd></div>
          </dl>
          <button className="btn-secondary" onClick={() => launch(false)}>{t("configure.configureVoices")}</button>
          <button className="btn-primary" onClick={() => launch(true)}>{t("configure.dubNow")}</button>
        </div>
      </div>
    </div>
  );
}
