import { useEffect, useState } from "react";
import type { Project } from "../api/types";
import { ClaudeConnect } from "../components/ClaudeConnect";
import { DropZone } from "../components/DropZone";
import { useToast } from "../components/Feedback";
import { FileRow } from "../components/FileRow";
import { Icon } from "../components/Icon";
import { go } from "../hooks/useRoute";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";

export function ImportPage() {
  const { t, lang } = useI18n();
  const { api, localeInfo } = useApp();
  const toast = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<Project[]>([]);

  useEffect(() => { api.listProjects().then(setRecent).catch(() => setRecent([])); }, [api]);

  const add = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    try {
      setProject(project ? await api.addFiles(project.id, files) : await api.createProject(files));
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    } finally {
      setBusy(false);
    }
  };
  const valid = project?.files.filter((f) => f.status !== "invalid") || [];

  return (
    <div className="space-y-10">
      {!project && <p className="max-w-2xl text-lg text-muted">{t("import.tagline")}</p>}
      <DropZone onFiles={add} compact={Boolean(project)} />
      {!project && <ClaudeConnect />}
      {busy && <p className="flex items-center gap-2 text-sm text-muted" role="status"><Icon name="refresh" className="animate-spin" size={16} />{t("import.analyzing")}</p>}

      {project && project.files.length > 0 && (
        <section aria-labelledby="files-h" className="space-y-3">
          <h2 id="files-h" className="text-sm font-semibold uppercase tracking-wide text-muted">{t("import.files")}</h2>
          <ul className="space-y-2">
            {project.files.map((f) => (
              <FileRow key={f.id} file={f} onRemove={async () => setProject(await api.removeFile(project.id, f.id))} />
            ))}
          </ul>
          <div className="flex justify-end">
            <button className="btn-primary" disabled={!valid.length} onClick={() => go(`/p/${project.id}/configure`)}>
              {t("common.continue")} <Icon name="chevronRight" size={16} />
            </button>
          </div>
        </section>
      )}

      <section aria-labelledby="recent-h" className="space-y-3">
        <h2 id="recent-h" className="text-sm font-semibold uppercase tracking-wide text-muted">{t("import.recent")}</h2>
        {recent.length === 0 ? (
          <p className="text-sm text-muted">{t("import.noRecent")}</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {recent.map((p) => (
              <li key={p.id} className="card flex flex-col gap-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <span className="truncate font-medium">{p.name}</span>
                  <span className="chip shrink-0">{t(p.status === "done" ? "status.done" : p.status === "processing" ? "status.running" : "status.pending")}</span>
                </div>
                <div className="text-sm" aria-label={`${p.source_lang || "?"} → ${p.targets.join(", ")}`}>
                  <span>{p.source_lang ? localeInfo(p.source_lang).flag : "🎙️"}</span>
                  <span className="mx-1 text-muted">→</span>
                  {p.targets.map((l) => <span key={l} title={l} className="mr-1">{localeInfo(l).flag}</span>)}
                </div>
                <div className="text-xs text-muted">{new Date(p.created_at).toLocaleDateString(lang)} · {p.files.length} fichier(s)</div>
                <div className="mt-auto flex gap-2">
                  <button className="btn-secondary btn-sm" onClick={() => go(`/p/${p.id}/${p.status === "done" ? "review" : "configure"}`)}>{t("common.open")}</button>
                  {p.status === "done" && <button className="btn-ghost btn-sm" onClick={() => go(`/p/${p.id}/export`)}>{t("import.reexport")}</button>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
