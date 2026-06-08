"use client";

import { useReducer, useRef, useEffect, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Copy, Download, ArrowUpRight, Paperclip, Archive } from "lucide-react";
import { marked } from "marked";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/i18n";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { MessageBubble } from "@/components/message-bubble";
import { FileChips } from "@/components/file-chips";
import { ToastContainer, toast } from "@/components/toast";
import { PlanProposal } from "@/components/plan-proposal";
import { reducer, INITIAL_STATE, hasArtifact, isActive, hasBuildTranscript, type AppState, type Action, type UploadedFile, type TranscriptEntry } from "@/lib/state";
import { mapWsMessage } from "@/lib/ws-handler";

const EASE = [0.16, 1, 0.3, 1] as const;
const ACCEPT = ".txt,.py,.js,.ts,.tsx,.jsx,.css,.html,.json,.md,.yaml,.yml,.xml,.csv,.sh,.sql,.go,.java,.c,.cpp,.h,.rb,.rs,.swift,.pdf,.xlsx,.xls,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg";

marked.setOptions({ breaks: true, gfm: true });

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Helpers
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function extractHtml(c: string) {
  const m = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?<\/html>)/i)
    || c.match(/```html\n([\s\S]*?<\/html>)/i)
    || c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
  return m ? m[1] : null;
}

function highlightLine(raw: string): string {
  return raw
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\/\/.*/g, m => `<span style="color:var(--text-3);font-style:italic">${m}</span>`)
    .replace(/\b(const|let|var|class|function|if|else|return|new|this|import|export|from|async|await|for|while|true|false|null|undefined)\b/g, m => `<span style="color:var(--amber)">${m}</span>`)
    .replace(/(["'`])(?:(?!\1).)*\1/g, m => `<span style="color:var(--sage)">${m}</span>`)
    .replace(/\b(\d+\.?\d*)\b/g, m => `<span style="color:#e0a5a5">${m}</span>`)
    .replace(/&lt;\/?[a-zA-Z][^&]*&gt;/g, m => `<span style="color:var(--amber-bright)">${m}</span>`);
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Sigil — animated logo/loading indicator
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function Sigil({ size = 96 }: { size?: number }) {
  return (
    <svg viewBox="0 0 96 96" style={{ width: size, height: size }}>
      <circle cx="48" cy="48" r="46" fill="none" stroke="var(--border-1)" strokeWidth="0.5" />
      <circle cx="48" cy="48" r="33" fill="none" stroke="var(--border-1)" strokeWidth="0.4" />
      <circle cx="48" cy="48" r="20" fill="none" stroke="var(--border-0)" strokeWidth="0.3" opacity="0.6" />
      <circle cx="48" cy="48" r="46" fill="none" stroke="var(--amber)" strokeWidth="2" strokeLinecap="round" strokeDasharray="60 160" style={{ animation: "e-spin 10s linear infinite", transformOrigin: "center" }} />
      <circle cx="48" cy="48" r="33" fill="none" stroke="var(--amber-bright)" strokeWidth="1.2" strokeLinecap="round" strokeDasharray="40 168" opacity="0.55" style={{ animation: "e-spin-r 16s linear infinite", transformOrigin: "center" }} />
      <circle cx="48" cy="48" r="20" fill="none" stroke="var(--amber)" strokeWidth="0.7" strokeLinecap="round" strokeDasharray="22 104" opacity="0.35" style={{ animation: "e-spin 7s linear infinite", transformOrigin: "center" }} />
      <circle cx="48" cy="48" r="10" fill="var(--amber)" opacity="0.04" style={{ animation: "e-breathe 4s ease-in-out infinite" }} />
      <circle cx="48" cy="48" r="4" fill="var(--amber)" opacity="0.85" />
      <circle cx="48" cy="48" r="2" fill="var(--text-0)" opacity="0.6" />
      <style>{`@keyframes e-spin{to{transform:rotate(360deg)}}@keyframes e-spin-r{to{transform:rotate(-360deg)}}@keyframes e-breathe{0%,100%{opacity:.03}50%{opacity:.1}}`}</style>
    </svg>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BriefBar — top status during active session
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function BriefBar({ text, elapsed }: { text: string; elapsed: number }) {
  const { t } = useLocale();
  return (
    <div className="flex items-center gap-3 shrink-0 relative" style={{ height: 42, padding: "0 24px", borderBottom: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "var(--amber)", padding: "3px 9px", background: "var(--amber-dim)", borderRadius: 4, border: "1px solid rgba(212,148,76,0.15)" }}>{t("brief.label")}</span>
      <span className="truncate" style={{ fontSize: 13, color: "var(--text-1)", flex: 1, fontWeight: 500 }}>{text}</span>
      <span style={{ fontSize: 12, color: "var(--amber)", fontFamily: "'Geist Mono', monospace", fontVariantNumeric: "tabular-nums", padding: "3px 10px", background: "rgba(212,148,76,0.04)", borderRadius: 5, border: "1px solid rgba(212,148,76,0.1)" }}>{elapsed}s</span>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   TranscriptTimeline — build process visibility
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function TranscriptTimeline({ entries, isBuilding }: { entries: TranscriptEntry[]; isBuilding: boolean }) {
  const phaseLabels: Record<string, string> = { analyze: "分析", plan: "规划", build: "构建", verify: "验证" };
  const phaseColors: Record<string, string> = { analyze: "var(--sage)", plan: "var(--amber)", build: "var(--amber)", verify: "var(--pass)" };

  return (
    <div className="mb-4" style={{ padding: "12px 16px", borderRadius: 12, background: "var(--surface-1)", border: "1px solid var(--border-0)" }}>
      {entries.map((evt, i) => {
        const label = phaseLabels[evt.phase || ""] || evt.phase || "";
        const dotColor = phaseColors[evt.phase || ""] || "var(--text-3)";
        const isLast = i === entries.length - 1 && isBuilding;
        return (
          <div key={i} className="flex items-start gap-2 py-1" style={{ fontSize: 12 }}>
            {isLast ? (
              <svg width="14" height="14" viewBox="0 0 14 14" style={{ marginTop: 2, flexShrink: 0, animation: "e-spin 1s linear infinite" }}>
                <circle cx="7" cy="7" r="5" fill="none" stroke={dotColor} strokeWidth="1.5" strokeDasharray="20 12" strokeLinecap="round" />
              </svg>
            ) : (
              <div style={{ width: 6, height: 6, borderRadius: "50%", marginTop: 5, flexShrink: 0, background: dotColor }} />
            )}
            {label && <span style={{ color: "var(--text-3)", fontSize: 11, minWidth: 32 }}>[{label}]</span>}
            <span style={{ color: "var(--text-2)", flex: 1 }}>{evt.content}</span>
            {evt.elapsed ? <span style={{ color: "var(--text-3)", fontSize: 10, flexShrink: 0 }}>{evt.elapsed}s</span> : null}
          </div>
        );
      })}
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   PreviewFrame — scales iframe for responsive layouts
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function PreviewFrame({ iframeRef }: { iframeRef: React.RefObject<HTMLIFrameElement | null> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = containerRef.current;
    const iframe = iframeRef.current;
    if (!el || !iframe) return;
    const updateScale = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      const scale = Math.min(w / 1280, 1);
      iframe.style.transform = `scale(${scale})`;
      iframe.style.transformOrigin = "top left";
      iframe.style.width = `${1280}px`;
      iframe.style.height = `${Math.floor(h / scale)}px`;
    };
    updateScale();
    const obs = new ResizeObserver(updateScale);
    obs.observe(el);
    return () => obs.disconnect();
  }, [iframeRef]);

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden">
      <motion.iframe ref={iframeRef} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}
        className="border-none" style={{ background: "#fff" }} />
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   CodePanel — code view + preview + version switcher
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function CodePanel({ code, html, rightPanel, setRightPanel, fileName, sessionId, expanded, onToggleExpand, currentVersion }: {
  code: string; html: string | null;
  rightPanel: "code" | "preview"; setRightPanel: (v: "code" | "preview") => void;
  fileName: string; sessionId: string;
  expanded?: boolean; onToggleExpand?: () => void;
  currentVersion?: number;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const codeEndRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const [versions, setVersions] = useState<{ version: number; files: string[] }[]>([]);
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [versionCode, setVersionCode] = useState("");

  const displayCode = viewingVersion ? versionCode : code;
  const lines = displayCode ? displayCode.split("\n") : [];
  const hasPreview = !!html;

  useEffect(() => {
    if (!sessionId) return;
    fetch(`/api/versions/${sessionId}`).then(r => r.json()).then(d => setVersions(d.versions || [])).catch(() => {});
  }, [sessionId, currentVersion]);

  useEffect(() => {
    if (!userScrolledRef.current && rightPanel === "code") codeEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [code, rightPanel]);

  useEffect(() => {
    if (rightPanel === "preview" && html && iframeRef.current) {
      const sid = sessionId.slice(0, 16);
      if (!sid) { iframeRef.current.srcdoc = html; return; }
      fetch(`/preview/${sid}/`, { method: "HEAD" }).then(r => {
        if (r.ok && iframeRef.current) iframeRef.current.src = `/preview/${sid}/`;
        else if (iframeRef.current) iframeRef.current.srcdoc = html!;
      }).catch(() => { if (iframeRef.current) iframeRef.current.srcdoc = html!; });
    }
  }, [rightPanel, html, sessionId]);

  function loadVersion(v: number) {
    if (v === currentVersion || v === 0) { setViewingVersion(null); setVersionCode(""); return; }
    setViewingVersion(v);
    fetch(`/api/versions/${sessionId}/${v}`).then(r => r.json()).then(d => {
      setVersionCode(Object.values(d.files || {}).join("\n\n") as string);
    }).catch(() => {});
  }

  function onCodeScroll(e: React.UIEvent) {
    const el = e.currentTarget;
    userScrolledRef.current = el.scrollHeight - el.scrollTop - el.clientHeight > 40;
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0" style={{ background: "var(--surface-0)" }}>
      {/* Tab bar */}
      <div className="flex items-center shrink-0" style={{ height: 38, padding: "0 16px", borderBottom: "1px solid var(--border-0)", background: hasPreview ? "var(--surface-0)" : "var(--surface-1)" }}>
        {!hasPreview ? (
          <>
            {code && <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)", marginRight: 10, animation: "e-pulse 2s ease-in-out infinite", boxShadow: "0 0 6px var(--amber-dim)" }} />}
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 12, color: "var(--text-1)", fontWeight: 500 }}>{fileName || "..."}</span>
            {versions.length > 1 && (
              <div className="flex items-center gap-1 ml-3">
                {versions.map(v => (
                  <button key={v.version} onClick={() => loadVersion(v.version)}
                    style={{ padding: "1px 6px", fontSize: 10, borderRadius: 3, border: "1px solid var(--border-0)", cursor: "pointer", fontFamily: "'Geist Mono', monospace",
                      background: (viewingVersion === v.version || (!viewingVersion && v.version === currentVersion)) ? "var(--amber-dim)" : "var(--surface-2)",
                      color: (viewingVersion === v.version || (!viewingVersion && v.version === currentVersion)) ? "var(--amber)" : "var(--text-3)" }}>
                    v{v.version}
                  </button>
                ))}
              </div>
            )}
            <span style={{ flex: 1 }} />
            {code && <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)", background: "var(--surface-2)", padding: "2px 6px", borderRadius: 4 }}>{(code.length / 1024).toFixed(1)} KB</span>}
            {onToggleExpand && <button onClick={onToggleExpand} style={{ marginLeft: 8, padding: "4px 6px", border: "none", background: "var(--surface-2)", borderRadius: 4, cursor: "pointer", color: "var(--text-2)", fontSize: 12 }}>{expanded ? "◁" : "▷"}</button>}
          </>
        ) : (
          <>
            {(["code", "preview"] as const).map(tab => (
              <button key={tab} onClick={() => setRightPanel(tab)} className="relative transition-colors" style={{ padding: "10px 16px", fontSize: 12, fontWeight: 500, color: rightPanel === tab ? "var(--text-0)" : "var(--text-3)", border: "none", background: "none", cursor: "pointer" }}>
                {tab === "code" ? "Code" : "Preview"}
                {rightPanel === tab && <div className="absolute bottom-0 left-[16px] right-[16px]" style={{ height: 2, background: "var(--amber)", borderRadius: 1 }} />}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)", background: "var(--surface-2)", padding: "2px 8px", borderRadius: 4 }}>{fileName}</span>
            {onToggleExpand && <button onClick={onToggleExpand} style={{ marginLeft: 8, padding: "4px 6px", border: "none", background: "var(--surface-2)", borderRadius: 4, cursor: "pointer", color: "var(--text-2)", fontSize: 12 }}>{expanded ? "◁" : "▷"}</button>}
          </>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 relative min-h-0">
        {rightPanel === "code" && (
          <div className="absolute inset-0 overflow-y-auto" onScroll={onCodeScroll} style={{ padding: "12px 0" }}>
            {lines.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-5 px-8">
                <Sigil size={48} />
                <div style={{ fontSize: 14, color: "var(--text-3)" }}>等待代码...</div>
              </div>
            ) : (
              lines.map((line, i) => (
                <div key={i} className="flex hover:bg-[var(--surface-1)] transition-colors duration-100" style={{ padding: "0 16px" }}>
                  <span style={{ width: 40, flexShrink: 0, textAlign: "right", paddingRight: 16, color: "var(--text-3)", fontSize: 11, userSelect: "none", fontFamily: "'Geist Mono', monospace", lineHeight: "1.7", borderRight: "1px solid var(--border-0)" }}>{i + 1}</span>
                  <span style={{ flex: 1, whiteSpace: "pre", fontFamily: "'Geist Mono', monospace", fontSize: 12.5, lineHeight: "1.7", color: "var(--text-1)", paddingLeft: 14 }}
                    dangerouslySetInnerHTML={{ __html: highlightLine(line) }} />
                </div>
              ))
            )}
            <div ref={codeEndRef} />
          </div>
        )}
        {rightPanel === "preview" && html && <PreviewFrame iframeRef={iframeRef} />}
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   CompleteBar — bottom action bar on completion
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function CompleteBar({ fileName, size, elapsed, code, isHtml, sessionId }: {
  fileName: string; size: string; elapsed: number; code: string; isHtml: boolean; sessionId: string;
}) {
  function copyCode() { navigator.clipboard.writeText(code); toast("已复制", "success"); }
  function downloadFile() {
    const blob = new Blob([code], { type: isHtml ? "text/html" : "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = fileName; a.click(); URL.revokeObjectURL(url);
  }
  function downloadZip() { window.open(`http://${API_HOST}/api/download/${sessionId}`, "_blank"); }
  function openNew() {
    if (isHtml) { const w = window.open("", "_blank"); if (w) { w.document.write(code); w.document.close(); } }
  }

  return (
    <div className="shrink-0 flex items-center gap-3" style={{ padding: "10px 16px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <div style={{ width: 24, height: 24, borderRadius: "50%", background: "var(--pass-dim)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--pass)" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12" /></svg>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-0)", fontFamily: "'Geist Mono', monospace" }}>{fileName}</div>
        <div style={{ fontSize: 10, color: "var(--text-3)" }}>{size} · {elapsed}s · ✓ 验证通过</div>
      </div>
      <button onClick={copyCode} className="px-3 py-1.5 rounded-lg text-[11px] transition-colors hover:bg-[var(--surface-2)]" style={{ border: "1px solid var(--border-0)", color: "var(--text-2)" }}>复制</button>
      <button onClick={downloadFile} className="px-3 py-1.5 rounded-lg text-[11px] transition-colors hover:bg-[var(--surface-2)]" style={{ border: "1px solid var(--border-0)", color: "var(--text-2)" }}>下载</button>
      <button onClick={downloadZip} className="px-3 py-1.5 rounded-lg text-[11px] transition-colors hover:bg-[var(--surface-2)]" style={{ border: "1px solid var(--border-0)", color: "var(--text-2)" }}>Zip</button>
      {isHtml && <button onClick={openNew} className="px-3 py-1.5 rounded-lg text-[11px] font-medium" style={{ background: "var(--amber)", color: "#000", border: "none", cursor: "pointer" }}>新窗口打开</button>}
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   GlobalInput — always visible input field
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function GlobalInput({ onSend, isBuilding, onStop, files, onFileSelect, onRemoveFile, uploading, fileInputRef }: {
  onSend: (t: string) => void; isBuilding: boolean; onStop?: () => void;
  files: UploadedFile[]; onFileSelect: (f: FileList) => void; onRemoveFile: (id: string) => void;
  uploading: boolean; fileInputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const [text, setText] = useState("");
  const compRef = useRef(false);
  const { t } = useLocale();

  function submit() {
    if (!text.trim() && files.length === 0) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <div className="shrink-0" style={{ padding: "12px 20px 16px", background: "linear-gradient(transparent, var(--void) 8px)" }}>
      {files.length > 0 && <FileChips files={files} onRemove={onRemoveFile} />}
      <div className="max-w-[680px] mx-auto relative">
        <textarea placeholder={isBuilding ? "构建中..." : "描述你想做的东西..."} rows={1}
          value={text} onChange={e => setText(e.target.value)}
          onCompositionStart={() => { compRef.current = true; }} onCompositionEnd={() => { compRef.current = false; }}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !compRef.current) { e.preventDefault(); submit(); } }}
          className="educe-input" style={{ opacity: 1, paddingLeft: 48 }} />
        <button onClick={() => fileInputRef.current?.click()}
          className="absolute left-[10px] bottom-[10px] w-[36px] h-[36px] rounded-[10px] flex items-center justify-center transition-all hover:bg-[var(--surface-2)]"
          style={{ color: "var(--text-3)", border: "none", background: "none", cursor: "pointer" }} title="上传文件">
          <Paperclip size={15} />
        </button>
        {isBuilding ? (
          <button onClick={onStop} className="absolute right-[8px] bottom-[9px]" style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: "var(--fail-dim)", color: "var(--fail)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: "currentColor" }} />
          </button>
        ) : (
          <button onClick={submit} disabled={!text.trim() && files.length === 0}
            className="absolute right-[8px] bottom-[9px] transition-all duration-200"
            style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: text.trim() ? "var(--amber)" : "var(--surface-2)", color: text.trim() ? "#000" : "var(--text-3)", display: "flex", alignItems: "center", justifyContent: "center", cursor: text.trim() ? "pointer" : "default", opacity: text.trim() ? 1 : 0.5 }}>
            <Send size={15} />
          </button>
        )}
        <input ref={fileInputRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={e => { if (e.target.files) onFileSelect(e.target.files); e.target.value = ""; }} />
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   DecisionCard (inline) — for decision_request
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function InlineDecision({ decisions, onSubmit }: { decisions: { question: string; options: string[] }[]; onSubmit: (choices: { question: string; choice: string }[]) => void }) {
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [note, setNote] = useState("");
  const allSelected = Object.keys(selections).length === decisions.length;
  function submit() {
    onSubmit(decisions.map((d, i) => ({ question: d.question, choice: d.options[selections[i] ?? 0] + (note ? ` (补充: ${note})` : "") })));
  }
  return (
    <div className="mb-4 rounded-2xl p-4" style={{ background: "var(--surface-1)", border: "1px solid var(--border-1)" }}>
      <div className="text-sm font-medium mb-3" style={{ color: "var(--text-0)" }}>先确认一下</div>
      {decisions.map((d, di) => (
        <div key={di} className="mb-3">
          <div className="text-[13px] mb-1.5" style={{ color: "var(--text-2)" }}>{d.question}</div>
          <div className="flex flex-wrap gap-1.5">
            {d.options.map((opt, oi) => (
              <button key={oi} onClick={() => setSelections(p => ({ ...p, [di]: oi }))}
                className="text-[12px] px-3 py-1.5 rounded-lg border transition-all"
                style={{ background: selections[di] === oi ? "var(--amber-dim)" : "var(--surface-0)", borderColor: selections[di] === oi ? "var(--amber)" : "var(--border-0)", color: selections[di] === oi ? "var(--amber)" : "var(--text-2)" }}>
                {opt}
              </button>
            ))}
          </div>
        </div>
      ))}
      <input type="text" value={note} onChange={e => setNote(e.target.value)} placeholder="补充你的想法（可选）"
        className="w-full text-[12px] px-3 py-2 rounded-lg outline-none mb-2" style={{ background: "var(--surface-0)", border: "1px solid var(--border-1)", color: "var(--text-1)" }} />
      <div className="flex items-center gap-2">
        <button onClick={submit} disabled={!allSelected} className="text-[13px] px-4 py-1.5 rounded-lg font-medium" style={{ background: allSelected ? "var(--amber)" : "var(--surface-2)", color: allSelected ? "#000" : "var(--text-3)", opacity: allSelected ? 1 : 0.6, border: "none", cursor: allSelected ? "pointer" : "default" }}>确认开始</button>
        <button onClick={() => onSubmit([])} className="text-[12px] px-3 py-1.5" style={{ color: "var(--text-3)", border: "none", background: "none", cursor: "pointer" }}>跳过，直接做</button>
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   EmptyState — idle view with sigil and starters
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function EmptyState({ onSend }: { onSend: (t: string) => void }) {
  const { t } = useLocale();
  const starters = [
    { key: "starter.pomodoro" as const, prompt: "做一个番茄钟" },
    { key: "starter.json" as const, prompt: "做一个JSON工具" },
    { key: "starter.game" as const, prompt: "做一个小游戏" },
    { key: "starter.dashboard" as const, prompt: "做一个数据看板" },
  ];
  return (
    <div className="flex-1 flex flex-col items-center relative overflow-hidden" style={{ justifyContent: "center", paddingBottom: "12%" }}>
      <div className="absolute pointer-events-none" style={{ top: "25%", left: "50%", transform: "translate(-50%,-50%)", width: 700, height: 500, background: "radial-gradient(ellipse at center, rgba(212,148,76,0.08) 0%, rgba(212,148,76,0.03) 35%, transparent 65%)" }} />
      <motion.div initial={{ opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1, ease: EASE }} className="relative z-10">
        <Sigil size={96} />
      </motion.div>
      <motion.h1 initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.2, ease: EASE }}
        className="mt-14 mb-4 text-center z-10" style={{ fontFamily: "'Instrument Serif', Georgia, serif", fontSize: 36, color: "var(--text-0)", letterSpacing: "-0.015em" }}>
        {t("empty.title")}
      </motion.h1>
      <motion.p initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.3, ease: EASE }}
        className="mb-10 text-center z-10" style={{ fontSize: 15, color: "var(--text-3)", lineHeight: 1.6, maxWidth: 420 }}>
        {t("empty.sub")}
      </motion.p>
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.4, ease: EASE }}
        className="flex flex-wrap gap-2 justify-center px-6 max-w-[540px] z-10">
        {starters.map(s => <button key={s.key} onClick={() => onSend(s.prompt)} className="starter-pill">{t(s.key)}</button>)}
      </motion.div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Page — main component (useReducer driven)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
export default function Page() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const sidRef = useRef("");
  const sidebarRef = useRef<SidebarRef>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useLocale();

  // Derived
  const showArtifact = hasArtifact(state);
  const active = isActive(state);
  const showTranscript = hasBuildTranscript(state);
  const { session, stream, pending, ui, upload } = state;
  const isBuilding = session.phase === "building";
  const isComplete = session.phase === "complete";

  // Timer effects
  useEffect(() => {
    if (!stream.thinking) return;
    const id = setInterval(() => dispatch({ type: "TICK_THINKING" }), 1000);
    return () => clearInterval(id);
  }, [stream.thinking]);

  useEffect(() => {
    if (!isBuilding) return;
    const id = setInterval(() => dispatch({ type: "TICK_ELAPSED" }), 1000);
    return () => clearInterval(id);
  }, [isBuilding]);

  // Auto-extract HTML on completion
  useEffect(() => {
    if (isComplete && stream.code && !stream.html) {
      const h = extractHtml(stream.code);
      if (h) dispatch({ type: "STREAM_HTML", html: h });
    }
  }, [isComplete, stream.code, stream.html]);

  // Auto-scroll chat
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [session.turns.length]);

  // WebSocket setup
  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    sidRef.current = sid;
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      dispatch({ type: "SET_UI", key: "connected", value: true });
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => dispatch({ type: "SET_UI", key: "model", value: d.model || "" })).catch(() => {});
    });
    ws.onDisconnect(() => dispatch({ type: "SET_UI", key: "connected", value: false }));

    ws.onMessage((msg: ServerMessage) => {
      const actions = mapWsMessage(msg);
      if (!actions) return;
      if (Array.isArray(actions)) { actions.forEach(a => dispatch(a)); }
      else { dispatch(actions); }
    });

    return () => { ws.close(); };
  }, []);

  // ── Actions ──

  function send(text: string) {
    if (!text && upload.files.length === 0) return;
    dispatch({ type: "USER_SEND", text });
    const fileIds = upload.files.map(f => f.id);
    wsRef.current?.send(text, fileIds.length > 0 ? fileIds : undefined);
    dispatch({ type: "SET_UPLOAD", files: [] });
  }

  function handleDecision(choices: { question: string; choice: string }[]) {
    wsRef.current?.sendRaw({ type: "decision_response", decisions: choices });
    dispatch({ type: "DECISION_SUBMITTED" });
  }

  function handlePlanSelect(planId: number, userNote: string) {
    wsRef.current?.sendRaw({ type: "plan_select", plan_id: planId, user_note: userNote });
    dispatch({ type: "PLAN_SELECTED" });
  }

  function reset() {
    const newSid = sidRef.current; // keep same WS connection
    wsRef.current?.sendRaw({ type: "reset_context" });
    dispatch({ type: "RESET", sessionId: newSid });
    sidebarRef.current?.refresh();
  }

  function handleTaskSelect(task: any) {
    wsRef.current?.sendRaw({ type: "switch_session", session_id: task.id });
    // Load full task data from API
    fetch(`http://${API_HOST}/api/tasks/${task.id}`).then(r => r.json()).then(data => {
      if (data.turns || data.transcript) {
        dispatch({ type: "SWITCH_SESSION", payload: data });
        // If there's code, try to extract and show it
        for (const turn of (data.turns || []).reverse()) {
          if (turn.response && turn.type === "code") {
            const h = extractHtml(turn.response);
            if (h) { dispatch({ type: "STREAM_HTML", html: h }); }
            const codeMatch = turn.response.match(/```filepath:([^\n]+)\n([\s\S]*)/);
            if (codeMatch) {
              dispatch({ type: "STREAM_CODE_UPDATE", code: codeMatch[2].replace(/\n```\s*$/, "") });
              dispatch({ type: "FILE_WRITTEN", fileName: codeMatch[1].trim(), size: 0 });
            }
            break;
          }
        }
      }
    }).catch(() => {});
  }

  function stopBuild() {
    wsRef.current?.close();
    dispatch({ type: "ERROR", message: "已停止" });
  }

  async function handleFileSelect(selectedFiles: FileList) {
    if (!selectedFiles.length) return;
    dispatch({ type: "SET_UPLOAD", uploading: true });
    const newFiles: UploadedFile[] = [];
    for (let i = 0; i < Math.min(selectedFiles.length, 5); i++) {
      const file = selectedFiles[i];
      const formData = new FormData(); formData.append("file", file);
      try {
        const r = await fetch(`http://${API_HOST}/api/upload/${sidRef.current}`, { method: "POST", body: formData });
        const data = await r.json();
        if (data.file_id) newFiles.push({ id: data.file_id, name: file.name, size: file.size, mime_type: file.type, is_image: file.type.startsWith("image/"), preview_url: data.preview_url });
      } catch {}
    }
    dispatch({ type: "SET_UPLOAD", files: [...upload.files, ...newFiles], uploading: false });
  }

  function fmtTime(ts: number) { return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }

  // ── Render ──

  return (
    <div className="h-screen flex" style={{ background: "var(--void)" }}>
      <Sidebar ref={sidebarRef} collapsed={ui.sidebarCollapsed} onCollapse={() => dispatch({ type: "SET_UI", key: "sidebarCollapsed", value: !ui.sidebarCollapsed })}
        activeSessionId={sidRef.current} onNewTask={reset} onOpenSettings={() => dispatch({ type: "SET_UI", key: "showSettings", value: true })}
        onTaskSelect={handleTaskSelect} />

      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Connection indicator */}
        <div className="absolute top-3 right-4 z-30">
          <button onClick={() => dispatch({ type: "SET_UI", key: "showSettings", value: true })} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full transition-colors hover:bg-[var(--surface-2)]" style={{ background: "var(--surface-1)", border: "1px solid var(--border-0)", cursor: "pointer" }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: ui.connected ? "var(--pass)" : "var(--fail)" }} />
            <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>{ui.model || "..."}</span>
          </button>
        </div>

        {/* Main content area */}
        <div className="flex-1 flex flex-col min-h-0">
          {!active ? (
            /* ── Idle View ── */
            <EmptyState onSend={send} />
          ) : (
            /* ── Session View ── */
            <motion.div key="session" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 flex flex-col min-h-0">
              {showArtifact && <BriefBar text={session.userRequest} elapsed={stream.buildElapsed} />}
              <div className="flex flex-1 min-h-0">
                {/* Chat panel */}
                {!(showArtifact && ui.artifactExpanded) && (
                  <div className="flex flex-col min-h-0 overflow-hidden" style={showArtifact ? { width: `${ui.splitPercent}%`, minWidth: 300, flex: "none", background: "var(--void)" } : { flex: 1, background: "var(--void)" }}>
                    <div className="flex-1 overflow-y-auto" style={{ padding: showArtifact ? "16px 18px 120px" : "24px 28px 120px" }}>
                      <div style={{ maxWidth: showArtifact ? "100%" : "760px", margin: showArtifact ? undefined : "0 auto" }}>
                        {/* Messages */}
                        {session.turns.map((turn, i) => (
                          <div key={i} className={`mb-4 ${turn.role === "user" ? "flex justify-end" : ""}`}>
                            {turn.role === "user" ? (
                              <div className="user-bubble">{turn.content}</div>
                            ) : (
                              <MessageBubble text={turn.content} timestamp={turn.timestamp} fmtTime={fmtTime} onFeedback={() => {}} />
                            )}
                          </div>
                        ))}

                        {/* Transcript timeline */}
                        {showTranscript && <TranscriptTimeline entries={session.transcript} isBuilding={isBuilding} />}

                        {/* Thinking indicator */}
                        {stream.thinking && (
                          <div className="flex items-center gap-3 mb-4 py-3">
                            <div className="flex gap-1">
                              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 1.5s ease-in-out infinite" }} />
                              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 1.5s ease-in-out 0.2s infinite" }} />
                              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 1.5s ease-in-out 0.4s infinite" }} />
                            </div>
                            <span style={{ fontSize: 12, color: "var(--text-3)" }}>
                              {session.expertName || "思考中"} · {stream.thinkingElapsed}s
                            </span>
                          </div>
                        )}

                        {/* Pending decisions */}
                        {pending.decisions && <InlineDecision decisions={pending.decisions} onSubmit={handleDecision} />}

                        {/* Pending plans */}
                        {pending.plans && <PlanProposal plans={pending.plans} onSelect={handlePlanSelect} originalRequest={pending.planRequest} />}

                        <div ref={chatEndRef} />
                      </div>
                    </div>

                    {/* Input */}
                    <GlobalInput onSend={send} isBuilding={isBuilding} onStop={stopBuild} files={upload.files} onFileSelect={handleFileSelect} onRemoveFile={id => dispatch({ type: "SET_UPLOAD", files: upload.files.filter(f => f.id !== id) })} uploading={upload.uploading} fileInputRef={fileInputRef} />
                  </div>
                )}

                {/* Draggable divider */}
                {showArtifact && !ui.artifactExpanded && (
                  <div style={{ width: 5, cursor: "col-resize", background: "var(--border-0)", transition: "background 0.2s" }}
                    onMouseDown={e => {
                      e.preventDefault();
                      const startX = e.clientX;
                      const startPct = ui.splitPercent;
                      const container = (e.target as HTMLElement).parentElement!;
                      const move = (ev: MouseEvent) => {
                        const dx = ev.clientX - startX;
                        const newPct = Math.max(25, Math.min(75, startPct + (dx / container.clientWidth) * 100));
                        dispatch({ type: "SET_UI", key: "splitPercent", value: newPct });
                      };
                      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
                      document.addEventListener("mousemove", move);
                      document.addEventListener("mouseup", up);
                    }} />
                )}

                {/* Artifact panel */}
                {showArtifact && (
                  <div className="flex flex-col min-h-0" style={ui.artifactExpanded ? { flex: 1 } : { width: `${100 - ui.splitPercent}%` }}>
                    <CodePanel code={stream.code} html={stream.html} rightPanel={ui.rightPanel} setRightPanel={v => dispatch({ type: "SET_UI", key: "rightPanel", value: v })} fileName={stream.fileName} sessionId={sidRef.current} expanded={ui.artifactExpanded} onToggleExpand={() => dispatch({ type: "SET_UI", key: "artifactExpanded", value: !ui.artifactExpanded })} currentVersion={session.currentVersion} />
                    {isComplete && (stream.html || stream.code) && (
                      <CompleteBar fileName={stream.fileName || "output.html"} size={`${(stream.fileSize / 1024 || stream.code.length / 1024).toFixed(1)} KB`} elapsed={stream.buildElapsed} code={stream.html || stream.code} isHtml={!!stream.html} sessionId={sidRef.current} />
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {/* Input at bottom when no artifact */}
          {active && !showArtifact && (
            <GlobalInput onSend={send} isBuilding={isBuilding} onStop={stopBuild} files={upload.files} onFileSelect={handleFileSelect} onRemoveFile={id => dispatch({ type: "SET_UPLOAD", files: upload.files.filter(f => f.id !== id) })} uploading={upload.uploading} fileInputRef={fileInputRef} />
          )}

          {/* Input at bottom when idle */}
          {!active && (
            <GlobalInput onSend={send} isBuilding={false} files={upload.files} onFileSelect={handleFileSelect} onRemoveFile={id => dispatch({ type: "SET_UPLOAD", files: upload.files.filter(f => f.id !== id) })} uploading={upload.uploading} fileInputRef={fileInputRef} />
          )}
        </div>
      </div>

      {/* Settings modal */}
      <AnimatePresence>
        {ui.showSettings && <SettingsModal open={true} onClose={() => dispatch({ type: "SET_UI", key: "showSettings", value: false })} model={ui.model} onModelChange={m => dispatch({ type: "SET_UI", key: "model", value: m })} />}
      </AnimatePresence>

      <ToastContainer />
      <style>{`@keyframes e-pulse{0%,100%{opacity:1}50%{opacity:.3}}`}</style>
    </div>
  );
}
