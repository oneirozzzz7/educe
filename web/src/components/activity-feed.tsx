"use client";

import { useEffect, useRef } from "react";
import { Check, AlertCircle, ArrowRight, Package } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AppEvent, ToolStream } from "@/lib/state";
import { ToolStreamCard } from "./tool-stream-card";

interface ActivityFeedProps {
  events: AppEvent[];
  onEventClick: (event: AppEvent) => void;
  toolStreams: Record<string, ToolStream>;
  isThinking: boolean;
  onCancelTool?: (id: string) => void;
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function truncate(text: string, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "..." : text;
}

/** Render a single event as a compact single-line entry */
function EventLine({ event, onClick }: { event: AppEvent; onClick: () => void }) {
  const ts = formatTs(event.ts);

  switch (event.type) {
    case "user_input":
      return (
        <div className="flex justify-end items-center gap-2 py-1 px-2" onClick={onClick}>
          <span style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
          <span
            className="px-2.5 py-1 rounded-full text-right truncate max-w-[260px]"
            style={{
              background: "var(--accent-deep)",
              color: "#fff",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            {truncate(event.content || event.text || "", 60)}
          </span>
        </div>
      );

    case "ai_reply":
      return (
        <div
          className="flex items-start gap-2 py-1.5 px-2 cursor-pointer rounded hover:opacity-90"
          style={{ background: "var(--accent-glow)" }}
          onClick={onClick}
        >
          <ArrowRight size={12} className="shrink-0 mt-0.5" style={{ color: "var(--accent)" }} />
          <div className="flex-1 min-w-0">
            <div className="truncate" style={{ fontSize: 12, color: "var(--text-1)", lineHeight: "1.4" }}>
              {truncate(event.content || "", 100)}
            </div>
            <span style={{ fontSize: 10, color: "var(--text-3)" }}>Canvas</span>
          </div>
          <span style={{ color: "var(--text-3)", fontSize: 10, flexShrink: 0 }}>{ts}</span>
        </div>
      );

    case "ai_reply_streaming":
      return (
        <div className="flex items-center gap-2 py-1.5 px-2">
          <div className="thinking-dots">
            <span /><span /><span />
          </div>
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>typing...</span>
        </div>
      );

    case "action_detail":
      return (
        <div className="flex items-center gap-2 py-0.5 px-2" onClick={onClick}>
          <Check size={11} style={{ color: "var(--pass)" }} />
          <span style={{ fontSize: 11, color: "var(--text-2)", fontFamily: "'Geist Mono', monospace" }}>
            {event.name || "action"}: {truncate(event.summary || event.result || "done", 50)}
            {event.duration_ms != null && ` (${event.duration_ms}ms)`}
          </span>
          <span className="ml-auto" style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
        </div>
      );

    case "error":
      return (
        <div className="flex items-center gap-2 py-1 px-2" onClick={onClick}>
          <AlertCircle size={12} style={{ color: "var(--fail)" }} />
          <span
            className="px-2 py-0.5 rounded truncate max-w-[280px]"
            style={{ background: "var(--fail-dim)", color: "var(--fail)", fontSize: 11 }}
          >
            {truncate(event.message || event.error || "Error", 80)}
          </span>
          <span className="ml-auto" style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
        </div>
      );

    case "transcript":
      return (
        <div className="flex items-center gap-2 py-0.5 px-2" style={{ opacity: 0.5 }}>
          <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>
            [{ts}] {truncate(event.content || event.text || "", 60)}
          </span>
        </div>
      );

    case "build_complete":
      return (
        <div className="flex items-center gap-2 py-1 px-2" onClick={onClick}>
          <Package size={12} style={{ color: "var(--pass)" }} />
          <span style={{ fontSize: 12, color: "var(--pass)" }}>
            Build complete{event.files ? ` (${event.files} files)` : ""}
          </span>
          <span className="ml-auto" style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
        </div>
      );

    default:
      return (
        <div className="flex items-center gap-2 py-0.5 px-2" onClick={onClick}>
          <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>
            [{ts}] {event.type}: {truncate(JSON.stringify(event).slice(0, 60), 60)}
          </span>
        </div>
      );
  }
}

/**
 * ActivityFeed - Compressed event stream (NOT chat bubbles).
 * Each event type gets a compact single-line rendering.
 */
export function ActivityFeed({ events, onEventClick, toolStreams, isThinking, onCancelTool }: ActivityFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new events
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, Object.keys(toolStreams).length]);

  // Active tool streams (running ones shown inline)
  const activeStreams = Object.values(toolStreams).filter(ts => ts.status === "running");

  return (
    <div
      className="flex-1 overflow-y-auto"
      style={{ background: "var(--bg)" }}
    >
      <div className="flex flex-col gap-0.5 py-2">
        {events.map((event, i) => (
          <EventLine key={i} event={event} onClick={() => onEventClick(event)} />
        ))}

        {/* Active tool streams */}
        {activeStreams.map(ts => (
          <div key={ts.id} className="px-2">
            <ToolStreamCard toolStream={ts} onCancel={onCancelTool} />
          </div>
        ))}

        {/* Thinking indicator (when no streaming event yet) */}
        {isThinking && !events.some(e => e.type === "ai_reply_streaming") && (
          <div className="flex items-center gap-2 py-1.5 px-2">
            <div className="thinking-dots">
              <span /><span /><span />
            </div>
            <span style={{ fontSize: 12, color: "var(--text-2)" }}>thinking...</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
