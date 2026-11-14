import { useEffect, useState } from "react";

export const AGENT_COLORS = {
  showrunner: "var(--c-showrunner)",
  research: "var(--c-research)",
  script: "var(--c-script)",
  qa: "var(--c-qa)",
  studio: "var(--c-studio)",
  packaging: "var(--c-packaging)",
  publisher: "var(--c-publisher)",
  you: "var(--c-you)",
};

export const agentColor = (name) => AGENT_COLORS[name] || "var(--muted)";

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function ago(ts, now = Date.now()) {
  if (!ts) return "—";
  const s = Math.max(0, Math.round((now - new Date(ts).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function duration(ts, now = Date.now()) {
  if (!ts) return "—";
  const s = Math.max(0, Math.round((now - new Date(ts).getTime()) / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export const money = (n) => `$${(n || 0).toFixed(2)}`;

export const clock = (ts) =>
  new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export const fmtLabel = (f) => (f === "short" ? "Short" : "Long-form");
