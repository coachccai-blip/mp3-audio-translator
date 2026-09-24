export type Locale = string;

export interface Variant { locale: Locale; flag: string; label: string; syllables_per_sec: number }
export interface Language {
  code: string; native_name: string; names: Record<string, string>; default_locale: Locale; variants: Variant[];
}
export interface Voice {
  id: string; provider: string; locale: Locale; display_name: string; gender: string; age_range: string;
  styles: string[]; validated: boolean; status: string; default: boolean; disabled: boolean;
  quality?: "hd" | "standard"; free?: boolean; note?: string | null;
}
export interface AudioFileT {
  id: string; project_id: string; name: string; duration_ms: number; format: string; sample_rate: number;
  channels: number; detected_lang: string | null; status: "ready" | "invalid" | "prepared" | "done" | "error";
  error: string | null; warnings: string[]; is_video: boolean; snr_db: number | null; loudness_lufs: number | null;
}
export interface ProjectSettings {
  register?: "auto" | "formal" | "conversational" | "advertising" | "educational";
  glossary?: { source: string; target: string }[];
  quality?: "fast" | "precise";
  keep_background?: boolean;
  stretch_tolerance?: number;
  source_locked?: boolean;
}
export interface Project {
  id: string; name: string; created_at: string; source_lang: string | null; targets: Locale[];
  settings: ProjectSettings; status: "draft" | "prepared" | "processing" | "done" | "error"; files: AudioFileT[];
}
export type StepStatus = "pending" | "running" | "done" | "error" | "skipped";
export interface JobStep { key: string; status: StepStatus; detail: string | null; duration_s: number | null }
export interface JobFile { file_id: string; name: string; locale: Locale | null; steps: JobStep[] }
export interface JobSnapshot {
  id: string; project_id: string; kind: string; status: "queued" | "running" | "done" | "error" | "cancelled";
  error: string | null; progress: number; elapsed_s: number; eta_s: number | null; files: JobFile[];
  logs: string[]; transcript_preview: string[]; result: { delta_ms?: number; review?: number; errors?: number };
}
export interface Speaker {
  id: string; audio_file_id: string; key: string; label: string; gender: string; speech_ms: number;
  voices: Record<Locale, string>; first_start_ms: number | null; first_text: string | null;
}
export type SegmentStatus = "pending" | "ok" | "adjusted" | "review" | "error";
export interface SegmentT {
  id: string; audio_file_id: string; locale: Locale; index: number; speaker_key: string; start_ms: number; end_ms: number;
  source_text: string; target_text: string; target_text_edited: string | null; effective_text: string;
  voice_override: string | null; voice_id: string | null; tts_ms: number | null; final_ms: number | null;
  stretch_ratio: number | null; retranslations: number; status: SegmentStatus; error: string | null;
  can_undo: boolean; can_redo: boolean;
}
export interface Report {
  file: string; locale: Locale; input_duration_ms: number; output_duration_ms: number; duration_delta_ms: number;
  duration_ok: boolean; processing_seconds: number; estimated_cost_usd: number;
  counts: Record<string, number>; warnings: string[];
}
export interface Estimate { total_seconds: number; processing_seconds: number; cost_usd: number }
export interface SettingsT {
  keys: Record<string, boolean>; tts_provider: string; whisper_model: string; device: string; azure_region: string;
  claude_model: string; output_dir: string; data_dir: string; cache_bytes: number; require_validated_voices: boolean;
  capabilities: { whisper: boolean; demucs: boolean; pyannote: boolean; kokoro?: boolean; piper?: boolean };
  translator?: "auto" | "local" | "claude"; translator_engine?: "local" | "claude"; local_llm?: string;
  ollama?: { running: boolean; model: string; model_ready: boolean }; missing?: string[];
}
export interface ExportBody {
  format: string; voice_only: boolean; background_only: boolean; subtitles: boolean; report: boolean;
  video: boolean; template: string; destination?: string | null; zip: boolean;
}
export interface ExportResult {
  id: string; directory: string; files: { name: string; path: string }[];
  summary: { file: string; locale: Locale; path: string; delta_ms: number }[];
}
export type AudioSource = { kind: "url"; url: string } | { kind: "speech"; text: string; lang: string };

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message || `HTTP ${status}`);
  }
}

export interface Api {
  mode: "local" | "demo";
  health(): Promise<boolean>;
  languages(): Promise<Language[]>;
  voices(locale: Locale): Promise<Voice[]>;
  allVoices(): Promise<Record<Locale, Voice[]>>;
  voiceSample(voice: Voice): Promise<AudioSource>;
  toggleVoice(id: string, disabled: boolean): Promise<Voice>;
  listProjects(): Promise<Project[]>;
  createProject(files: File[]): Promise<Project>;
  addFiles(pid: string, files: File[]): Promise<Project>;
  getProject(pid: string): Promise<Project>;
  patchProject(pid: string, body: Partial<Pick<Project, "name" | "source_lang" | "targets" | "settings">>): Promise<Project>;
  removeFile(pid: string, fid: string): Promise<Project>;
  deleteProject(pid: string): Promise<void>;
  estimate(pid: string): Promise<Estimate>;
  prepare(pid: string): Promise<JobSnapshot>;
  run(pid: string): Promise<JobSnapshot>;
  latestJob(pid: string): Promise<JobSnapshot | null>;
  cancelJob(jid: string): Promise<JobSnapshot>;
  watchJob(jid: string, cb: (s: JobSnapshot) => void): () => void;
  speakers(fid: string): Promise<Speaker[]>;
  patchSpeaker(sid: string, body: { label?: string; locale?: string; voice_id?: string; regenerate?: boolean }): Promise<Speaker>;
  mergeSpeakers(fid: string, source_id: string, target_id: string): Promise<Speaker[]>;
  speakerPreview(sid: string, locale: Locale, voice_id: string): Promise<AudioSource>;
  segments(fid: string, locale: Locale): Promise<SegmentT[]>;
  patchSegment(sid: string, body: { target_text?: string; voice_id?: string; action?: string }): Promise<SegmentT>;
  originalUrl(fid: string): string;
  trackUrl(fid: string, track: "mix" | "voice" | "background", locale: Locale): string;
  peaks(fid: string, locale?: Locale): Promise<number[]>;
  report(fid: string, locale: Locale): Promise<Report>;
  exportProject(pid: string, body: ExportBody): Promise<ExportResult>;
  exportFileUrl(eid: string, name: string): string;
  getSettings(): Promise<SettingsT>;
  putSettings(body: { keys?: Record<string, string>; values?: Record<string, string> }): Promise<SettingsT>;
  testService(service: string): Promise<{ ok: boolean; error?: string }>;
  clearCache(): Promise<{ freed_bytes: number }>;
}
