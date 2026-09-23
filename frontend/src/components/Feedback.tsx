import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

type Tone = "info" | "success" | "warning" | "danger";
interface ToastItem { id: number; tone: Tone; text: string; action?: { label: string; run: () => void } }
const ToastCtx = createContext<(t: Omit<ToastItem, "id">) => void>(() => {});

const toneStyle: Record<Tone, string> = {
  info: "border-border bg-surface text-text",
  success: "border-success/40 bg-surface text-text",
  warning: "border-accent/60 bg-surface text-text",
  danger: "border-danger/60 bg-surface text-text",
};
const toneIcon: Record<Tone, string> = { info: "info", success: "check", warning: "alert", danger: "alert" };
const toneColor: Record<Tone, string> = { info: "text-muted", success: "text-success", warning: "text-accent", danger: "text-danger" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((t: Omit<ToastItem, "id">) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 6000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`pointer-events-auto fade-in flex items-start gap-3 rounded-md border p-3 text-sm shadow-md ${toneStyle[t.tone]}`}>
            <Icon name={toneIcon[t.tone]} className={`mt-0.5 ${toneColor[t.tone]}`} />
            <span className="flex-1">{t.text}</span>
            {t.action && <button className="font-medium text-primary underline" onClick={t.action.run}>{t.action.label}</button>}
            <button aria-label="×" className="text-muted hover:text-text" onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function Banner({ tone = "info", title, children, action }: {
  tone?: Tone; title?: string; children: ReactNode; action?: ReactNode;
}) {
  const bg = { info: "bg-surface-2", success: "bg-surface-2", warning: "bg-accent/10 border-accent/50", danger: "bg-danger/10 border-danger/50" }[tone];
  return (
    <div className={`flex flex-wrap items-start gap-3 rounded-md border border-border px-4 py-3 text-sm ${bg}`} role={tone === "danger" ? "alert" : "note"}>
      <Icon name={toneIcon[tone]} className={`mt-0.5 shrink-0 ${toneColor[tone]}`} />
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium">{title}</div>}
        <div className="text-muted">{children}</div>
      </div>
      {action}
    </div>
  );
}
