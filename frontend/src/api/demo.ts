// Mode démo : tourne entièrement dans le navigateur (GitHub Pages, sans serveur local).
// Analyse réelle du fichier (durée, forme d'onde, segments de parole détectés par énergie),
// mais la traduction et la synthèse sont SIMULÉES : aucun doublage n'est produit.
import catalog from "../data/catalog.json";
import type {
  Api, AudioFileT, JobSnapshot, JobStep, Language, Project, SegmentT, SettingsT, Speaker, Voice,
} from "./types";
import { ApiError } from "./types";

type Cat = { languages: Record<string, { native_name: string; names: Record<string, string>; default_locale: string;
  variants: Record<string, { flag: string; label: string; syllables_per_sec: number }> }>; voices: Record<string, Voice[]> };
const CAT = catalog as unknown as Cat;

const DEMO_LINE: Record<string, string> = {
  fr: "Ceci est une traduction de démonstration.", en: "This is a demo translation.", zh: "这是演示翻译。",
  de: "Dies ist eine Demo-Übersetzung.", sv: "Detta är en demoöversättning.", es: "Esta es una traducción de demostración.",
  it: "Questa è una traduzione dimostrativa.", pl: "To jest tłumaczenie demonstracyjne.",
};

interface DemoFile extends AudioFileT { url: string; peaks: number[]; units: { start: number; end: number }[] }
interface DemoProject extends Omit<Project, "files"> { files: DemoFile[] }

const uid = () => Math.random().toString(36).slice(2, 14);

function detectSpeech(data: Float32Array, sr: number): { start: number; end: number }[] {
  const frame = Math.floor(sr * 0.03);
  const n = Math.floor(data.length / frame);
  const rms = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let j = i * frame; j < (i + 1) * frame; j++) s += data[j] * data[j];
    rms[i] = Math.sqrt(s / frame);
  }
  const sorted = Array.from(rms).sort((a, b) => a - b);
  const floor = sorted[Math.floor(n * 0.1)] || 0;
  const peak = sorted[Math.floor(n * 0.95)] || 0;
  const thr = floor + (peak - floor) * 0.25;
  const raw: { start: number; end: number }[] = [];
  let cur: number | null = null;
  for (let i = 0; i < n; i++) {
    if (rms[i] > thr && cur === null) cur = i;
    if ((rms[i] <= thr || i === n - 1) && cur !== null) {
      raw.push({ start: (cur * frame) / sr, end: ((i + 1) * frame) / sr });
      cur = null;
    }
  }
  const merged: { start: number; end: number }[] = [];
  for (const r of raw) {
    const last = merged[merged.length - 1];
    if (last && (r.start - last.end < 0.4 || last.end - last.start < 2) && r.end - last.start <= 12) last.end = r.end;
    else merged.push({ ...r });
  }
  return merged.filter((u) => u.end - u.start >= 0.5);
}

function peaksOf(data: Float32Array, bins = 1000): number[] {
  const out: number[] = [];
  const step = data.length / bins;
  let top = 0;
  for (let b = 0; b < bins; b++) {
    let m = 0;
    for (let i = Math.floor(b * step); i < Math.floor((b + 1) * step); i++) m = Math.max(m, Math.abs(data[i]));
    out.push(m);
    top = Math.max(top, m);
  }
  return out.map((v) => (top ? v / top : 0));
}

