// Copie le catalogue (config/*.yaml) en JSON pour le mode démo du frontend (GitHub Pages).
import { copyFileSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const languages = YAML.parse(readFileSync(resolve(root, "config/languages.yaml"), "utf8")).languages;
const voicesRaw = YAML.parse(readFileSync(resolve(root, "config/voices.yaml"), "utf8"));
const voices = {};
for (const [locale, list] of Object.entries(voicesRaw)) {
  voices[locale] = list.map((v) => ({
    id: v.id, provider: v.provider, locale, display_name: v.display_name, gender: v.gender,
    age_range: v.age_range, styles: v.styles || [], validated: Boolean(v.validated_by && v.validated_on),
    status: v.status || "to_confirm", default: Boolean(v.default), disabled: false,
  }));
}
const out = resolve(root, "frontend/src/data/catalog.json");
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify({ languages, voices }, null, 1));
console.log("catalog.json écrit");

// Installateur Windows téléchargeable depuis le site (GitHub Pages).
mkdirSync(resolve(root, "frontend/public"), { recursive: true });
copyFileSync(resolve(root, "installer/windows/Installer-Doublr.bat"), resolve(root, "frontend/public/Installer-Doublr.bat"));
