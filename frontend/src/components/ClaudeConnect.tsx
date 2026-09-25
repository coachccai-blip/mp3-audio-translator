import { useState } from "react";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";
import { useToast } from "./Feedback";
import { Icon } from "./Icon";

const KEYS_URL = "https://console.anthropic.com/settings/keys";

/** Page d'accueil : brancher Claude pour une traduction de meilleure qualité (clé API Anthropic). */
export function ClaudeConnect() {
  const { t } = useI18n();
  const { api, settings, refreshSettings } = useApp();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  if (api.mode !== "local" || !settings) return null;
  const connected = settings.keys.ANTHROPIC_API_KEY && settings.translator_engine === "claude";

  const connect = async () => {
    if (!key.trim()) return;
    setBusy(true);
    try {
      await api.putSettings({ keys: { ANTHROPIC_API_KEY: key.trim() }, values: { DOUBLR_TRANSLATOR: "auto" } });
      const test = await api.testService("anthropic");
      if (!test.ok) {
        await api.putSettings({ remove_keys: ["ANTHROPIC_API_KEY"] });
        toast({ tone: "danger", text: t("claude.invalid", { e: test.error || "" }) });
      } else {
        toast({ tone: "success", text: t("claude.connected") });
        setOpen(false);
        setKey("");
      }
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    } finally {
      setBusy(false);
      await refreshSettings();
    }
  };
  const disconnect = async () => {
    try { await api.putSettings({ remove_keys: ["ANTHROPIC_API_KEY"] }); await refreshSettings(); toast({ tone: "info", text: t("claude.disconnected") }); }
    catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };

  if (connected) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 text-sm">
        <Icon name="check" className="text-success" />
        <span className="flex-1">{t("claude.active")}</span>
        <button className="btn-ghost btn-sm" onClick={disconnect}>{t("claude.disconnect")}</button>
      </div>
    );
  }
  return (
    <section className="rounded-md border border-border bg-surface-2 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex-1"><span className="font-medium">{t("claude.title")}</span> <span className="text-muted">{t("claude.pitch")}</span></span>
        {!open && <button className="btn-primary btn-sm" onClick={() => setOpen(true)}>{t("claude.button")}</button>}
      </div>
      {open && (
        <div className="mt-3 space-y-3">
          <ol className="list-decimal space-y-1 pl-5 text-muted">
            <li>{t("claude.step1")} <a className="text-primary underline" href={KEYS_URL} target="_blank" rel="noreferrer">{t("claude.openConsole")}</a></li>
            <li>{t("claude.step2")}</li>
          </ol>
          <p className="text-xs text-muted">{t("claude.note")}</p>
          <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); connect(); }}>
            <input className="input min-w-0 flex-1" type="password" autoComplete="off" placeholder="sk-ant-…" aria-label={t("claude.keyLabel")}
              value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn-primary" type="submit" disabled={busy || !key.trim()}>{busy ? t("claude.testing") : t("claude.connect")}</button>
            <button className="btn-ghost" type="button" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
          </form>
        </div>
      )}
    </section>
  );
}
