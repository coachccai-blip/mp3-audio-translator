import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createDemoApi } from "./api/demo";
import { createHttpApi, storedApiBase } from "./api/http";
import type { Api, Language, SettingsT } from "./api/types";
import { useI18n } from "./i18n";

interface AppCtx {
  api: Api;
  ready: boolean;
  apiBase: string;
  languages: Language[];
  settings: SettingsT | null;
  missingKeys: string[];
  connect: (base: string) => Promise<boolean>;
  refreshSettings: () => Promise<void>;
  langName: (code: string | null | undefined) => string;
  localeInfo: (locale: string) => { flag: string; native: string; label: string; name: string };
}
const Ctx = createContext<AppCtx | null>(null);
const demo = createDemoApi();

export function AppProvider({ children }: { children: ReactNode }) {
  const { lang } = useI18n();
  const [api, setApi] = useState<Api>(demo);
  const [ready, setReady] = useState(false);
  const [apiBase, setApiBase] = useState(storedApiBase());
  const [languages, setLanguages] = useState<Language[]>([]);
  const [settings, setSettings] = useState<SettingsT | null>(null);

  const connect = useCallback(async (base: string) => {
    const http = createHttpApi(base);
    const ok = await http.health();
    if (ok) {
      try { localStorage.setItem("doublr.api", base); } catch { /* */ }
      setApiBase(base);
      setApi(http);
    }
    return ok;
  }, []);

  useEffect(() => {
    connect(storedApiBase()).finally(() => setReady(true));
  }, [connect]);

  const refreshSettings = useCallback(async () => {
    try { setSettings(await api.getSettings()); } catch { setSettings(null); }
  }, [api]);

  useEffect(() => {
    api.languages().then(setLanguages).catch(() => setLanguages([]));
    refreshSettings();
  }, [api, refreshSettings]);

  const missingKeys = useMemo(() => {
    if (!settings || api.mode === "demo") return [];
    return settings.missing ?? [];
  }, [settings, api.mode]);

  const langName = useCallback((code: string | null | undefined) => {
    if (!code) return "—";
    const l = languages.find((x) => x.code === code.split("-")[0]);
    return l ? l.names[lang] || l.native_name : code;
  }, [languages, lang]);

  const localeInfo = useCallback((locale: string) => {
    const l = languages.find((x) => x.code === locale.split("-")[0]);
    const v = l?.variants.find((x) => x.locale === locale) || l?.variants.find((x) => x.locale === l.default_locale) || l?.variants[0];
    return { flag: v?.flag || "🏳️", native: l?.native_name || locale, label: v?.label || locale, name: l ? l.names[lang] || l.native_name : locale };
  }, [languages, lang]);

  const value = useMemo(() => ({ api, ready, apiBase, languages, settings, missingKeys, connect, refreshSettings, langName, localeInfo }),
    [api, ready, apiBase, languages, settings, missingKeys, connect, refreshSettings, langName, localeInfo]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp() {
  const c = useContext(Ctx);
  if (!c) throw new Error("AppProvider manquant");
  return c;
}

export function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}
