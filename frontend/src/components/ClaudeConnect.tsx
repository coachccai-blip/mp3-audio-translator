import { useState } from "react";
import { useI18n } from "../i18n";
import { errMsg, useApp } from "../store";
import { useToast } from "./Feedback";
import { Icon } from "./Icon";

const KEYS_URL = "https://console.anthropic.com/settings/keys";

type Mode = "closed" | "account" | "waiting" | "key";

/** Page d'accueil : traduire avec Claude, via le compte Claude (Claude Code) ou une clé API Anthropic. */
export function ClaudeConnect() {
  const { t } = useI18n();
  const { api, settings, refreshSettings } = useApp();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("closed");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  if (api.mode !== "local" || !settings) return null;
  const engine = settings.translator_engine;
  const connected = engine === "claude-code" || (engine === "claude" && settings.keys.ANTHROPIC_API_KEY);

  const openLogin = async () => {
    setBusy(true);
    try { await api.claudeLogin(); setMode("waiting"); }
    catch (e) { toast({ tone: "danger", text: errMsg(e) }); setMode("waiting"); }
    finally { setBusy(false); }
  };
  const verifyAccount = async () => {
    setBusy(true);
    try {
      const test = await api.testService("claude-code");
      if (!test.ok) { toast({ tone: "danger", text: t("claude.accountFailed", { e: test.error || "" }) }); return; }
      await api.putSettings({ values: { DOUBLR_TRANSLATOR: "claude-code" } });
      toast({ tone: "success", text: t("claude.connected") });
      setMode("closed");
    } catch (e) {
      toast({ tone: "danger", text: errMsg(e) });
    } finally {
      setBusy(false);
      await refreshSettings();
    }
  };
  const connectKey = async () => {
    if (!key.trim()) return;
    setBusy(true);
    try {
      await api.putSettings({ keys: { ANTHROPIC_API_KEY: key.trim() }, values: { DOUBLR_TRANSLATOR: "claude" } });
      const test = await api.testService("anthropic");
      if (!test.ok) {
        await api.putSettings({ remove_keys: ["ANTHROPIC_API_KEY"], values: { DOUBLR_TRANSLATOR: "auto" } });
        toast({ tone: "danger", text: t("claude.invalid", { e: test.error || "" }) });
      } else {
        toast({ tone: "success", text: t("claude.connected") });
        setMode("closed");
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
    try {
      await api.putSettings(engine === "claude"
        ? { remove_keys: ["ANTHROPIC_API_KEY"], values: { DOUBLR_TRANSLATOR: "auto" } }
        : { values: { DOUBLR_TRANSLATOR: "local" } });
      await refreshSettings();
      toast({ tone: "info", text: t("claude.disconnected") });
    } catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };

  if (connected) {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 text-sm">
        <Icon name="check" className="text-success" />
        <span className="flex-1">{engine === "claude-code" ? t("claude.accountActive") : t("claude.active")}</span>
        <button className="btn-ghost btn-sm" onClick={disconnect}>{t("claude.disconnect")}</button>
      </div>
    );
  }
  return (
    <section className="rounded-md border border-border bg-surface-2 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex-1"><span className="font-medium">{t("claude.title")}</span> <span className="text-muted">{t("claude.pitch")}</span></span>
        {mode === "closed" && (
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary btn-sm" onClick={() => setMode("account")}>{t("claude.account")}</button>
            <button className="btn-ghost btn-sm" onClick={() => setMode("key")}>{t("claude.orKey")}</button>
          </div>
        )}
      </div>

      {mode === "account" && (
        <div className="mt-3 space-y-3">
          <p className="text-muted">{t("claude.accountIntro")}</p>
          <p className="text-xs text-muted">{t("claude.accountNote")}</p>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy} onClick={openLogin}>{t("claude.openLogin")}</button>
            {settings.claude_code?.installed && <button className="btn-secondary" disabled={busy} onClick={verifyAccount}>{busy ? t("claude.testing") : t("claude.verify")}</button>}
            <button className="btn-ghost" onClick={() => setMode("closed")}>{t("common.cancel")}</button>
          </div>
        </div>
      )}

      {mode === "waiting" && (
        <div className="mt-3 space-y-3">
          <p className="text-muted">{t("claude.waiting")}</p>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy} onClick={verifyAccount}>{busy ? t("claude.testing") : t("claude.verify")}</button>
            <button className="btn-ghost" disabled={busy} onClick={openLogin}>{t("claude.reopen")}</button>
            <button className="btn-ghost" onClick={() => setMode("closed")}>{t("common.cancel")}</button>
          </div>
        </div>
      )}

      {mode === "key" && (
        <div className="mt-3 space-y-3">
          <ol className="list-decimal space-y-1 pl-5 text-muted">
            <li>{t("claude.step1")} <a className="text-primary underline" href={KEYS_URL} target="_blank" rel="noreferrer">{t("claude.openConsole")}</a></li>
            <li>{t("claude.step2")}</li>
          </ol>
          <p className="text-xs text-muted">{t("claude.note")}</p>
          <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); connectKey(); }}>
            <input className="input min-w-0 flex-1" type="password" autoComplete="off" placeholder="sk-ant-…" aria-label={t("claude.keyLabel")}
              value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn-primary" type="submit" disabled={busy || !key.trim()}>{busy ? t("claude.testing") : t("claude.connect")}</button>
            <button className="btn-ghost" type="button" onClick={() => setMode("closed")}>{t("common.cancel")}</button>
          </form>
        </div>
      )}
    </section>
  );
}
