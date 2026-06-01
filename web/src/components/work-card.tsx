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

interface ToolEvent {
  event: string;
  content?: string;
  file?: string;
  size?: number;
  command?: string;
  success?: boolean;
  output?: string;
  files?: string[];
  turns?: number;
}

export function WorkCard({ steps, html, isActive, currentAgent, elapsed, timestamp, streamingCode, toolEvents }: {
  steps: StepInfo[]; html?: string; isActive: boolean; currentAgent: string; elapsed: number; timestamp: number; streamingCode?: string; toolEvents?: ToolEvent[];
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
  const streamSize = streamingCode ? streamingCode.length : 0;
  const progress = isActive
    ? (streamSize > 0
      ? Math.min(90, Math.round((streamSize / 8000) * 80))
      : (doneSteps.length > 0 ? Math.min(80, doneSteps.length * 25) : 5))
    : 100;

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
            ? streamSize > 0
              ? `💻 生成中... ${(streamSize / 1024).toFixed(1)} KB`
              : `${STEP_ICONS[currentAgent] || "⚙️"} ${LABELS[currentAgent] || currentAgent || "处理"}中...`
            : `完成 · ${doneSteps.length} 步${html ? ` · ${fileSize} KB` : ""}`}
        </span>
        <div className="flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-3)" }}>
          <Clock size={11} />
          <span>{isActive ? `${elapsed}s` : new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
        <ChevronDown size={14} className={cn("transition-transform", !expanded && "-rotate-90")} style={{ color: "var(--text-3)" }} />
      </button>

      {/* 动作序列——展示模型每一步的思考和行动 */}
      {expanded && (toolEvents?.length || 0) > 0 && (
        <div className="px-4 py-2 space-y-1" style={{ borderTop: "1px solid var(--border-light)" }}>
          {toolEvents!.map((evt, i) => (
            <div key={i} className="py-0.5">
              {evt.event === "thinking" && (
                <div className="flex items-start gap-2">
                  <span className="text-xs shrink-0 mt-0.5">💭</span>
                  <span className="text-xs italic" style={{ color: "var(--text-3)" }}>{evt.content}</span>
                </div>
              )}
              {evt.event === "write_file" && (
                <div className="flex items-center gap-2">
                  <span className="text-xs">📝</span>
                  <span className="text-xs font-medium" style={{ color: "var(--text-2)" }}>写入 {evt.file}</span>
                </div>
              )}
              {evt.event === "run" && (
                <div className="flex items-center gap-2">
                  <span className="text-xs">▶️</span>
                  <code className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: "var(--bg-sunken)", color: "var(--text-2)" }}>{evt.command}</code>
                </div>
              )}
              {(evt.event === "run_result" || evt.event === "write_file_result") && (
                <div className="flex items-start gap-2 ml-5">
                  {evt.success ? (
                    <Check size={11} className="mt-0.5 shrink-0" style={{ color: "var(--success)" }} />
                  ) : (
                    <span className="text-[11px] shrink-0">✗</span>
                  )}
                  <span className={cn("text-[11px]", evt.success ? "" : "font-medium")}
                    style={{ color: evt.success ? "var(--text-3)" : "var(--error, #ef4444)" }}>
                    {evt.output?.split("\n")[0]?.slice(0, 80)}
                  </span>
                </div>
              )}
              {evt.event === "read_file_result" && (
                <div className="flex items-center gap-2 ml-5">
                  <Check size={11} style={{ color: "var(--success)" }} />
                  <span className="text-[11px]" style={{ color: "var(--text-3)" }}>已读取</span>
                </div>
              )}
              {evt.event === "done" && (
                <div className="flex items-center gap-2 pt-1">
                  <span className="text-xs">✅</span>
                  <span className="text-xs font-medium" style={{ color: "var(--success)" }}>
                    完成 · {evt.turns}轮 · {evt.files?.join(", ")}
                  </span>
                </div>
              )}
            </div>
          ))}
          {isActive && !(toolEvents?.some(e => e.event === "done")) && (
            <div className="flex items-center gap-2 py-1">
              <Loader2 size={11} className="animate-spin shrink-0" style={{ color: "var(--brand)" }} />
              <span className="text-[11px]" style={{ color: "var(--brand)" }}>执行中...</span>
            </div>
          )}
        </div>
      )}

      {/* 旧步骤列表（兼容无toolEvents的情况） */}
      {expanded && doneSteps.length > 0 && !(toolEvents?.length) && (
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

      {/* 构建中实时代码预览 */}
      {isActive && streamingCode && !html && (
        <div style={{ borderTop: "1px solid var(--border-light)" }}>
          <div className="px-4 py-2 flex items-center gap-2">
            <Code2 size={12} style={{ color: "var(--brand)" }} />
            <span className="text-[11px] font-medium" style={{ color: "var(--brand)" }}>实时生成中...</span>
            <span className="text-[10px] ml-auto tabular-nums" style={{ color: "var(--text-4)" }}>
              {(streamingCode.length / 1024).toFixed(1)} KB
            </span>
          </div>
          <pre className="px-4 pb-3 text-[11px] leading-[1.6] overflow-auto max-h-[300px] font-mono"
            style={{ color: "var(--text-2)" }}>
            {streamingCode.slice(-2000)}
          </pre>
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