export function createDemoApi(): Api {
  const projects = new Map<string, DemoProject>();
  const jobs = new Map<string, JobSnapshot>();
  const listeners = new Map<string, Set<(s: JobSnapshot) => void>>();
  const speakers = new Map<string, Speaker[]>();
  const segments = new Map<string, SegmentT[]>();

  const strip = (p: DemoProject): Project => ({ ...p, files: p.files.map(({ url, peaks, units, ...f }) => f) });
  const get = (pid: string) => {
    const p = projects.get(pid);
    if (!p) throw new ApiError(404, "Projet introuvable");
    return p;
  };
  const allFiles = () => [...projects.values()].flatMap((p) => p.files);
  const fileById = (fid: string) => {
    const f = allFiles().find((x) => x.id === fid);
    if (!f) throw new ApiError(404, "Fichier introuvable");
    return f;
  };

  async function analyse(pid: string, file: File): Promise<DemoFile> {
    const base: DemoFile = {
      id: uid(), project_id: pid, name: file.name, duration_ms: 0, format: file.name.split(".").pop()?.toLowerCase() || "",
      sample_rate: 0, channels: 0, detected_lang: null, status: "ready", error: null, warnings: [],
      is_video: /\.(mp4|mov)$/i.test(file.name), snr_db: null, loudness_lufs: null,
      url: URL.createObjectURL(file), peaks: [], units: [],
    };
    if (!/\.(mp3|wav|m4a|aac|flac|ogg|mp4|mov)$/i.test(file.name)) {
      return { ...base, status: "invalid", error: "Format non pris en charge." };
    }
    try {
      const ctx = new AudioContext();
      const buf = await ctx.decodeAudioData(await file.arrayBuffer());
      ctx.close();
      if (buf.duration > 3 * 3600) return { ...base, status: "invalid", error: "Fichier trop long (maximum 3 h)." };
      const mono = buf.getChannelData(0);
      return { ...base, duration_ms: Math.round(buf.duration * 1000), sample_rate: buf.sampleRate,
        channels: buf.numberOfChannels, peaks: peaksOf(mono), units: detectSpeech(mono, buf.sampleRate) };
    } catch {
      return { ...base, status: "invalid", error: "Fichier illisible ou corrompu." };
    }
  }

  function emit(jid: string) {
    const s = jobs.get(jid)!;
    listeners.get(jid)?.forEach((cb) => cb(structuredClone(s)));
  }

  function simulate(p: DemoProject, kind: "prepare" | "run"): JobSnapshot {
    const prep = ["separate", "transcribe", "diarize"];
    const dub = ["translate", "synthesize", "assemble"];
    const files = p.files.filter((f) => f.status !== "invalid");
    const entries = kind === "prepare"
      ? files.map((f) => ({ file_id: f.id, name: f.name, locale: null, steps: prep.map(mk) }))
      : files.flatMap((f) => p.targets.map((loc, i) => ({
          file_id: f.id, name: f.name, locale: loc,
          steps: [...(i === 0 && f.status === "ready" ? prep : []), ...dub].map(mk) })));
    function mk(key: string): JobStep { return { key, status: "pending", detail: null, duration_s: null }; }
    const snap: JobSnapshot = { id: uid(), project_id: p.id, kind, status: "running", error: null, progress: 0,
      elapsed_s: 0, eta_s: null, files: entries, logs: ["Mode démo : traitement simulé."], transcript_preview: [], result: {} };
    jobs.set(snap.id, snap);
    const steps = entries.flatMap((e) => e.steps.map((s) => ({ e, s })));
    let i = 0;
    const t0 = Date.now();
    const tick = () => {
      const cur = jobs.get(snap.id)!;
      if (cur.status === "cancelled") return emit(snap.id);
      if (i >= steps.length) {
        cur.status = "done";
        cur.progress = 1;
        cur.result = { delta_ms: 0, review: 0, errors: 0 };
        files.forEach((f) => (f.status = kind === "run" ? "done" : "prepared"));
        if (kind === "run") p.status = "done";
        finish(p, kind);
        return emit(snap.id);
      }
      const { e, s } = steps[i];
      if (s.status === "pending") {
        s.status = "running";
        if (s.key === "transcribe") cur.transcript_preview.push(`[démo] ${fileById(e.file_id).units.length} segments de parole détectés`);
      } else {
        s.status = "done";
        s.duration_s = 0.6;
        if (s.key === "synthesize") s.detail = `${fileById(e.file_id).units.length}/${fileById(e.file_id).units.length}`;
        i++;
      }
      cur.progress = (i + (s.status === "running" ? 0.5 : 0)) / steps.length;
      cur.elapsed_s = (Date.now() - t0) / 1000;
      cur.eta_s = Math.max(0, Math.round(((steps.length - i) * 0.9)));
      emit(snap.id);
      setTimeout(tick, 450);
    };
    setTimeout(tick, 300);
    return structuredClone(snap);
  }

  function finish(p: DemoProject, kind: string) {
    for (const f of p.files.filter((x) => x.status !== "invalid")) {
      if (!speakers.has(f.id)) {
        const voices: Record<string, string> = {};
        p.targets.forEach((loc) => { const v = defaultVoice(loc); if (v) voices[loc] = v.id; });
        speakers.set(f.id, [{ id: uid(), audio_file_id: f.id, key: "S1", label: "Locuteur 1", gender: "unknown",
          speech_ms: Math.round(f.units.reduce((a, u) => a + (u.end - u.start), 0) * 1000), voices,
          first_start_ms: f.units[0] ? Math.round(f.units[0].start * 1000) : null, first_text: "[démo] transcription simulée" }]);
      }
      if (kind !== "run") continue;
      for (const loc of p.targets) {
        segments.set(`${f.id}:${loc}`, f.units.map((u, index) => {
          const text = DEMO_LINE[loc.split("-")[0]] || DEMO_LINE.en;
          return { id: uid(), audio_file_id: f.id, locale: loc, index, speaker_key: "S1",
            start_ms: Math.round(u.start * 1000), end_ms: Math.round(u.end * 1000),
            source_text: `[démo] segment ${index + 1} — transcription simulée`, target_text: text, target_text_edited: null,
            effective_text: text, voice_override: null, voice_id: defaultVoice(loc)?.id || null,
            tts_ms: (u.end - u.start) * 1000, final_ms: (u.end - u.start) * 1000, stretch_ratio: 1, retranslations: 0,
            status: "ok", error: null, can_undo: false, can_redo: false } satisfies SegmentT;
        }));
      }
    }
  }

  function defaultVoice(locale: string): Voice | undefined {
    const vs = CAT.voices[locale] || [];
    return vs.find((v) => v.default) || vs[0];
  }

  const notAvailable = () => { throw new ApiError(501, "Disponible uniquement avec le serveur local Doublr (voir README)."); };

  return {
    mode: "demo",
    health: async () => true,
    async languages(): Promise<Language[]> {
      return Object.entries(CAT.languages).map(([code, l]) => ({
        code, native_name: l.native_name, names: l.names, default_locale: l.default_locale,
        variants: Object.entries(l.variants).filter(([loc]) => (CAT.voices[loc] || []).length)
          .map(([locale, v]) => ({ locale, ...v })),
      })).filter((l) => l.variants.length);
    },
    voices: async (locale) => {
      const vs = CAT.voices[locale];
      if (!vs?.length) throw new ApiError(422, `Aucune voix native validée pour ${locale}`);
      return vs;
    },
    allVoices: async () => CAT.voices,
    voiceSample: async (voice) => ({ kind: "speech", lang: voice.locale, text: DEMO_LINE[voice.locale.split("-")[0]] }),
    toggleVoice: async () => notAvailable(),
    listProjects: async () => [...projects.values()].reverse().map(strip),
    async createProject(files) {
      const p: DemoProject = { id: uid(), name: files[0]?.name.replace(/\.[^.]+$/, "") || "Projet", created_at: new Date().toISOString(),
        source_lang: null, targets: [], settings: {}, status: "draft", files: [] };
      p.files = await Promise.all(files.map((f) => analyse(p.id, f)));
      projects.set(p.id, p);
      return strip(p);
    },
    async addFiles(pid, files) {
      const p = get(pid);
      p.files.push(...(await Promise.all(files.map((f) => analyse(pid, f)))));
      return strip(p);
    },
    getProject: async (pid) => strip(get(pid)),
    async patchProject(pid, body) {
      const p = get(pid);
      if (body.targets) for (const t of body.targets) if (!CAT.voices[t]?.length) throw new ApiError(422, `Aucune voix native validée pour ${t}`);
      Object.assign(p, { ...body, settings: { ...p.settings, ...(body.settings || {}) } });
      if (body.source_lang) p.settings.source_locked = true;
      return strip(p);
    },
    async removeFile(pid, fid) { const p = get(pid); p.files = p.files.filter((f) => f.id !== fid); return strip(p); },
    async deleteProject(pid) { projects.delete(pid); },
    async estimate(pid) {
      const p = get(pid);
      const secs = p.files.filter((f) => f.status !== "invalid").reduce((a, f) => a + f.duration_ms / 1000, 0);
      const n = Math.max(1, p.targets.length);
      return { total_seconds: secs, processing_seconds: Math.round(secs * 1.5 * (1 + 0.25 * (n - 1))),
        cost_usd: Math.round((secs / 6) * n * 1.35 * 0.0115 * 100 + secs * 14 * n * 1.35 * 16e-6 * 100) / 100 };
    },
    prepare: async (pid) => simulate(get(pid), "prepare"),
    run: async (pid) => {
      const p = get(pid);
      if (!p.targets.length) throw new ApiError(422, "Choisissez au moins une langue cible.");
      p.status = "processing";
      return simulate(p, "run");
    },
    latestJob: async (pid) => [...jobs.values()].reverse().find((j) => j.project_id === pid) || null,
    async cancelJob(jid) { const j = jobs.get(jid)!; j.status = "cancelled"; emit(jid); return j; },
    watchJob(jid, cb) {
      if (!listeners.has(jid)) listeners.set(jid, new Set());
      listeners.get(jid)!.add(cb);
      const s = jobs.get(jid);
      if (s) cb(structuredClone(s));
      return () => listeners.get(jid)?.delete(cb);
    },
    speakers: async (fid) => speakers.get(fid) || [],
    async patchSpeaker(sid, body) {
      for (const list of speakers.values()) {
        const s = list.find((x) => x.id === sid);
        if (s) {
          if (body.label) s.label = body.label;
          if (body.locale && body.voice_id) s.voices = { ...s.voices, [body.locale]: body.voice_id };
          return s;
        }
      }
      throw new ApiError(404, "Locuteur introuvable");
    },
    mergeSpeakers: async (fid) => speakers.get(fid) || [],
    speakerPreview: async (_sid, locale) => ({ kind: "speech", lang: locale, text: DEMO_LINE[locale.split("-")[0]] }),
    segments: async (fid, locale) => segments.get(`${fid}:${locale}`) || [],
    async patchSegment(sid, body) {
      for (const list of segments.values()) {
        const s = list.find((x) => x.id === sid);
        if (s) {
          if (body.target_text !== undefined) { s.target_text_edited = body.target_text; s.effective_text = body.target_text; }
          if (body.action === "reset") { s.target_text_edited = null; s.effective_text = s.target_text; }
          return { ...s };
        }
      }
      throw new ApiError(404, "Segment introuvable");
    },
    originalUrl: (fid) => fileById(fid).url,
    trackUrl: (fid) => fileById(fid).url,
    peaks: async (fid) => fileById(fid).peaks,
    async report(fid, locale) {
      const f = fileById(fid);
      return { file: f.name, locale, input_duration_ms: f.duration_ms, output_duration_ms: f.duration_ms, duration_delta_ms: 0,
        duration_ok: true, processing_seconds: 0, estimated_cost_usd: 0, counts: { ok: f.units.length }, warnings: ["demo"] };
    },
    exportProject: async () => notAvailable(),
    exportFileUrl: () => "#",
    async getSettings(): Promise<SettingsT> {
      return { keys: { ANTHROPIC_API_KEY: false, AZURE_SPEECH_KEY: false, ELEVENLABS_API_KEY: false, HF_TOKEN: false },
        tts_provider: "azure", whisper_model: "large-v3", device: "auto", azure_region: "westeurope", claude_model: "claude-opus-5",
        output_dir: "—", data_dir: "—", cache_bytes: 0, require_validated_voices: false,
        capabilities: { whisper: false, demucs: false, pyannote: false } };
    },
    putSettings: async () => notAvailable(),
    testService: async () => ({ ok: false, error: "Mode démo" }),
    clearCache: async () => ({ freed_bytes: 0 }),
    version: async () => ({ sha: null, branch: "main", installed_at: null, can_update: false }),
    startUpdate: async () => notAvailable(),
  };
}
