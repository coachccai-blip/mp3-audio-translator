import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import de from "./de";
import en from "./en";
import es from "./es";
import fr, { type Dict } from "./fr";
import it from "./it";
import pl from "./pl";
import sv from "./sv";
import zh from "./zh";

export const UI_LANGS = { fr, en, zh, de, sv, es, it, pl } as const;
export type UiLang = keyof typeof UI_LANGS;
export const UI_LANG_NAMES: Record<UiLang, string> = {
  fr: "Français", en: "English", zh: "中文", de: "Deutsch", sv: "Svenska", es: "Español", it: "Italiano", pl: "Polski",
};
export type TKey = keyof Dict;

function initialLang(): UiLang {
  try {
    const saved = localStorage.getItem("doublr.lang") as UiLang | null;
    if (saved && saved in UI_LANGS) return saved;
  } catch { /* stockage indisponible */ }
  const nav = (navigator.language || "fr").slice(0, 2) as UiLang;
  return nav in UI_LANGS ? nav : "fr";
}

interface I18nCtx { lang: UiLang; setLang: (l: UiLang) => void; t: (k: TKey, vars?: Record<string, string | number>) => string }
const Ctx = createContext<I18nCtx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<UiLang>(initialLang);
  const setLang = useCallback((l: UiLang) => {
    setLangState(l);
    try { localStorage.setItem("doublr.lang", l); } catch { /* */ }
    document.documentElement.lang = l;
  }, []);
  const t = useCallback((k: TKey, vars?: Record<string, string | number>) => {
    let s: string = UI_LANGS[lang][k] ?? fr[k] ?? k;
    if (vars) for (const [name, v] of Object.entries(vars)) s = s.split(`{${name}}`).join(String(v));
    return s;
  }, [lang]);
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const c = useContext(Ctx);
  if (!c) throw new Error("I18nProvider manquant");
  return c;
}
