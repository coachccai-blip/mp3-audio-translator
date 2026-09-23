import { useRef, useState, type DragEvent } from "react";
import { useI18n } from "../i18n";
import { Icon } from "./Icon";

const ACCEPT = ".mp3,.wav,.m4a,.aac,.flac,.ogg,.mp4,.mov,audio/*,video/mp4,video/quicktime";

async function filesFromDrop(e: DragEvent): Promise<File[]> {
  const items = Array.from(e.dataTransfer.items || []);
  const entries = items.map((i) => i.webkitGetAsEntry?.()).filter(Boolean) as FileSystemEntry[];
  if (!entries.length) return Array.from(e.dataTransfer.files);
  const out: File[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      out.push(await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej)));
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const children = await new Promise<FileSystemEntry[]>((res) => reader.readEntries(res));
      await Promise.all(children.map(walk));
    }
  };
  await Promise.all(entries.map(walk));
  return out;
}

export function DropZone({ onFiles, compact = false }: { onFiles: (files: File[]) => void; compact?: boolean }) {
  const { t } = useI18n();
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={async (e) => { e.preventDefault(); setOver(false); onFiles(await filesFromDrop(e)); }}
      className={`relative flex flex-col items-center justify-center rounded-lg text-center transition-colors ${
        compact ? "gap-2 px-6 py-6" : "gap-4 px-6 py-16 sm:py-24"} ${
        over ? "dropzone-active bg-primary/5" : "border-2 border-dashed border-border bg-surface"}`}
    >
      <div className={`flex items-center justify-center rounded-full bg-surface-2 text-primary ${compact ? "h-10 w-10" : "h-16 w-16"}`}>
        <Icon name="upload" size={compact ? 20 : 28} />
      </div>
      <p className={`font-semibold ${compact ? "text-md" : "text-xl"}`}>{over ? t("import.drop") : t("import.title")}</p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <button type="button" className="btn-primary" onClick={() => input.current?.click()}>{t("import.browse")}</button>
        <button type="button" className="text-sm text-primary underline-offset-2 hover:underline" onClick={() => folder.current?.click()}>
          {t("import.folder")}
        </button>
      </div>
      <p className="text-xs text-muted">{t("import.formats")}</p>
      <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" tabIndex={-1}
        onChange={(e) => { onFiles(Array.from(e.target.files || [])); e.target.value = ""; }} />
      <input ref={folder} type="file" multiple className="sr-only" tabIndex={-1}
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => { onFiles(Array.from(e.target.files || []).filter((f) => /\.(mp3|wav|m4a|aac|flac|ogg|mp4|mov)$/i.test(f.name))); e.target.value = ""; }} />
    </div>
  );
}
