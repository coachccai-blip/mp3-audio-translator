import { useEffect, useState } from "react";
import type { Language, Locale, Voice } from "../api/types";
import { useI18n } from "../i18n";
import { useApp } from "../store";
import { Icon } from "./Icon";
import { PlayButton } from "./PlayButton";

// Grille des 8 langues cibles : multi-sélection, variante régionale, écoute d'un exemple (brief §8.3, écran 2).
export function LanguageGrid({ languages, selected, exclude, onChange }: {
  languages: Language[]; selected: Locale[]; exclude?: string | null; onChange: (locales: Locale[]) => void;
}) {
  const { t, lang } = useI18n();
  const visible = languages.filter((l) => l.code !== exclude);
  const selectedFor = (code: string) => selected.find((loc) => loc.split("-")[0] === code);

  const toggle = (l: Language) => {
    const cur = selectedFor(l.code);
    onChange(cur ? selected.filter((x) => x !== cur) : [...selected, l.default_locale]);
  };
  const setVariant = (l: Language, locale: Locale) =>
    onChange(selected.map((x) => (x.split("-")[0] === l.code ? locale : x)));

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {visible.map((l) => {
        const loc = selectedFor(l.code);
        const on = Boolean(loc);
        const variant = l.variants.find((v) => v.locale === (loc || l.default_locale)) || l.variants[0];
        return (
          <div key={l.code}
            className={`relative flex flex-col rounded-lg border-2 bg-surface transition-transform duration-150 ${on ? "scale-[1.02] border-primary" : "border-border hover:border-muted"}`}>
            <button type="button" aria-pressed={on} onClick={() => toggle(l)}
              className="flex flex-1 flex-col items-start gap-1 rounded-lg p-4 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
              <span className="text-2xl" aria-hidden>{variant.flag}</span>
              <span className="text-lg font-semibold leading-tight" lang={l.code}>{l.native_name}</span>
              <span className="text-xs text-muted">{l.names[lang]}</span>
            </button>
            {on && (
              <span className="check-pop absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-white" aria-hidden>
                <Icon name="check" size={14} strokeWidth={3} />
              </span>
            )}
            {on && loc && <VariantRow language={l} locale={loc} onVariant={(v) => setVariant(l, v)} label={t("configure.variant")} listen={t("configure.listen")} />}
          </div>
        );
      })}
    </div>
  );
}

function VariantRow({ language, locale, onVariant, label, listen }: {
  language: Language; locale: Locale; onVariant: (l: Locale) => void; label: string; listen: string;
}) {
  const { api } = useApp();
  const [voice, setVoice] = useState<Voice | null>(null);
  useEffect(() => {
    api.voices(locale).then((vs) => setVoice(vs.find((v) => v.default) || vs[0] || null)).catch(() => setVoice(null));
  }, [api, locale]);
  return (
    <div className="flex items-center gap-2 border-t border-border px-3 py-2">
      {language.variants.length > 1 ? (
        <select aria-label={`${label} — ${language.native_name}`} value={locale} onChange={(e) => onVariant(e.target.value)}
          className="min-w-0 flex-1 rounded-sm border border-border bg-surface px-2 py-1 text-xs">
          {language.variants.map((v) => <option key={v.locale} value={v.locale}>{v.flag} {v.label} ({v.locale})</option>)}
        </select>
      ) : (
        <span className="flex-1 font-mono text-xs text-muted">{locale}</span>
      )}
      {voice && <PlayButton id={`sample-${voice.id}`} label={`${listen} (${voice.display_name})`} size={28}
        load={() => api.voiceSample(voice)} />}
    </div>
  );
}
