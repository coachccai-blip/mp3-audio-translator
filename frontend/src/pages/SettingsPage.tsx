import { useEffect, useState } from "react";
import type { Voice } from "../api/types";
import { useToast } from "../components/Feedback";
import { Icon } from "../components/Icon";
import { PlayButton } from "../components/PlayButton";
import { fmtBytes } from "../format";
import type { ThemePref } from "../hooks/useTheme";
import { UI_LANG_NAMES, useI18n, type UiLang } from "../i18n";
import { errMsg, useApp } from "../store";

const KEY_SERVICES: Record<string, string> = {
  ANTHROPIC_API_KEY: "anthropic", AZURE_SPEECH_KEY: "azure", ELEVENLABS_API_KEY: "elevenlabs", HF_TOKEN: "huggingface",
};

export function SettingsPage({ theme, setTheme }: { theme: ThemePref; setTheme: (t: ThemePref) => void }) {
  const { t, lang, setLang } = useI18n();
  const { api, apiBase, connect, settings, refreshSettings, localeInfo } = useApp();
  const toast = useToast();
  const [server, setServer] = useState(apiBase);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, { ok: boolean; error?: string } | "busy">>({});
  const [voices, setVoices] = useState<Record<string, Voice[]>>({});
  const [sound, setSound] = useState(() => { try { return localStorage.getItem("doublr.sound") !== "off"; } catch { return true; } });

  useEffect(() => { api.allVoices().then(setVoices).catch(() => setVoices({})); }, [api]);

  const save = async (body: Parameters<typeof api.putSettings>[0]) => {
    try { await api.putSettings(body); await refreshSettings(); toast({ tone: "success", text: t("settings.saved") }); }
    catch (e) { toast({ tone: "danger", text: errMsg(e) }); }
  };
  const local = api.mode === "local";

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="card space-y-3 p-5">
        <h2 className="flex items-center gap-2 font-semibold"><Icon name="server" />{t("settings.server")}</h2>
        <div className="flex gap-2">
          <input aria-label={t("settings.serverUrl")} className="input font-mono" value={server} onChange={(e) => setServer(e.target.value)} />
          <button className="btn-secondary" onClick={async () => toast(await connect(server)
            ? { tone: "success", text: t("settings.connected") } : { tone: "danger", text: `${t("settings.unreachable")} : ${server}` })}>
            {t("settings.connect")}
          </button>
        </div>
        <p className={`inline-flex items-center gap-1 text-sm ${local ? "text-success" : "text-accent"}`}>
          <Icon name={local ? "check" : "alert"} size={14} />{local ? `${t("settings.connected")} (${apiBase})` : t("mode.demo.title")}
        </p>
        {settings && local && (
          <div className="text-sm">
            <p className="label mt-2">{t("settings.capabilities")}</p>
            <ul className="flex flex-wrap gap-2">
              {Object.entries(settings.capabilities).map(([k, ok]) => (
                <li key={k} className="chip"><Icon name={ok ? "check" : "x"} size={12} className={ok ? "text-success" : "text-danger"} />{k}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="card space-y-3 p-5">
        <h2 className="font-semibold">{t("settings.keys")}</h2>
        <p className="text-xs text-muted">{t("settings.keysHelp")}</p>
        {Object.entries(KEY_SERVICES).map(([key, service]) => {
          const configured = settings?.keys[key];
          const test = tests[key];
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-mono text-xs">{key}</span>
                <span className={`inline-flex items-center gap-1 text-xs ${configured ? "text-success" : "text-muted"}`}>
                  <Icon name={configured ? "check" : "x"} size={12} />{configured ? t("settings.configured") : t("settings.missing")}
                </span>
              </div>
              <div className="flex gap-2">
                <input type="password" autoComplete="off" className="input font-mono" placeholder={t("settings.newKey")} disabled={!local}
                  value={keys[key] || ""} onChange={(e) => setKeys({ ...keys, [key]: e.target.value })} />
                <button className="btn-secondary btn-sm" disabled={!local || !keys[key]} onClick={() => { save({ keys: { [key]: keys[key] } }); setKeys({ ...keys, [key]: "" }); }}>
                  {t("common.save")}
                </button>
                <button className="btn-ghost btn-sm" disabled={!local || !configured} onClick={async () => {
                  setTests({ ...tests, [key]: "busy" });
                  const r = await api.testService(service);
                  setTests((x) => ({ ...x, [key]: r }));
                }}>{test === "busy" ? <Icon name="refresh" size={14} className="animate-spin" /> : t("settings.test")}</button>
              </div>
              {test && test !== "busy" && (
                <p className={`text-xs ${test.ok ? "text-success" : "text-danger"}`}>{test.ok ? t("settings.ok") : test.error}</p>
              )}
            </div>
          );
        })}
      </section>

      <section className="card space-y-4 p-5">
        <label className="block"><span className="label">{t("settings.translation")}</span>
          <select className="input" disabled={!local} value={settings?.translator || "auto"} onChange={(e) => save({ values: { DOUBLR_TRANSLATOR: e.target.value } })}>
            <option value="auto">{t("translator.auto")}</option>
            <option value="local">{t("translator.local")}</option>
            <option value="claude">{t("translator.claude")}</option>
          </select>
        </label>
        {settings?.translator_engine === "local" && (
          <div>
            <label className="block"><span className="label">{t("settings.localModel")}</span>
              <select className="input" disabled={!local} value={settings?.local_llm || "gemma3:4b"} onChange={(e) => save({ values: { DOUBLR_LOCAL_LLM: e.target.value } })}>
                <option value="gemma3:4b">Gemma 3 4B — {t("model.light")}</option>
                <option value="gemma3:12b">Gemma 3 12B — {t("model.better")}</option>
                <option value="qwen2.5:7b">Qwen 2.5 7B</option>
              </select>
            </label>
            {settings.ollama && (
              <p className={`mt-1 inline-flex items-center gap-1 text-xs ${settings.ollama.model_ready ? "text-success" : "text-accent"}`}>
                <Icon name={settings.ollama.model_ready ? "check" : "alert"} size={12} />
                {settings.ollama.model_ready ? t("settings.ollamaOk") : t("settings.ollamaMissing", { model: settings.ollama.model })}
              </p>
            )}
          </div>
        )}
        <label className="block"><span className="label">{t("settings.voicePref")}</span>
          <select className="input" disabled={!local} value={settings?.tts_provider || "auto"} onChange={(e) => save({ values: { DOUBLR_TTS_PROVIDER: e.target.value } })}>
            <option value="auto">{t("voicePref.auto")}</option>
            <option value="kokoro">Kokoro — {t("voice.free")} HD</option>
            <option value="piper">Piper — {t("voice.free")}</option>
            <option value="azure">Azure Neural TTS</option>
            <option value="elevenlabs">ElevenLabs</option>
          </select>
        </label>
        <label className="block"><span className="label">{t("settings.whisper")}</span>
          <select className="input" disabled={!local} value={settings?.whisper_model || "large-v3"} onChange={(e) => save({ values: { DOUBLR_WHISPER_MODEL: e.target.value } })}>
            <option value="large-v3">large-v3</option><option value="large-v3-turbo">large-v3-turbo</option>
          </select>
        </label>
        <label className="block"><span className="label">{t("settings.device")}</span>
          <select className="input" disabled={!local} value={settings?.device || "auto"} onChange={(e) => save({ values: { DOUBLR_DEVICE: e.target.value } })}>
            <option value="auto">auto</option><option value="cpu">CPU</option><option value="cuda">GPU (CUDA)</option><option value="mps">GPU (Apple MPS)</option>
          </select>
        </label>
      </section>

      <section className="card space-y-4 p-5">
        <label className="block"><span className="label">{t("settings.uiLang")}</span>
          <select className="input" value={lang} onChange={(e) => setLang(e.target.value as UiLang)}>
            {Object.entries(UI_LANG_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <fieldset><legend className="label">{t("settings.theme")}</legend>
          <div className="flex gap-2">
            {(["light", "dark", "system"] as ThemePref[]).map((th) => (
              <label key={th} className={`btn-secondary btn-sm cursor-pointer ${theme === th ? "border-primary text-primary" : ""}`}>
                <input type="radio" name="theme" className="sr-only" checked={theme === th} onChange={() => setTheme(th)} />{t(`theme.${th}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-[var(--color-primary)]" checked={sound}
            onChange={(e) => { setSound(e.target.checked); try { localStorage.setItem("doublr.sound", e.target.checked ? "on" : "off"); } catch { /* */ } }} />
          {t("settings.sound")}
        </label>
      </section>

      {settings && local && (
        <section className="card space-y-3 p-5">
          <h2 className="font-semibold">{t("settings.folders")}</h2>
          <label className="block"><span className="label">{t("settings.output")}</span>
            <input className="input font-mono" defaultValue={settings.output_dir} onBlur={(e) => e.target.value !== settings.output_dir && save({ values: { DOUBLR_OUTPUT_DIR: e.target.value } })} />
          </label>
          <div className="flex items-center justify-between text-sm">
            <span>{t("settings.cache", { size: fmtBytes(settings.cache_bytes) })}</span>
            <button className="btn-secondary btn-sm" onClick={async () => { const r = await api.clearCache(); toast({ tone: "success", text: `−${fmtBytes(r.freed_bytes)}` }); refreshSettings(); }}>
              <Icon name="trash" size={14} />{t("settings.clearCache")}
            </button>
          </div>
        </section>
      )}

      <section className="card space-y-2 p-5">
        <h2 className="font-semibold">{t("settings.privacy")}</h2>
        <p className="text-sm text-muted">{t("settings.privacyText")}</p>
      </section>

      <section className="card space-y-3 p-5 lg:col-span-2">
        <h2 className="font-semibold">{t("settings.catalog")}</h2>
        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(voices).map(([loc, vs]) => (
            <div key={loc}>
              <p className="mb-1 text-sm font-medium">{localeInfo(loc).flag} {loc}</p>
              <ul className="space-y-1">
                {vs.map((v) => (
                  <li key={v.id} className={`flex items-center gap-2 text-sm ${v.disabled ? "opacity-50" : ""}`}>
                    <PlayButton id={`sample-${v.id}`} label={v.display_name} size={24} variant="outline" load={() => api.voiceSample(v)} />
                    <span className="flex-1">{v.display_name} <span className="text-xs text-muted">· {t(`gender.${v.gender as "male"}`)} · {v.free ? t("voice.free") : v.provider}{v.quality === "hd" ? " · HD" : ""}{v.validated ? "" : ` · ${t("voice.toConfirm")}`}</span></span>
                    {local && (
                      <button className="text-xs text-primary underline" onClick={async () => {
                        const nv = await api.toggleVoice(v.id, !v.disabled);
                        setVoices((all) => ({ ...all, [loc]: all[loc].map((x) => (x.id === v.id ? nv : x)) }));
                      }}>{v.disabled ? t("settings.enable") : t("settings.disable")}</button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
