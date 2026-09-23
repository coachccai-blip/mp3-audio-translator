import { useCallback, useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";

function read(): ThemePref {
  try {
    return (localStorage.getItem("doublr.theme") as ThemePref) || "system";
  } catch {
    return "system";
  }
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = pref === "dark" || (pref === "system" && mq.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);
  const set = useCallback((p: ThemePref) => {
    setPref(p);
    try { localStorage.setItem("doublr.theme", p); } catch { /* */ }
  }, []);
  return { pref, set };
}
