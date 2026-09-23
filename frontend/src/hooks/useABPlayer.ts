import { useCallback, useEffect, useRef, useState } from "react";

// Lecteur A/B : bascule instantanée original/doublé sans perdre la position (brief §8.3, écran 5).
export function useABPlayer(originalUrl: string | null, dubbedUrl: string | null) {
  const a = useRef<HTMLAudioElement>(new Audio());
  const b = useRef<HTMLAudioElement>(new Audio());
  const [mode, setMode] = useState<"original" | "dubbed">("dubbed");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const active = useCallback(() => (mode === "original" ? a.current : b.current), [mode]);

  useEffect(() => { a.current.preload = "auto"; if (originalUrl) a.current.src = originalUrl; }, [originalUrl]);
  useEffect(() => { b.current.preload = "auto"; if (dubbedUrl) b.current.src = dubbedUrl; }, [dubbedUrl]);

  useEffect(() => {
    const el = active();
    let raf = 0;
    const loop = () => { setTime(el.currentTime); raf = requestAnimationFrame(loop); };
    const onMeta = () => setDuration(el.duration || 0);
    const onEnd = () => setPlaying(false);
    el.addEventListener("loadedmetadata", onMeta);
    el.addEventListener("ended", onEnd);
    if (el.duration) setDuration(el.duration);
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); el.removeEventListener("loadedmetadata", onMeta); el.removeEventListener("ended", onEnd); };
  }, [active]);

  useEffect(() => () => { a.current.pause(); b.current.pause(); }, []);

  const playPause = useCallback(() => {
    const el = active();
    if (el.paused) { el.play().then(() => setPlaying(true)).catch(() => setPlaying(false)); }
    else { el.pause(); setPlaying(false); }
  }, [active]);

  const toggleMode = useCallback(() => {
    const from = active();
    const to = mode === "original" ? b.current : a.current;
    const wasPlaying = !from.paused;
    from.pause();
    to.currentTime = from.currentTime;
    setMode((m) => (m === "original" ? "dubbed" : "original"));
    if (wasPlaying) to.play().catch(() => setPlaying(false));
  }, [active, mode]);

  const seek = useCallback((sec: number) => {
    a.current.currentTime = sec;
    b.current.currentTime = sec;
    setTime(sec);
  }, []);

  const reloadDubbed = useCallback((url: string) => {
    const t = b.current.currentTime;
    const wasPlaying = !b.current.paused;
    b.current.src = url;
    b.current.currentTime = t;
    if (wasPlaying) b.current.play().catch(() => {});
  }, []);

  return { mode, setMode, playing, time, duration, playPause, toggleMode, seek, reloadDubbed };
}
