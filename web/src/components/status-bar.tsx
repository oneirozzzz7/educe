"use client";

import { Terminal, Circle, Loader2, Hammer, Coffee } from "lucide-react";
import type { AppState } from "@/lib/state";

interface StatusBarProps {
  phase: AppState["phase"];
  model: string;
  connected: boolean;
  elapsed: number;
  lastAction?: string;
  onToggleDebug: () => void;
}

function PhaseIndicator({ phase }: { phase: AppState["phase"] }) {
  switch (phase) {
    case "thinking":
      return (
        <div className="flex items-center gap-1.5">
          <Loader2 size={13} className="animate-spin" style={{ color: "var(--accent)" }} />
          <span style={{ color: "var(--accent)" }}>Thinking</span>
        </div>
      );
    case "building":
      return (
        <div className="flex items-center gap-1.5">
          <Hammer size={13} style={{ color: "var(--pass)" }} />
          <span style={{ color: "var(--pass)" }}>Building</span>
        </div>
      );
    default:
      return (
        <div className="flex items-center gap-1.5">
          <Coffee size={13} style={{ color: "var(--text-2)" }} />
          <span style={{ color: "var(--text-2)" }}>Idle</span>
        </div>
      );
  }
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

/**
 * StatusBar - Horizontal bar showing phase, elapsed time, model, connection, debug toggle
 */
export function StatusBar({ phase, model, connected, elapsed, lastAction, onToggleDebug }: StatusBarProps) {
  return (
    <div
      className="flex items-center gap-3 px-4 select-none shrink-0"
      style={{
        height: 36,
        background: "var(--surface-1)",
        borderBottom: "1px solid var(--border-0)",
        fontSize: 12,
        fontFamily: "'Geist Mono', monospace",
      }}
    >
      {/* Phase */}
      <PhaseIndicator phase={phase} />

      {/* Elapsed (when not idle) */}
      {phase !== "idle" && elapsed > 0 && (
        <span style={{ color: "var(--text-2)" }}>{formatElapsed(elapsed)}</span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Last action hint */}
      {lastAction && (
        <span className="truncate max-w-[180px]" style={{ color: "var(--text-3)" }}>
          {lastAction}
        </span>
      )}

      {/* Model badge */}
      {model && (
        <span
          className="px-2 py-0.5 rounded"
          style={{ background: "var(--accent-dim)", color: "var(--accent)", fontSize: 11 }}
        >
          {model}
        </span>
      )}

      {/* Connection dot */}
      <Circle
        size={8}
        fill={connected ? "var(--pass)" : "var(--fail)"}
        stroke="none"
      />

      {/* Debug toggle */}
      <button
        onClick={onToggleDebug}
        className="flex items-center justify-center rounded hover:opacity-80 transition-opacity"
        style={{
          width: 28,
          height: 28,
          background: "var(--surface-2)",
          border: "1px solid var(--border-0)",
        }}
        title="Toggle debug panel"
      >
        <Terminal size={14} style={{ color: "var(--text-2)" }} />
      </button>
    </div>
  );
}
