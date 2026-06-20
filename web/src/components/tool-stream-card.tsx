"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Check, X, Square, ChevronDown, Terminal, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolStream } from "@/lib/state";

const MAX_VISIBLE_LINES = 200;

function StatusIcon({ status }: { status: ToolStream["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 size={14} className="animate-spin shrink-0" style={{ color: "var(--brand)" }} />;
    case "done":
      return (
        <div className="w-4 h-4 rounded-full flex items-center justify-center shrink-0" style={{ background: "var(--success-light)" }}>
          <Check size={10} style={{ color: "var(--success)" }} />
        </div>
      );
    case "cancelled":
      return <Square size={14} className="shrink-0" style={{ color: "var(--text-3)" }} />;
    case "error":
      return <X size={14} className="shrink-0" style={{ color: "var(--error)" }} />;
  }
}

function ToolIcon({ tool }: { tool: string }) {
  switch (tool) {
    case "shell":
      return <Terminal size={13} style={{ color: "var(--text-2)" }} />;
    case "write_file":
      return <FileText size={13} style={{ color: "var(--text-2)" }} />;
    default:
      return <Terminal size={13} style={{ color: "var(--text-2)" }} />;
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StreamView({ lines, autoScroll }: { lines: ToolStream["lines"]; autoScroll: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (autoScroll && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [lines.length, autoScroll]);

  const visibleLines = lines.length > MAX_VISIBLE_LINES
    ? lines.slice(-MAX_VISIBLE_LINES)
    : lines;
  const truncated = lines.length > MAX_VISIBLE_LINES;

  if (collapsed || lines.length === 0) return null;

  return (
    <div
      ref={ref}
      className="overflow-auto font-mono text-[12px] leading-[1.6] p-3 max-h-[300px]"
      style={{ background: "var(--bg-code)", borderTop: "1px solid var(--border-light)" }}
    >
      {truncated && (
        <div className="text-[11px] mb-1" style={{ color: "var(--text-3)" }}>
          ... {lines.length - MAX_VISIBLE_LINES} lines hidden ...
        </div>
      )}
      {visibleLines.map((line, i) => (
        <div
          key={i}
          className={cn(
            "whitespace-pre-wrap break-all",
            line.stream === "stderr" && "text-red-400",
            line.stream === "diff" && line.data.startsWith("+") && "text-green-400",
            line.stream === "diff" && line.data.startsWith("-") && "text-red-400",
            line.stream === "diff" && line.data.startsWith("@@") && "text-cyan-400",
          )}
          style={{ color: line.stream === "stdout" || line.stream === "content" ? "var(--text)" : undefined }}
        >
          {line.data}
        </div>
      ))}
    </div>
  );
}

export function ToolStreamCard({
  toolStream,
  onCancel,
}: {
  toolStream: ToolStream;
  onCancel?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const elapsed = toolStream.result?.duration_ms
    ?? (toolStream.status === "running" ? Date.now() - toolStream.startedAt : 0);

  const title = toolStream.tool === "shell"
    ? toolStream.meta.cmd || "shell"
    : toolStream.tool === "write_file"
      ? `${toolStream.meta.mode === "modify" ? "修改" : "写入"} ${toolStream.meta.path || ""}`
      : toolStream.tool;

  const exitCode = toolStream.result?.exit_code;
  const isSuccess = toolStream.status === "done" && (exitCode === 0 || exitCode === undefined);

  return (
    <div
      className="rounded-xl overflow-hidden my-2"
      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", boxShadow: "var(--shadow-sm)" }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <StatusIcon status={toolStream.status} />
        <ToolIcon tool={toolStream.tool} />
        <span className="text-[12px] font-medium flex-1 truncate" style={{ color: "var(--text)" }}>
          {title}
        </span>

        {/* Meta info */}
        <div className="flex items-center gap-2 text-[11px]" style={{ color: "var(--text-3)" }}>
          {toolStream.status === "done" && exitCode !== undefined && exitCode !== null && (
            <span className={cn(exitCode === 0 ? "text-green-500" : "text-red-400")}>
              exit {exitCode}
            </span>
          )}
          {toolStream.result?.lines && (
            <span>{toolStream.result.lines} lines</span>
          )}
          {elapsed > 0 && <span>{formatDuration(elapsed)}</span>}
          {toolStream.result?.background && (
            <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: "var(--brand-light)", color: "var(--brand)" }}>
              后台
            </span>
          )}
        </div>

        {/* Cancel button */}
        {toolStream.status === "running" && onCancel && (
          <button
            onClick={(e) => { e.stopPropagation(); onCancel(toolStream.id); }}
            className="px-2 py-0.5 rounded text-[11px] hover:opacity-80 transition-opacity"
            style={{ background: "var(--error-light)", color: "var(--error)" }}
          >
            停止
          </button>
        )}

        <ChevronDown
          size={13}
          className={cn("transition-transform", !expanded && "-rotate-90")}
          style={{ color: "var(--text-3)" }}
        />
      </div>

      {/* Body */}
      {expanded && (
        <StreamView
          lines={toolStream.lines}
          autoScroll={toolStream.status === "running"}
        />
      )}
    </div>
  );
}
