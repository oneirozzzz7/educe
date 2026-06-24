"use client";

import { useEffect, useRef, useState } from "react";
import { X, Zap, Clock, Terminal, Brain, AlertTriangle, Database } from "lucide-react";

interface DebugPanelProps {
  open: boolean;
  events: any[];
  onClose: () => void;
}

function formatTime(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function getEventDisplay(event: any): { icon: React.ReactNode; label: string; detail: string; color: string } | null {
  const name = event.name || "";
  const type = event.type || "";
  const data = event.data || {};
  const summary = event.summary || "";

  // lifecycle
  if (name === "ws_received" || name === "request_start") {
    const msg = data.user_message || summary || `${data.msg_len} chars`;
    return { icon: <Zap size={11} />, label: "Request", detail: msg.slice(0, 60), color: "var(--accent)" };
  }
  if (name === "request_complete") {
    const ms = data.wall_ms || event.duration_ms || 0;
    return { icon: <Clock size={11} />, label: "Done", detail: `${ms}ms`, color: "var(--pass)" };
  }
  if (name === "request_error") {
    return { icon: <AlertTriangle size={11} />, label: "Error", detail: data.error?.slice(0, 60) || summary, color: "var(--fail)" };
  }
  if (name === "task_cancelled") {
    return { icon: <X size={11} />, label: "Cancelled", detail: summary, color: "var(--text-3)" };
  }

  // llm_call
  if (name === "model_called") {
    const model = data.model || "";
    const round = data.round ?? "";
    return { icon: <Brain size={11} />, label: `LLM #${round}`, detail: model, color: "var(--text-2)" };
  }
  if (name === "llm_response" || name === "model_responded") {
    const ms = event.duration_ms || data.duration_ms || 0;
    const actions = data.actions_count || 0;
    const types = (data.action_types || []).join(", ");
    const preview = data.reply_preview || "";
    const detail = actions > 0
      ? `${ms}ms · ${types}`
      : `${ms}ms · ${preview.slice(0, 40) || "no action"}`;
    return { icon: <Brain size={11} />, label: `Response`, detail, color: ms > 5000 ? "var(--warning, orange)" : "var(--pass)" };
  }

  // tool_call
  if (name === "tool_result" || name === "action_executed") {
    const toolType = data.action_type || data.type || "";
    const success = data.success !== false;
    return { icon: <Terminal size={11} />, label: toolType, detail: success ? "✓" : "✗ " + (data.output_preview || "").slice(0, 40), color: success ? "var(--pass)" : "var(--fail)" };
  }
  if (name === "shell_exec") {
    return { icon: <Terminal size={11} />, label: "shell", detail: summary.slice(0, 50), color: "var(--text-2)" };
  }

  // memory
  if (name === "conflict_detected") {
    return { icon: <Database size={11} />, label: "Conflict", detail: summary.slice(0, 50), color: "var(--warning, orange)" };
  }
  if (name === "auto_write") {
    return { icon: <Database size={11} />, label: "Memory", detail: summary.slice(0, 50), color: "var(--text-3)" };
  }

  // fallback: skip unknown events
  return null;
}

function EventRow({ event }: { event: any }) {
  const [expanded, setExpanded] = useState(false);
  const display = getEventDisplay(event);
  if (!display) return null;

  const data = event.data || {};

  return (
    <div className="mb-0.5">
      <div
        className="flex items-center gap-2 py-1.5 px-2 rounded cursor-pointer transition-all hover:bg-[var(--surface-2)]"
        onClick={() => setExpanded(!expanded)}
      >
        <span style={{ color: display.color, flexShrink: 0 }}>{display.icon}</span>
        <span style={{ fontSize: 11, fontWeight: 500, color: display.color, flexShrink: 0, minWidth: 55 }}>
          {display.label}
        </span>
        <span className="flex-1 truncate" style={{ fontSize: 11, color: "var(--text-2)" }}>
          {display.detail}
        </span>
        <span style={{ fontSize: 9, color: "var(--text-3)", flexShrink: 0 }}>
          {formatTime(event.ts)}
        </span>
      </div>
      {expanded && (
        <div className="pl-8 pr-2 pb-2" style={{ fontSize: 11, color: "var(--text-3)" }}>
          {data.user_message && <div style={{ color: "var(--text-2)" }}>"{data.user_message}"</div>}
          {data.reply_preview && <div style={{ color: "var(--text-2)", marginTop: 2 }}>→ {data.reply_preview}</div>}
          {data.action_params && data.action_params.length > 0 && (
            <div style={{ marginTop: 2 }}>{data.action_types?.map((t: string, i: number) => `${t}: ${data.action_params[i] || ""}`).join(" | ")}</div>
          )}
          {data.error && <div style={{ color: "var(--fail)", marginTop: 2 }}>{data.error}</div>}
          {event.duration_ms && <div>⏱ {event.duration_ms}ms</div>}
        </div>
      )}
    </div>
  );
}

export function DebugPanel({ open, events, onClose }: DebugPanelProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Only show events that have meaningful display
  const displayable = events.filter(e => getEventDisplay(e) !== null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [displayable.length, autoScroll]);

  function handleScroll() {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }

  if (!open) return null;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-4 shrink-0" style={{ height: 44, borderBottom: "1px solid var(--border-0)" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-0)" }}>Activity</span>
        {displayable.length > 0 && (
          <span className="ml-2 px-1.5 py-0.5 rounded-full" style={{ fontSize: 10, color: "var(--text-3)", background: "var(--surface-2)" }}>
            {displayable.length}
          </span>
        )}
        <div className="flex-1" />
        <button onClick={onClose} className="w-6 h-6 rounded-md flex items-center justify-center transition-all hover:bg-[var(--surface-2)]">
          <X size={14} style={{ color: "var(--text-3)" }} />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={handleScroll} style={{ padding: "8px 4px" }}>
        {displayable.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2" style={{ color: "var(--text-3)" }}>
            <Zap size={20} style={{ opacity: 0.3 }} />
            <span style={{ fontSize: 12 }}>No activity yet</span>
            <span style={{ fontSize: 10 }}>Structured events stream here as requests process</span>
          </div>
        ) : (
          displayable.map((event, i) => <EventRow key={i} event={event} />)
        )}
      </div>
    </div>
  );
}
