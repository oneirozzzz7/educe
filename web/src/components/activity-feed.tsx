"use client";

import { useEffect, useRef, useState } from "react";
import { Check, AlertCircle, Package, ExternalLink, ChevronDown, ChevronUp } from "lucide-react";
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
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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

/** User message bubble (right-aligned) */
function UserBubble({ event }: { event: AppEvent }) {
  return (
    <div className="flex justify-end mb-3" style={{ paddingLeft: "15%" }}>
      <div className="flex flex-col items-end gap-1">
        <div className="user-msg">{event.content || event.text || ""}</div>
        <span style={{ fontSize: 10, color: "var(--text-3)", paddingRight: 4 }}>{formatTs(event.ts)}</span>
      </div>
    </div>
  );
}

/** AI reply with purple bar, collapsible */
function AiReplyBubble({ event, isExpanded, onToggle }: {
  event: AppEvent;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const content = event.content || "";
  const lines = content.split("\n");
  const isLong = lines.length > 8 || content.length > 500;
  const showFull = isExpanded || !isLong;

  return (
    <div className="mb-3">
      <div className="ai-reply">
        <div className="ai-reply-bar" />
        <div className="ai-reply-content" style={{ flex: 1, minWidth: 0, position: "relative" }}>
          <div
            className="md"
            style={{
              maxHeight: showFull ? "none" : 160,
              overflow: showFull ? "visible" : "hidden",
              maskImage: showFull ? "none" : "linear-gradient(to bottom, black 60%, transparent 100%)",
              WebkitMaskImage: showFull ? "none" : "linear-gradient(to bottom, black 60%, transparent 100%)",
            }}
            dangerouslySetInnerHTML={{ __html: marked.parse(content) as string }}
          />
          {isLong && (
            <button
              onClick={onToggle}
              className="flex items-center gap-1 mt-1.5 transition-colors hover:text-[var(--accent)]"
              style={{ fontSize: 12, color: "var(--text-3)", background: "none", border: "none", cursor: "pointer", padding: "2px 0", fontFamily: "inherit" }}
            >
              {showFull ? <><ChevronUp size={12} /> Collapse</> : <><ChevronDown size={12} /> Expand</>}
            </button>
          )}
          <span style={{ fontSize: 10, color: "var(--text-3)", display: "block", marginTop: 4 }}>{formatTs(event.ts)}</span>
        </div>
      </div>
    </div>
  );
}

/** Action detail line */
function ActionLine({ event, isExpanded, onToggle }: {
  event: AppEvent;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="mb-2">
      <div
        className="flex items-center gap-2 py-1.5 px-3 rounded-lg cursor-pointer transition-all hover:bg-[var(--surface-1)]"
        onClick={onToggle}
      >
        <Check size={12} style={{ color: "var(--pass)", flexShrink: 0 }} />
        <span className="truncate" style={{ fontSize: 12, color: "var(--text-2)", fontFamily: "'Geist Mono', monospace" }}>
          {event.name || "action"}: {event.summary || event.result || "done"}
          {event.duration_ms != null && ` (${event.duration_ms}ms)`}
        </span>
        <span className="ml-auto shrink-0" style={{ fontSize: 10, color: "var(--text-3)" }}>{formatTs(event.ts)}</span>
      </div>
      {isExpanded && (
        <div style={{ padding: "4px 0 4px 28px", animation: "expandIn 0.2s ease-out" }}>
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
      )}
    </div>
  );
}

/** Error event */
function ErrorLine({ event, isExpanded, onToggle }: {
  event: AppEvent;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="mb-2">
      <div
        className="flex items-center gap-2 py-1.5 px-3 rounded-lg cursor-pointer transition-all hover:bg-[var(--fail-dim)]"
        onClick={onToggle}
      >
        <AlertCircle size={12} style={{ color: "var(--fail)", flexShrink: 0 }} />
        <span className="truncate" style={{ fontSize: 12, color: "var(--fail)" }}>
          {event.message || event.error || "Error"}
        </span>
        <span className="ml-auto shrink-0" style={{ fontSize: 10, color: "var(--text-3)" }}>{formatTs(event.ts)}</span>
      </div>
      {isExpanded && (
        <div style={{ padding: "4px 0 4px 28px", animation: "expandIn 0.2s ease-out" }}>
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
      )}
    </div>
  );
}

/** Build complete event */
function BuildLine({ event, isExpanded, onToggle, sessionId, codeFiles }: {
  event: AppEvent;
  isExpanded: boolean;
  onToggle: () => void;
  sessionId: string;
  codeFiles: string[];
}) {
  const file = event.file || (codeFiles.length > 0 ? codeFiles[0] : null);

  return (
    <div className="mb-2">
      <div
        className="flex items-center gap-2 py-1.5 px-3 rounded-lg cursor-pointer transition-all hover:bg-[var(--pass-dim)]"
        onClick={onToggle}
      >
        <Package size={12} style={{ color: "var(--pass)", flexShrink: 0 }} />
        <span style={{ fontSize: 12, color: "var(--pass)" }}>
          Build complete{event.files ? ` (${event.files} files)` : ""}
        </span>
        <span className="ml-auto shrink-0" style={{ fontSize: 10, color: "var(--text-3)" }}>{formatTs(event.ts)}</span>
      </div>
      {isExpanded && file && (
        <div style={{ padding: "8px 0 4px 28px", animation: "expandIn 0.2s ease-out" }}>
          {(() => {
            const previewUrl = `http://${API_HOST}/preview/${sessionId.slice(0, 16)}/${file}`;
            const isHtml = /\.(html?|svg)$/i.test(file);
            return (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 12, color: "var(--text-2)", fontWeight: 500 }}>{file}</span>
                  <a href={previewUrl} target="_blank" rel="noopener"
                    style={{ fontSize: 11, color: "var(--accent)", textDecoration: "none", padding: "2px 8px", borderRadius: 4, background: "rgba(167,139,250,0.08)", display: "inline-flex", alignItems: "center", gap: 4 }}>
                    <ExternalLink size={10} /> Open
                  </a>
                </div>
                {isHtml ? (
                  <iframe src={previewUrl} style={{ width: "100%", height: 320, border: "1px solid var(--border-0)", borderRadius: 8, background: "#fff" }} sandbox="allow-scripts allow-same-origin" />
                ) : (
                  <CodeBlock fileUrl={previewUrl} />
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

/** Thinking indicator */
function ThinkingIndicator() {
  return (
    <div className="mb-3">
      <div className="ai-reply" style={{ opacity: 0.7 }}>
        <div className="ai-reply-bar" style={{ background: "var(--accent)", opacity: 0.5 }} />
        <div className="flex items-center gap-2 py-2">
          <div className="thinking-dots">
            <span /><span /><span />
          </div>
          <span style={{ fontSize: 13, color: "var(--text-2)" }}>Thinking...</span>
        </div>
      </div>
    </div>
  );
}

/**
 * ActivityFeed - Chat-style event stream with bubbles and expandable AI replies.
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, Object.keys(toolStreams).length]);

  const activeStreams = Object.values(toolStreams).filter(ts => ts.status === "running");

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "24px 16px 16px" }}>
        {events.map((event, i) => {
          const expanded = expandedEventIdx === i;
          const toggle = () => onEventClick(event, i);

          switch (event.type) {
            case "user_input":
              return <UserBubble key={i} event={event} />;

            case "ai_reply":
              return <AiReplyBubble key={i} event={event} isExpanded={expanded} onToggle={toggle} />;

            case "ai_reply_streaming":
              return <ThinkingIndicator key={i} />;

            case "action_detail":
              return <ActionLine key={i} event={event} isExpanded={expanded} onToggle={toggle} />;

            case "error":
              return <ErrorLine key={i} event={event} isExpanded={expanded} onToggle={toggle} />;

            case "build_complete":
              return <BuildLine key={i} event={event} isExpanded={expanded} onToggle={toggle} sessionId={sessionId} codeFiles={codeFiles} />;

            case "transcript":
              return (
                <div key={i} className="mb-1 px-3" style={{ opacity: 0.4 }}>
                  <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>
                    [{formatTs(event.ts)}] {event.content || event.text || ""}
                  </span>
                </div>
              );

            default:
              return null;
          }
        })}

        {/* Active tool streams */}
        {activeStreams.map(ts => (
          <div key={ts.id} className="mb-2">
            <ToolStreamCard toolStream={ts} onCancel={onCancelTool} />
          </div>
        ))}

        {/* Thinking (when no streaming event) */}
        {isThinking && !events.some(e => e.type === "ai_reply_streaming") && (
          <ThinkingIndicator />
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
