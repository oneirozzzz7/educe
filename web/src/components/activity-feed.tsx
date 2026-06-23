"use client";

import { useEffect, useRef } from "react";
import { Check, AlertCircle, ArrowRight, Package, ExternalLink, ChevronDown, ChevronRight } from "lucide-react";
import { marked } from "marked";
import { cn } from "@/lib/utils";
import type { AppEvent, ToolStream } from "@/lib/state";
import { ToolStreamCard } from "./tool-stream-card";
import { API_HOST } from "@/lib/ws";

interface ActivityFeedProps {
  events: AppEvent[];
  expandedEventIdx: number | null;
  onEventClick: (event: AppEvent, idx: number) => void;
  toolStreams: Record<string, ToolStream>;
  isThinking: boolean;
  onCancelTool?: (id: string) => void;
  sessionId: string;
  codeFiles: string[];
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function truncate(text: string, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "..." : text;
}

/** Inline expanded content for an event */
function ExpandedContent({ event, sessionId, codeFiles }: {
  event: AppEvent;
  sessionId: string;
  codeFiles: string[];
}) {
  switch (event.type) {
    case "ai_reply":
      return (
        <div
          className="expanded-content md"
          style={{
            padding: "12px 16px",
            fontSize: 14,
            color: "var(--text-1)",
            lineHeight: 1.7,
            maxWidth: 720,
            borderLeft: "2px solid var(--accent)",
            marginLeft: 20,
            marginRight: 12,
          }}
          dangerouslySetInnerHTML={{ __html: marked.parse(event.content || "") as string }}
        />
      );

    case "build_complete": {
      const file = event.file || (codeFiles.length > 0 ? codeFiles[0] : null);
      if (!file) {
        return (
          <div style={{ padding: "12px 16px", marginLeft: 20, color: "var(--text-2)", fontSize: 13 }}>
            Build completed. No preview available.
          </div>
        );
      }
      const previewUrl = `http://${API_HOST}/preview/${sessionId.slice(0, 16)}/${file}`;
      const isHtml = /\.(html?|svg)$/i.test(file);

      return (
        <div style={{ padding: "8px 16px", marginLeft: 20, marginRight: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: "var(--text-2)", fontWeight: 500 }}>{file}</span>
            <a
              href={previewUrl}
              target="_blank"
              rel="noopener"
              style={{
                fontSize: 11,
                color: "var(--accent)",
                textDecoration: "none",
                padding: "2px 8px",
                borderRadius: 4,
                background: "rgba(167,139,250,0.08)",
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <ExternalLink size={10} />
              Open in tab
            </a>
          </div>
          {isHtml ? (
            <iframe
              src={previewUrl}
              style={{
                width: "100%",
                height: 320,
                border: "1px solid var(--border-0)",
                borderRadius: 8,
                background: "#fff",
              }}
              sandbox="allow-scripts allow-same-origin"
            />
          ) : (
            <CodeBlock fileUrl={previewUrl} />
          )}
        </div>
      );
    }

    case "action_detail":
      return (
        <div style={{ padding: "8px 16px", marginLeft: 20, marginRight: 12 }}>
          <pre style={{
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-1)",
            fontFamily: "'Geist Mono', monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            margin: 0,
            padding: 12,
            background: "var(--surface-0)",
            borderRadius: 8,
            border: "1px solid var(--border-0)",
            maxHeight: 300,
            overflow: "auto",
          }}>
            {event.result || event.output || event.summary || "done"}
          </pre>
        </div>
      );

    case "error":
      return (
        <div style={{ padding: "8px 16px", marginLeft: 20, marginRight: 12 }}>
          <pre style={{
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--fail)",
            fontFamily: "'Geist Mono', monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            margin: 0,
            padding: 12,
            background: "var(--fail-dim)",
            borderRadius: 8,
            maxHeight: 300,
            overflow: "auto",
          }}>
            {event.message || event.error || event.traceback || "Unknown error"}
          </pre>
        </div>
      );

    default:
      return (
        <div style={{ padding: "8px 16px", marginLeft: 20, marginRight: 12 }}>
          <pre style={{
            fontSize: 11,
            color: "var(--text-2)",
            fontFamily: "'Geist Mono', monospace",
            whiteSpace: "pre-wrap",
            margin: 0,
            padding: 8,
            background: "var(--surface-0)",
            borderRadius: 6,
            maxHeight: 200,
            overflow: "auto",
          }}>
            {JSON.stringify(event, null, 2)}
          </pre>
        </div>
      );
  }
}

/** Simple code block that fetches file content */
function CodeBlock({ fileUrl }: { fileUrl: string }) {
  const ref = useRef<HTMLPreElement>(null);

  useEffect(() => {
    fetch(fileUrl)
      .then(r => r.text())
      .then(text => { if (ref.current) ref.current.textContent = text; })
      .catch(() => { if (ref.current) ref.current.textContent = "// Load failed"; });
  }, [fileUrl]);

  return (
    <pre ref={ref} style={{
      fontSize: 12,
      lineHeight: 1.5,
      color: "var(--text-1)",
      fontFamily: "'Geist Mono', monospace",
      whiteSpace: "pre-wrap",
      wordBreak: "break-all",
      margin: 0,
      padding: 12,
      background: "var(--surface-0)",
      borderRadius: 8,
      border: "1px solid var(--border-0)",
      maxHeight: 300,
      overflow: "auto",
    }}>
      Loading...
    </pre>
  );
}

/** Check if an event type is expandable */
function isExpandable(event: AppEvent): boolean {
  if (event.type === "ai_reply" && event.content && event.content.length > 0) return true;
  if (event.type === "build_complete") return true;
  if (event.type === "action_detail") return true;
  if (event.type === "error") return true;
  return false;
}

/** Render a single event as a compact single-line entry */
function EventLine({ event, idx, isExpanded, onClick }: {
  event: AppEvent;
  idx: number;
  isExpanded: boolean;
  onClick: () => void;
}) {
  const ts = formatTs(event.ts);
  const expandable = isExpandable(event);

  switch (event.type) {
    case "user_input":
      return (
        <div className="flex justify-end items-center gap-2 py-1 px-2">
          <span style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
          <span
            className="px-2.5 py-1 rounded-full text-right truncate max-w-[260px]"
            style={{
              background: "var(--accent-deep)",
              color: "#fff",
              fontSize: 12,
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
          style={{ background: isExpanded ? "var(--surface-1)" : "var(--accent-glow)" }}
          onClick={onClick}
        >
          {isExpanded ? (
            <ChevronDown size={12} className="shrink-0 mt-0.5" style={{ color: "var(--accent)" }} />
          ) : (
            <ChevronRight size={12} className="shrink-0 mt-0.5" style={{ color: "var(--accent)" }} />
          )}
          <div className="flex-1 min-w-0">
            <div className="truncate" style={{ fontSize: 12, color: "var(--text-1)", lineHeight: "1.4" }}>
              {truncate(event.content || "", 100)}
            </div>
            {!isExpanded && (
              <span style={{ fontSize: 10, color: "var(--text-3)" }}>Click to expand</span>
            )}
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
        <div
          className={cn("flex items-center gap-2 py-0.5 px-2", expandable && "cursor-pointer")}
          onClick={expandable ? onClick : undefined}
        >
          {isExpanded ? (
            <ChevronDown size={11} style={{ color: "var(--pass)" }} />
          ) : (
            <Check size={11} style={{ color: "var(--pass)" }} />
          )}
          <span style={{ fontSize: 11, color: "var(--text-2)", fontFamily: "'Geist Mono', monospace" }}>
            {event.name || "action"}: {truncate(event.summary || event.result || "done", 50)}
            {event.duration_ms != null && ` (${event.duration_ms}ms)`}
          </span>
          <span className="ml-auto" style={{ color: "var(--text-3)", fontSize: 10 }}>{ts}</span>
        </div>
      );

    case "error":
      return (
        <div
          className={cn("flex items-center gap-2 py-1 px-2", expandable && "cursor-pointer")}
          onClick={expandable ? onClick : undefined}
        >
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
        <div
          className="flex items-center gap-2 py-1 px-2 cursor-pointer"
          onClick={onClick}
        >
          {isExpanded ? (
            <ChevronDown size={12} style={{ color: "var(--pass)" }} />
          ) : (
            <Package size={12} style={{ color: "var(--pass)" }} />
          )}
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
 * ActivityFeed - Compressed event stream with inline expandable content.
 * Each event type gets a compact single-line rendering. Clicking an expandable
 * event reveals its full content inline below it.
 */
export function ActivityFeed({
  events,
  expandedEventIdx,
  onEventClick,
  toolStreams,
  isThinking,
  onCancelTool,
  sessionId,
  codeFiles,
}: ActivityFeedProps) {
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
          <div key={i}>
            <EventLine
              event={event}
              idx={i}
              isExpanded={expandedEventIdx === i}
              onClick={() => onEventClick(event, i)}
            />
            {/* Inline expanded content */}
            {expandedEventIdx === i && isExpandable(event) && (
              <div
                className="expanded-section"
                style={{
                  overflow: "hidden",
                  animation: "expandIn 0.2s ease-out",
                }}
              >
                <ExpandedContent
                  event={event}
                  sessionId={sessionId}
                  codeFiles={codeFiles}
                />
              </div>
            )}
          </div>
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
