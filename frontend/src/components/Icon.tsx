const PATHS: Record<string, string> = {
  play: "M8 5.5v13l11-6.5z",
  pause: "M7 5h4v14H7zM13 5h4v14h-4z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  upload: "M12 16V4m0 0L7 9m5-5l5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3",
  folder: "M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  chevronDown: "M6 9l6 6 6-6",
  chevronRight: "M9 6l6 6-6 6",
  arrowLeft: "M19 12H5m0 0l6-6m-6 6l6 6",
  alert: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  info: "M12 16v-4m0-4h.01M22 12a10 10 0 11-20 0 10 10 0 0120 0z",
  refresh: "M4 4v5h5M20 20v-5h-5M5.1 15a7 7 0 0011.8 2.3L20 15M4 9l3.1-2.3A7 7 0 0118.9 9",
  undo: "M9 14L4 9l5-5M4 9h11a5 5 0 010 10h-3",
  redo: "M15 14l5-5-5-5M20 9H9a5 5 0 000 10h3",
  download: "M12 4v12m0 0l-5-5m5 5l5-5M4 20h16",
  wave: "M3 12h2M7 8v8M11 5v14M15 8v8M19 10v4",
  shorter: "M4 12h16M8 8l-4 4 4 4M16 8l4 4-4 4",
  longer: "M20 12H4M16 8l4 4-4 4M8 8l-4 4 4 4",
  user: "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z",
  trash: "M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  server: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
};

export function Icon({ name, size = 18, className = "", strokeWidth = 2, label }: {
  name: keyof typeof PATHS | string; size?: number; className?: string; strokeWidth?: number; label?: string;
}) {
  const filled = name === "play" || name === "pause";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} role={label ? "img" : undefined}
      aria-label={label} aria-hidden={label ? undefined : true} fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name] || PATHS.info} />
    </svg>
  );
}
