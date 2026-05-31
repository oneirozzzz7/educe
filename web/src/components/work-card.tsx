"use client";

import { useState, useEffect, useRef } from "react";
import { Check, Loader2, ChevronDown, Eye, Code2, ExternalLink, Clock, Copy, Download } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepInfo { agent: string; summary: string; done: boolean }

const LABELS: Record<string, string> = {
  builder: "构建", tester: "测试", planner: "规划",
  project_manager: "项目管理", product_manager: "产品",
  architect: "架构", engineer: "工程", reviewer: "审查",
  crowd_user: "内测", memory_keeper: "沉淀", assistant: "助手",
};

const STEP_ICONS: Record<string, string> = {
  builder: "💻", tester: "🧪", planner: "📋",
  project_manager: "🎯", product_manager: "📋",
  architect: "🏗", engineer: "💻", reviewer: "🔍",
  crowd_user: "👥", memory_keeper: "🧠", assistant: "💬",
};

export function WorkCard({ steps, html, isActive, currentAgent, elapsed, timestamp }: {
  steps: StepInfo[]; html?: string; isActive: boolean; currentAgent: string; elapsed: number; timestamp: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const [blobUrl, setBlobUrl] = useState("");
  const [codeCopied, setCodeCopied] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

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

  function downloadCode() {
    if (!html) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    a.download = "index.html";
    a.click();
  }

  const doneSteps = steps.filter(s => s.done);
  const fileSize = html ? (new Blob([html]).size / 1024).toFixed(1) : "0";
  const totalExpected = Math.max(doneSteps.length + 1, 3);
  const progress = isActive ? Math.min(95, Math.round((doneSteps.length / totalExpected) * 80) + (elapsed > 5 ? 10 : 0)) : 100;

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}>
      {/* 进度条 */}
      {isActive && (
        <div className="h-1 w-full" style={{ background: "var(--border-light)" }}>
          <div className="h-full transition-all duration-500" style={{ width: `${progress}%`, background: "var(--brand)" }} />
        </div>
      )}
      {/* 头部 */}
      <button onClick={() => setExpanded(!expanded)} className="w-full px-4 py-3 flex items-center gap-2.5 transition-colors"
        style={{ color: "var(--text)" }}>
        {isActive ? (
          <Loader2 size={15} className="animate-spin shrink-0" style={{ color: "var(--brand)" }} />
        ) : (
          <div className="w-5 h-5 rounded-full flex items-center justify-center shrink-0" style={{ background: "var(--success-light)" }}>
            <Check size={11} style={{ color: "var(--success)" }} />
          </div>
        )}
        <span className="text-[13px] font-medium flex-1 text-left">
          {isActive
            ? `${STEP_ICONS[currentAgent] || "⚙️"} ${LABELS[currentAgent] || currentAgent || "处理"}中... ${progress}%`
            : `完成 · ${doneSteps.length} 步${html ? ` · ${fileSize} KB` : ""}`}
        </span>
        <div className="flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-3)" }}>
          <Clock size={11} />
          <span>{isActive ? `${elapsed}s` : new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <ChevronDown size={14} className={cn("transition-transform", !expanded && "-rotate-90")} style={{ color: "var(--text-3)" }} />
      </button>

      {/* 步骤列表 */}
      {expanded && doneSteps.length > 0 && (
        <div className="px-4 py-2" style={{ borderTop: "1px solid var(--border-light)" }}>
          {doneSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5">
              <Check size={12} style={{ color: "var(--success)" }} className="shrink-0" />
              <span className="text-xs font-medium shrink-0" style={{ color: "var(--text-2)" }}>
                {STEP_ICONS[s.agent] || "⚙️"} {LABELS[s.agent] || s.agent}
              </span>
              <span className="text-xs truncate flex-1 text-right" style={{ color: "var(--text-3)" }}>{s.summary}</span>
            </div>
          ))}
          {isActive && (
            <div className="flex items-center gap-2 py-1.5">
              <Loader2 size={12} className="animate-spin shrink-0" style={{ color: "var(--brand)" }} />
              <span className="text-xs font-medium" style={{ color: "var(--brand)" }}>
                {STEP_ICONS[currentAgent] || "⚙️"} {LABELS[currentAgent] || "处理中"}...
              </span>
              <span className="text-[10px] ml-auto tabular-nums" style={{ color: "var(--text-4)" }}>{elapsed}s</span>
            </div>
          )}
        </div>
      )}

      {/* 产出物区域 */}
      {html && (
        <div style={{ borderTop: "1px solid var(--border-light)" }}>
          {/* 工具栏 */}
          <div className="px-4 py-2.5 flex items-center gap-2 flex-wrap">
            <button onClick={() => { setShowPreview(!showPreview); setShowCode(false); }}
              className={cn("text-xs font-medium flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all",
                showPreview ? "shadow-sm" : "")}
              style={{
                color: showPreview ? "white" : "var(--text-3)",
                background: showPreview ? "var(--brand)" : "transparent",
              }}>
              <Eye size={12} />{showPreview ? "收起预览" : "预览"}
            </button>
            <button onClick={() => { setShowCode(!showCode); setShowPreview(false); }}
              className={cn("text-xs font-medium flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all",
                showCode ? "shadow-sm" : "")}
              style={{
                color: showCode ? "white" : "var(--text-3)",
                background: showCode ? "var(--brand)" : "transparent",
              }}>
              <Code2 size={12} />{showCode ? "收起代码" : "代码"}
            </button>
            <button onClick={copyCode}
              className="text-xs font-medium flex items-center gap-1 px-2 py-1.5 rounded-lg transition-colors"
              style={{ color: codeCopied ? "var(--success)" : "var(--text-3)" }}>
              {codeCopied ? <Check size={12} /> : <Copy size={12} />}{codeCopied ? "已复制" : "复制"}
            </button>
            <button onClick={downloadCode}
              className="text-xs font-medium flex items-center gap-1 px-2 py-1.5 rounded-lg transition-colors"
              style={{ color: "var(--text-3)" }}>
              <Download size={12} />下载
            </button>

            {/* 新窗口——醒目按钮 */}
            {blobUrl && (
              <a href={blobUrl} target="_blank" rel="noopener"
                className="ml-auto text-xs font-medium flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all hover:shadow-sm"
                style={{ background: "var(--brand-light)", color: "var(--brand)" }}>
                <ExternalLink size={12} /> 新窗口打开
              </a>
            )}
          </div>

          {/* 预览iframe */}
          {showPreview && blobUrl && (
            <div className="relative" style={{ borderTop: "1px solid var(--border-light)" }}>
              <iframe ref={iframeRef} src={blobUrl} className="w-full h-[450px] bg-white" tabIndex={0}
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms" />
            </div>
          )}

          {/* 代码查看 */}
          {showCode && (
            <pre className="w-full max-h-[400px] overflow-auto px-4 py-3 text-[11px] font-mono whitespace-pre-wrap leading-relaxed"
              style={{ borderTop: "1px solid var(--border-light)", background: "var(--bg-sunken)", color: "var(--text-2)" }}>
              {html}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
