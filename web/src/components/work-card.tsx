"use client";

import { useState, useEffect } from "react";
import { Check, Loader2, ChevronDown, Eye, Code2, ExternalLink, Clock, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepInfo { agent: string; summary: string; done: boolean }

const LABELS: Record<string, string> = {
  builder: "Builder 编码", tester: "Tester 验证", planner: "Planner 规划",
};

export function WorkCard({ steps, html, isActive, currentAgent, elapsed, timestamp }: {
  steps: StepInfo[]; html?: string; isActive: boolean; currentAgent: string; elapsed: number; timestamp: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const [blobUrl, setBlobUrl] = useState("");
  const [codeCopied, setCodeCopied] = useState(false);

  useEffect(() => {
    if (html) {
      const u = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      setBlobUrl(u);
      return () => URL.revokeObjectURL(u);
    }
  }, [html]);

  useEffect(() => {
    if (html && !isActive) setShowPreview(true);
  }, [html, isActive]);

  function copyCode() {
    if (!html) return;
    navigator.clipboard.writeText(html).then(() => {
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 2000);
    });
  }

  const doneSteps = steps.filter(s => s.done);

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}>
      {/* 头部 */}
      <button onClick={() => setExpanded(!expanded)} className="w-full px-4 py-3 flex items-center gap-2.5 transition-colors"
        style={{ color: "var(--text)" }}>
        {isActive ? <Loader2 size={15} className="animate-spin shrink-0" style={{ color: "var(--brand)" }} />
          : <div className="w-5 h-5 rounded-full flex items-center justify-center shrink-0" style={{ background: "var(--success-light)" }}><Check size={11} style={{ color: "var(--success)" }} /></div>}
        <span className="text-[13px] font-medium flex-1 text-left">
          {isActive ? `${LABELS[currentAgent] || currentAgent || "处理"}中...` : `完成 · ${doneSteps.length} 步`}
        </span>
        <div className="flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-3)" }}>
          <Clock size={11} />
          <span>{isActive ? `${elapsed}s` : new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <ChevronDown size={14} className={cn("transition-transform", !expanded && "-rotate-90")} style={{ color: "var(--text-3)" }} />
      </button>

      {/* 步骤 */}
      {expanded && doneSteps.length > 0 && (
        <div className="px-4 py-2" style={{ borderTop: "1px solid var(--border-light)" }}>
          {doneSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5">
              <Check size={12} style={{ color: "var(--success)" }} className="shrink-0" />
              <span className="text-xs font-medium" style={{ color: "var(--text-2)" }}>{LABELS[s.agent] || s.agent}</span>
              <span className="text-xs truncate flex-1 text-right" style={{ color: "var(--text-3)" }}>{s.summary}</span>
            </div>
          ))}
          {isActive && (
            <div className="flex items-center gap-2 py-1.5">
              <Loader2 size={12} className="animate-spin" style={{ color: "var(--brand)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--brand)" }}>{LABELS[currentAgent] || "处理中"}...</span>
            </div>
          )}
        </div>
      )}

      {/* 产出物 */}
      {html && (
        <div style={{ borderTop: "1px solid var(--border-light)" }}>
          <div className="px-4 py-2.5 flex items-center gap-3">
            <button onClick={() => { setShowPreview(!showPreview); setShowCode(false); }}
              className={cn("text-xs font-medium flex items-center gap-1 transition-colors")}
              style={{ color: showPreview ? "var(--brand)" : "var(--text-3)" }}>
              <Eye size={12} />{showPreview ? "收起" : "预览"}
            </button>
            <button onClick={() => { setShowCode(!showCode); setShowPreview(false); }}
              className="text-xs font-medium flex items-center gap-1 transition-colors"
              style={{ color: showCode ? "var(--brand)" : "var(--text-3)" }}>
              <Code2 size={12} />{showCode ? "收起" : "代码"}
            </button>
            <button onClick={copyCode}
              className="text-xs font-medium flex items-center gap-1 transition-colors"
              style={{ color: codeCopied ? "var(--success)" : "var(--text-3)" }}>
              {codeCopied ? <Check size={12} /> : <Copy size={12} />}{codeCopied ? "已复制" : "复制"}
            </button>
            {blobUrl && (
              <a href={blobUrl} target="_blank" rel="noopener" className="text-[11px] flex items-center gap-0.5 ml-auto transition-colors"
                style={{ color: "var(--text-3)" }}>
                新窗口 <ExternalLink size={10} />
              </a>
            )}
          </div>
          {showPreview && blobUrl && (
            <iframe src={blobUrl} className="w-full h-[420px] bg-white"
              style={{ borderTop: "1px solid var(--border-light)" }}
              tabIndex={0} />
          )}
          {showCode && (
            <pre className="w-full max-h-[300px] overflow-auto px-4 py-3 text-[11px] font-mono whitespace-pre-wrap"
              style={{ borderTop: "1px solid var(--border-light)", background: "var(--bg-sunken)", color: "var(--text-2)" }}>
              {html.slice(0, 5000)}{html.length > 5000 ? "\n..." : ""}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
