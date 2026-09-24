import { useCallback, useEffect, useState } from "react";
import type { Project } from "./api/types";
import { Banner } from "./components/Feedback";
import { Icon } from "./components/Icon";
import { go, useRoute, type Screen } from "./hooks/useRoute";
import { useTheme } from "./hooks/useTheme";
import { useI18n } from "./i18n";
import { ConfigurePage } from "./pages/ConfigurePage";
import { ExportPage } from "./pages/ExportPage";
import { ImportPage } from "./pages/ImportPage";
import { ProcessingPage } from "./pages/ProcessingPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SpeakersPage } from "./pages/SpeakersPage";
import { errMsg, useApp } from "./store";

const README = "https://github.com/coachccai-blip/mp3-audio-translator#readme";
const FLOW: { screen: Screen | "import"; key: "flow.import" | "flow.configure" | "flow.speakers" | "flow.processing" | "flow.review" | "flow.export" }[] = [
  { screen: "import", key: "flow.import" }, { screen: "configure", key: "flow.configure" }, { screen: "speakers", key: "flow.speakers" },
  { screen: "processing", key: "flow.processing" }, { screen: "review", key: "flow.review" }, { screen: "export", key: "flow.export" },
];

function Logo() {
  return (
    <a href="#/" className="flex items-center gap-2 font-semibold" aria-label="Doublr">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="8" fill="var(--color-primary)" />
        <path d="M7 16h2M11 11v10M15 7v18M19 11v10M23 14v4" stroke="white" strokeWidth="2.4" strokeLinecap="round" /></svg>
      <span className="text-lg">Doublr</span>
    </a>
  );
}

export default function App() {
  const { t } = useI18n();
  const { api, ready, missingKeys } = useApp();
  const route = useRoute();
  const { pref, set } = useTheme();
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const pid = route.name === "project" ? route.id : null;

  const reload = useCallback(() => {
    if (!pid) return;
    api.getProject(pid).then((p) => { setProject(p); setLoadError(null); }).catch((e) => setLoadError(errMsg(e)));
  }, [api, pid]);
  useEffect(() => { setProject(null); reload(); }, [reload]);

  const isDark = document.documentElement.dataset.theme === "dark";
  const screenTitle = route.name === "project" ? t(FLOW.find((f) => f.screen === route.screen)!.key) : route.name === "settings" ? t("settings.title") : null;

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-sm focus:bg-surface focus:px-3 focus:py-2">Contenu</a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <Logo />
          {route.name === "project" && project && (
            <nav aria-label="Étapes" className="hidden flex-1 md:block">
              <ol className="flex items-center gap-1 text-sm">
                {FLOW.map((f, i) => {
                  const current = f.screen === route.screen;
                  const reachable = f.screen === "import" || f.screen === "configure" || f.screen === "speakers" || project.status !== "draft";
                  return (
                    <li key={f.screen} className="flex items-center gap-1">
                      {i > 0 && <Icon name="chevronRight" size={14} className="text-muted" />}
                      <button disabled={!reachable} aria-current={current ? "step" : undefined}
                        onClick={() => go(f.screen === "import" ? "/" : `/p/${project.id}/${f.screen}`)}
                        className={`rounded-sm px-2 py-1 ${current ? "bg-surface-2 font-medium text-text" : "text-muted hover:text-text"} disabled:opacity-40`}>
                        {t(f.key)}
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>
          )}
          <div className="ml-auto flex items-center gap-1">
            <button className="btn-ghost h-9 w-9 p-0" aria-label={t("nav.theme")} onClick={() => set(isDark ? "light" : "dark")}>
              <Icon name={isDark ? "sun" : "moon"} />
            </button>
            <a href="#/settings" className="btn-ghost h-9 w-9 p-0" aria-label={t("nav.settings")}><Icon name="settings" /></a>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        {ready && api.mode === "demo" && (
          <Banner tone="info" title={t("mode.demo.title")} action={
            <div className="flex flex-wrap gap-2">
              <a className="btn-primary btn-sm" href={`${import.meta.env.BASE_URL}Installer-Doublr.bat`} download>{t("mode.demo.install")}</a>
              <a className="btn-secondary btn-sm" href="#/settings">{t("mode.demo.connect")}</a>
              <a className="btn-ghost btn-sm" href={README} target="_blank" rel="noreferrer">{t("mode.demo.howto")}</a>
            </div>}>
            {t("mode.demo.body")}
          </Banner>
        )}
        {route.name === "home" && missingKeys.length > 0 && (
          <Banner tone="warning" action={<a className="btn-secondary btn-sm" href="#/settings">{t("banner.goSettings")}</a>}>
            {t("banner.missingKeys", { keys: missingKeys.join(", ") })}
          </Banner>
        )}
        {screenTitle && (
          <div className="flex items-center gap-3">
            <button className="btn-ghost h-9 w-9 p-0" aria-label={t("common.back")} onClick={() => history.back()}><Icon name="arrowLeft" /></button>
            <h1 className="text-xl font-semibold">{screenTitle}{project && route.name === "project" ? <span className="ml-2 text-md font-normal text-muted">· {project.name}</span> : null}</h1>
          </div>
        )}

        {!ready ? <p className="text-muted">{t("common.loading")}</p>
          : route.name === "home" ? <ImportPage />
          : route.name === "settings" ? <SettingsPage theme={pref} setTheme={set} />
          : loadError ? <Banner tone="danger">{loadError}</Banner>
          : !project ? <p className="text-muted">{t("common.loading")}</p>
          : route.screen === "configure" ? <ConfigurePage project={project} onChange={setProject} />
          : route.screen === "speakers" ? <SpeakersPage project={project} reload={reload} />
          : route.screen === "processing" ? <ProcessingPage project={project} reload={reload} />
          : route.screen === "review" ? <ReviewPage project={project} />
          : <ExportPage project={project} />}
      </main>
    </div>
  );
}
