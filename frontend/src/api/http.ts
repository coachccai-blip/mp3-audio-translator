import type { Api, AudioSource, JobSnapshot, Project } from "./types";
import { ApiError } from "./types";

// VITE_SAME_ORIGIN=1 : interface servie par le serveur local lui-même (installateur Windows).
export const DEFAULT_API = import.meta.env.VITE_SAME_ORIGIN === "1"
  ? window.location.origin
  : import.meta.env.VITE_API_URL || "http://localhost:8000";

export function storedApiBase(): string {
  try {
    return localStorage.getItem("doublr.api") || DEFAULT_API;
  } catch {
    return DEFAULT_API;
  }
}

export function createHttpApi(base: string): Api {
  const url = (p: string) => `${base.replace(/\/$/, "")}${p}`;

  async function req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url(path), init);
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        detail = (await res.json()).detail;
      } catch { /* corps non JSON */ }
      throw new ApiError(res.status, detail);
    }
    return res.status === 204 ? (undefined as T) : res.json();
  }
  const json = (method: string, body: unknown): RequestInit => ({
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const upload = (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return { method: "POST", body: fd };
  };
  async function blobSource(path: string, init?: RequestInit): Promise<AudioSource> {
    const res = await fetch(url(path), init);
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try { detail = (await res.json()).detail; } catch { /* */ }
      throw new ApiError(res.status, detail);
    }
    return { kind: "url", url: URL.createObjectURL(await res.blob()) };
  }

  return {
    mode: "local",
    async health() {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 2500);
        const res = await fetch(url("/api/health"), { signal: ctrl.signal });
        clearTimeout(t);
        return res.ok;
      } catch {
        return false;
      }
    },
    languages: () => req("/api/languages"),
    voices: (locale) => req(`/api/voices?locale=${encodeURIComponent(locale)}`),
    allVoices: () => req("/api/voices"),
    voiceSample: (voice) => blobSource(`/api/voices/${encodeURIComponent(voice.id)}/sample`),
    toggleVoice: (id, disabled) => req(`/api/voices/${encodeURIComponent(id)}`, json("PATCH", { disabled })),
    listProjects: () => req("/api/projects"),
    createProject: (files) => req<Project>("/api/projects", upload(files)),
    addFiles: (pid, files) => req(`/api/projects/${pid}/files`, upload(files)),
    getProject: (pid) => req(`/api/projects/${pid}`),
    patchProject: (pid, body) => req(`/api/projects/${pid}`, json("PATCH", body)),
    removeFile: (pid, fid) => req(`/api/projects/${pid}/files/${fid}`, { method: "DELETE" }),
    deleteProject: async (pid) => { await req(`/api/projects/${pid}`, { method: "DELETE" }); },
    estimate: (pid) => req(`/api/projects/${pid}/estimate`),
    prepare: (pid) => req(`/api/projects/${pid}/prepare`, { method: "POST" }),
    run: (pid) => req(`/api/projects/${pid}/run`, { method: "POST" }),
    latestJob: (pid) => req(`/api/projects/${pid}/job`),
    cancelJob: (jid) => req(`/api/jobs/${jid}/cancel`, { method: "POST" }),
    watchJob(jid, cb) {
      let closed = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let last: JobSnapshot | null = null;
      let failures = 0;
      const finished = (s: JobSnapshot | null) => !!s && ["done", "error", "cancelled"].includes(s.status);
      const emit = (s: JobSnapshot) => { last = s; cb(s); };
      const poll = async () => {
        if (closed) return;
        try {
          const s = await req<JobSnapshot>(`/api/jobs/${jid}`);
          failures = 0;
          emit(s);
          if (finished(s)) return;
        } catch (e) {
          // Serveur arrêté ou traitement perdu : on le dit au lieu d'afficher « En cours » indéfiniment.
          failures += 1;
          const lost = e instanceof ApiError && e.status === 404;
          if (last && (lost || failures === 8)) emit({ ...last, status: "error", eta_s: null, error: lost ? "lost" : "offline" });
          if (lost) return;
        }
        timer = setTimeout(poll, failures ? 2000 : 800);
      };
      let ws: WebSocket | null = null;
      try {
        ws = new WebSocket(url(`/api/ws/jobs/${jid}`).replace(/^http/, "ws"));
        ws.onmessage = (e) => { const s = JSON.parse(e.data); if (s && s.id) emit(s); };
        // Fermeture (serveur arrêté, réseau) avant la fin : on bascule sur l'interrogation régulière.
        ws.onclose = () => { ws = null; if (!closed && !finished(last)) poll(); };
      } catch {
        poll();
      }
      return () => { closed = true; ws?.close(); if (timer) clearTimeout(timer); };
    },
    speakers: (fid) => req(`/api/files/${fid}/speakers`),
    patchSpeaker: (sid, body) => req(`/api/speakers/${sid}`, json("PATCH", body)),
    mergeSpeakers: (fid, source_id, target_id) => req(`/api/files/${fid}/speakers/merge`, json("POST", { source_id, target_id })),
    speakerPreview: (sid, locale, voice_id) =>
      blobSource(`/api/speakers/${sid}/preview?locale=${encodeURIComponent(locale)}&voice_id=${encodeURIComponent(voice_id)}`, { method: "POST" }),
    segments: (fid, locale) => req(`/api/files/${fid}/segments?locale=${encodeURIComponent(locale)}`),
    patchSegment: (sid, body) => req(`/api/segments/${sid}`, json("PATCH", body)),
    originalUrl: (fid) => url(`/api/files/${fid}/audio/original`),
    trackUrl: (fid, track, locale) => url(`/api/files/${fid}/audio/${track}?locale=${encodeURIComponent(locale)}`),
    peaks: (fid, locale) => req(`/api/files/${fid}/peaks${locale ? `?locale=${encodeURIComponent(locale)}` : ""}`),
    report: (fid, locale) => req(`/api/files/${fid}/report?locale=${encodeURIComponent(locale)}`),
    exportProject: (pid, body) => req(`/api/projects/${pid}/export`, json("POST", body)),
    exportFileUrl: (eid, name) => url(`/api/exports/${eid}/files/${encodeURIComponent(name)}`),
    getSettings: () => req("/api/settings"),
    putSettings: (body) => req("/api/settings", json("PUT", body)),
    testService: (service) => req(`/api/settings/test/${service}`, { method: "POST" }),
    clearCache: () => req("/api/cache", { method: "DELETE" }),
  };
}
