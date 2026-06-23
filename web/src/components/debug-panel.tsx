"use client";

import { useEffect, useRef, useState } from "react";
import { X, ChevronDown, ChevronRight, Filter } from "lucide-react";
import { cn } from "@/lib/utils";

interface DebugPanelProps {
  open: boolean;
  events: any[];
  onClose: () => void;
}

type FilterType = "all" | "action" | "error" | "tool" | "user";

const FILTER_OPTIONS: { value: FilterType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "action", label: "Actions" },
  { value: "error", label: "Errors" },
  { value: "tool", label: "Tools" },
  { value: "user", label: "User" },
];

function matchesFilter(event: any, filter: FilterType): boolean {
  if (filter === "all") return true;
  if (filter === "error") return event.type === "error" || event.type === "action_error";
  if (filter === "action") return event.type?.startsWith("action") || event.type === "tool_start" || event.type === "tool_end";
  if (filter === "tool") return event.type?.startsWith("tool") || event.type === "action_detail";
  if (filter === "user") return event.type === "user_input" || event.type === "user_confirm";
  return true;
}

function formatTimestamp(ts: number): string {
  if (!ts) return "--:--:--";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3 } as any);
}

function summarizeEvent(event: any): string {
  if (event.content) return event.content.slice(0, 80);
  if (event.message) return event.message.slice(0, 80);
  if (event.name) return event.name;
  if (event.result) return typeof event.result === "string" ? event.result.slice(0, 80) : JSON.stringify(event.result).slice(0, 80);
  const { type, ts, ...rest } = event;
  const s = JSON.stringify(rest);
  return s.length > 80 ? s.slice(0, 80) + "..." : s;
}

function EventRow({ event, index }: { event: any; index: number }) {
  const [expanded, setExpanded] = useState(false);

  const typeColor =
    event.type === "error" ? "var(--fail)" :
    event.type?.startsWith("tool") ? "var(--accent)" :
    event.type === "user_input" ? "var(--pass)" :
    "var(--text-2)";

  return (
    <div style={{ borderBottom: "1px solid var(--border-0)" }}>
      <div
        className="flex items-center gap-2 px-3 py-1 cursor-pointer hover:opacity-80"
        onClick={() => setExpanded(!expanded)}
        style={{ minHeight: 28 }}
      >
        {expanded
          ? <ChevronDown size={10} style={{ color: "var(--text-3)" }} />
          : <ChevronRight size={10} style={{ color: "var(--text-3)" }} />
        }
        <span style={{ color: "var(--text-3)", fontSize: 10, width: 80, flexShrink: 0 }}>
          {formatTimestamp(event.ts)}
        </span>
        <span
          className="px-1.5 py-0.5 rounded"
          style={{
            fontSize: 10,
            color: typeColor,
            background: `color-mix(in srgb, ${typeColor} 12%, transparent)`,
            fontWeight: 500,
            width: 90,
            flexShrink: 0,
            textAlign: "center",
          }}
        >
          {event.type || "unknown"}
        </span>
        <span
          className="flex-1 truncate"
          style={{ fontSize: 11, color: "var(--text-2)" }}
        >
          {summarizeEvent(event)}
        </span>
      </div>

      {expanded && (
        <pre
          className="px-6 py-2 overflow-x-auto"
          style={{
            fontSize: 11,
            lineHeight: 1.5,
            color: "var(--text-1)",
            background: "var(--surface-2)",
            margin: 0,
            maxHeight: 200,
            overflow: "auto",
          }}
        >
          {JSON.stringify(event, null, 2)}
        </pre>
      )}
    </div>
  );
}

/**
 * DebugPanel - Collapsible bottom panel for event inspection.
 * Monospace, JSON-like display. Auto-scrolls with pause on manual scroll.
 */
export function DebugPanel({ open, events, onClose }: DebugPanelProps) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filtered = events.filter(e => matchesFilter(e, filter));

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered.length, autoScroll]);

  // Detect manual scroll (pause auto-scroll)
  function handleScroll() {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 40;
    setAutoScroll(atBottom);
  }

  if (!open) return null;

  return (
    <div className="flex flex-col h-full" style={{ fontFamily: "'Geist Mono', monospace" }}>
      {/* Header */}
      <div
        className="flex items-center gap-3 px-3 shrink-0 select-none"
        style={{
          height: 34,
          borderBottom: "1px solid var(--border-0)",
          background: "var(--surface-1)",
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-0)" }}>Debug</span>
        <span style={{ fontSize: 10, color: "var(--text-3)" }}>({filtered.length})</span>

        {/* Filter dropdown */}
        <div className="flex items-center gap-1 ml-2">
          <Filter size={11} style={{ color: "var(--text-3)" }} />
          <select
            value={filter}
            onChange={e => setFilter(e.target.value as FilterType)}
            className="bg-transparent border-none outline-none cursor-pointer"
            style={{ fontSize: 11, color: "var(--text-2)" }}
          >
            {FILTER_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value} style={{ background: "var(--surface-2)" }}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex-1" />

        {/* Auto-scroll indicator */}
        {!autoScroll && (
          <button
            onClick={() => setAutoScroll(true)}
            className="text-[10px] px-2 py-0.5 rounded"
            style={{ background: "var(--accent-dim)", color: "var(--accent)" }}
          >
            Resume scroll
          </button>
        )}

        {/* Close */}
        <button
          onClick={onClose}
          className="flex items-center justify-center rounded hover:opacity-70 transition-opacity"
          style={{ width: 24, height: 24 }}
        >
          <X size={14} style={{ color: "var(--text-2)" }} />
        </button>
      </div>

      {/* Event list */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
        onScroll={handleScroll}
        style={{ background: "var(--bg)" }}
      >
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full" style={{ color: "var(--text-3)", fontSize: 12 }}>
            No events
          </div>
        ) : (
          filtered.map((event, i) => <EventRow key={i} event={event} index={i} />)
        )}
      </div>
    </div>
  );
}
