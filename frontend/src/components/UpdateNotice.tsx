import { useEffect, useState } from "react";
import type { Api, VersionInfo } from "../api/types";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";
import { Banner, useToast } from "./Feedback";

const REPO = "coachccai-blip/mp3-audio-translator";

/** Dernière version publiée sur GitHub (mise en cache 10 min pour ménager la limite de l'API GitHub). */
async function latestSha(branch: string): Promise<string | null> {
  const key = `doublr.latest.${branch}`;
  try {
    const cached = JSON.parse(sessionStorage.getItem(key) || "null");
    if (cached && Date.now() - cached.at < 600_000) return cached.sha;
  } catch { /* stockage indisponible */ }
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/commits/${encodeURIComponent(branch)}`,
      { headers: { Accept: "application/vnd.github.sha" } });
    if (!res.ok) return null;
    const sha = (await res.text()).trim();
    try { sessionStorage.setItem(key, JSON.stringify({ sha, at: Date.now() })); } catch { /* idem */ }
    return sha;
  } catch {
    return null;
  }
}

export interface UpdateState { info: VersionInfo | null; latest: string | null; available: boolean }

export function useUpdate(api: Api): UpdateState {
  const [state, setState] = useState<UpdateState>({ info: null, latest: null, available: false });
  useEffect(() => {
    let alive = true;
    if (api.mode !== "local") return;
    api.version().then(async (info) => {
      if (!info.can_update) { if (alive) setState({ info, latest: null, available: false }); return; }
      const latest = await latestSha(info.branch);
      // Installation antérieure à ce bouton (version inconnue) : forcément plus ancienne.
      if (alive) setState({ info, latest, available: !!latest && latest !== info.sha });
    }).catch(() => { /* serveur ancien sans /api/version */ });
    return () => { alive = false; };
  }, [api]);
  return state;
}

export function useStartUpdate() {
  const { t } = useI18n();
  const { api } = useApp();
  const toast = useToast();
  const [started, setStarted] = useState(false);
  const start = async () => {
    if (!window.confirm(t("update.confirm"))) return;
    try { await api.startUpdate(); setStarted(true); }
    catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };
  return { started, start };
}

export function UpdateBanner() {
  const { t } = useI18n();
  const { api } = useApp();
  const { available } = useUpdate(api);
  const { started, start } = useStartUpdate();
  if (started) return <Banner tone="info" title={t("update.startedTitle")}>{t("update.started")}</Banner>;
  if (!available) return null;
  return (
    <Banner tone="info" title={t("update.available")} action={<button className="btn-primary btn-sm" onClick={start}>{t("update.button")}</button>}>
      {t("update.body")}
    </Banner>
  );
}

export function UpdateSection() {
  const { t } = useI18n();
  const { api } = useApp();
  const { info, available } = useUpdate(api);
  const { started, start } = useStartUpdate();
  if (!info?.can_update) return null;
  return (
    <section className="card space-y-3 p-5">
      <h2 className="font-semibold">{t("update.title")}</h2>
      <p className="text-sm text-muted">
        {t("update.installed", { v: info.sha ? info.sha.slice(0, 7) : "?" })} · {available ? t("update.available") : t("update.upToDate")}
      </p>
      {started ? <p className="text-sm">{t("update.started")}</p>
        : <button className={available ? "btn-primary" : "btn-secondary"} onClick={start}>{t("update.button")}</button>}
    </section>
  );
}
