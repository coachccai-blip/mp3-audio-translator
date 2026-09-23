import { useEffect, useState } from "react";

export type Screen = "configure" | "speakers" | "processing" | "review" | "export";
export type Route = { name: "home" } | { name: "settings" } | { name: "project"; id: string; screen: Screen };

const SCREENS: Screen[] = ["configure", "speakers", "processing", "review", "export"];

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "p" && parts[1]) {
    const screen = (SCREENS as string[]).includes(parts[2]) ? (parts[2] as Screen) : "configure";
    return { name: "project", id: parts[1], screen };
  }
  return { name: "home" };
}

export function go(path: string) {
  window.location.hash = path.startsWith("#") ? path : `#${path}`;
  window.scrollTo({ top: 0 });
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
