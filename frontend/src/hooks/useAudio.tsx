// Lecteur partagé pour les pré-écoutes (échantillons de voix, extraits) : un seul son à la fois.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { AudioSource } from "../api/types";

interface PreviewState { playingId: string | null; loadingId: string | null; progress: number; error: string | null }
interface PreviewCtx extends PreviewState {
  toggle: (id: string, load: () => Promise<AudioSource>, range?: { start: number; end: number }) => void;
  stop: () => void;
}
const Ctx = createContext<PreviewCtx | null>(null);

export function PreviewProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [state, setState] = useState<PreviewState>({ playingId: null, loadingId: null, progress: 0, error: null });
  const rangeEnd = useRef<number | null>(null);
  const rangeStart = useRef(0);

  const stop = useCallback(() => {
    audio.current?.pause();
    window.speechSynthesis?.cancel();
    setState((s) => ({ ...s, playingId: null, loadingId: null, progress: 0 }));
  }, []);

  useEffect(() => {
    const a = new Audio();
    audio.current = a;
    const onTime = () => {
      const end = rangeEnd.current ?? a.duration;
      const start = rangeStart.current;
      if (rangeEnd.current !== null && a.currentTime >= rangeEnd.current) { stop(); return; }
      setState((s) => ({ ...s, progress: end > start ? (a.currentTime - start) / (end - start) : 0 }));
    };
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("ended", stop);
    return () => { a.pause(); a.removeEventListener("timeupdate", onTime); a.removeEventListener("ended", stop); };
  }, [stop]);

  const toggle = useCallback<PreviewCtx["toggle"]>(async (id, load, range) => {
    if (state.playingId === id || state.loadingId === id) { stop(); return; }
    stop();
    setState({ playingId: null, loadingId: id, progress: 0, error: null });
    try {
      const src = await load();
      if (src.kind === "speech") {
        const u = new SpeechSynthesisUtterance(src.text);
        u.lang = src.lang;
        const voice = speechSynthesis.getVoices().find((v) => v.lang.replace("_", "-") === src.lang);
        if (voice) u.voice = voice;
        u.onend = stop;
        let p = 0;
        const timer = setInterval(() => { p = Math.min(0.95, p + 0.05); setState((s) => s.playingId === id ? { ...s, progress: p } : s); }, 150);
        u.onend = () => { clearInterval(timer); stop(); };
        speechSynthesis.speak(u);
      } else {
        const a = audio.current!;
        a.src = src.url;
        rangeStart.current = range ? range.start : 0;
        rangeEnd.current = range ? range.end : null;
        if (range) a.currentTime = range.start;
        await a.play();
      }
      setState({ playingId: id, loadingId: null, progress: 0, error: null });
    } catch (e) {
      setState({ playingId: null, loadingId: null, progress: 0, error: e instanceof Error ? e.message : String(e) });
    }
  }, [state.playingId, state.loadingId, stop]);

  return <Ctx.Provider value={{ ...state, toggle, stop }}>{children}</Ctx.Provider>;
}

export function usePreview() {
  const c = useContext(Ctx);
  if (!c) throw new Error("PreviewProvider manquant");
  return c;
}
