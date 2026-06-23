"use client";

import { useEffect, useRef, useState } from "react";
import { X, ChevronDown, ChevronRight, MessageSquare, Zap, AlertTriangle, Terminal, Send } from "lucide-react";

interface DebugPanelProps {
  open: boolean;
  events: any[];
  onClose: () => void;
}

function isNoise(event: any): boolean {
  return event.type === "state_sync" || event.type === "status" || event.type === "ping";
}

function formatTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function getEventMeta(event: any): { icon: React.ReactNode; label: string; color: string; summary: string } {
  const type = event.type || "";

  if (type === "user_input" || type === "user_confirm") {
    return {
      icon: <Send size={12} />,
      label: "You",
      color: "var(--accent)",
      summary: event.content?.slice(0, 80) || event.text?.slice(0, 80) || "",
    };
  }
  if (type === "ai_reply" || type === "ai_reply_streaming") {
    return {
      icon: <MessageSquare size={12} />,
      label: "AI",
      color: "var(--pass)",
      summary: (event.content || "").slice(0, 80) || "responding...",
    };
  }
  if (type === "action_detail" || type.startsWith("tool")) {
    return {
      icon: <Terminal size={12} />,
      label: event.name || "action",
      color: "var(--text-2)",
      summary: event.summary || event.result || "done",
    };
  }
  if (type === "error" || type === "action_error") {
    return {
      icon: <AlertTriangle size={12} />,
      label: "Error",
      color: "var(--fail)",
      summary: event.message || event.error || "something went wrong",
    };
  }
  return {
    icon: <Zap size={12} />,
    label: type || "event",
    color: "var(--text-3)",
    summary: event.content || event.message || event.name || "",
  };
}

function EventCard({ event }: { event: any }) {
  const [expanded, setExpanded] = useState(false);
  const { icon, label, color, summary } = getEventMeta(event);

  return (
    <div style={{ paddingLeft: 20, position: "relative" }}>
      {/* Timeline dot */}
      <div style={{
        position: "absolute",
        left: 7,
        top: 12,
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
      }} />

      {/* Card */}
      <div
        className="rounded-lg mb-2 cursor-pointer transition-all hover:bg-[var(--surface-2)]"
        style={{ padding: "8px 12px", background: expanded ? "var(--surface-2)" : "transparent" }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Header row */}
        <div className="flex items-center gap-2">
          <span style={{ color }}>{icon}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color }}>{label}</span>
          <span className="flex-1 truncate" style={{ fontSize: 12, color: "var(--text-1)" }}>
            {summary.slice(0, 60)}
          </span>
          <span style={{ fontSize: 10, color: "var(--text-3)", flexShrink: 0 }}>
            {formatTime(event.ts)}
          </span>
        </div>

        {/* Expanded details */}
        {expanded && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--border-0)" }}>
            {/* Readable fields */}
            {event.duration_ms && (
              <div style={{ fontSize: 11, color: "var(--text-2)", marginBottom: 4 }}>
                Duration: {event.duration_ms}ms
              </div>
            )}
            {event.result && typeof event.result === "string" && (
              <pre style={{
                fontSize: 11, color: "var(--text-2)", margin: 0, whiteSpace: "pre-wrap",
                wordBreak: "break-all", maxHeight: 80, overflow: "auto",
              }}>
                {event.result.slice(0, 200)}
              </pre>
            )}
            {/* Raw JSON toggle */}
            <details style={{ marginTop: 6 }}>
              <summary style={{ fontSize: 10, color: "var(--text-3)", cursor: "pointer" }}>
                Raw data
              </summary>
              <pre style={{
                fontSize: 10, lineHeight: 1.3, color: "var(--text-3)", margin: "4px 0 0",
                maxHeight: 100, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all",
              }}>
                {JSON.stringify(event, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

export function DebugPanel({ open, events, onClose }: DebugPanelProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filtered = events.filter(e => !isNoise(e));

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered.length, autoScroll]);

  function handleScroll() {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }

  if (!open) return null;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="flex items-center px-4 shrink-0"
        style={{ height: 44, borderBottom: "1px solid var(--border-0)" }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-0)" }}>Activity</span>
        {filtered.length > 0 && (
          <span className="ml-2 px-1.5 py-0.5 rounded-full" style={{ fontSize: 10, color: "var(--text-3)", background: "var(--surface-2)" }}>
            {filtered.length}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={onClose}
          className="w-6 h-6 rounded-md flex items-center justify-center transition-all hover:bg-[var(--surface-2)]"
        >
          <X size={14} style={{ color: "var(--text-3)" }} />
        </button>
      </div>

      {/* Timeline */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto"
        onScroll={handleScroll}
        style={{ padding: "12px 8px 12px 12px" }}
      >
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2" style={{ color: "var(--text-3)" }}>
            <Zap size={20} style={{ opacity: 0.3 }} />
            <span style={{ fontSize: 12 }}>No activity yet</span>
            <span style={{ fontSize: 10 }}>Events will appear here as you interact</span>
          </div>
        ) : (
          <div style={{ borderLeft: "1px solid var(--border-1)", marginLeft: 9 }}>
            {filtered.map((event, i) => <EventCard key={i} event={event} />)}
          </div>
        )}
      </div>
    </div>
  );
}
