"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Paperclip, ChevronRight, ArrowUpRight, Copy, Download, X } from "lucide-react";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { ToastContainer, toast } from "@/components/toast";
import { FileChips, type UploadedFile } from "@/components/file-chips";
import { MessageBubble } from "@/components/message-bubble";

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────
type AppPhase = "idle" | "thinking" | "deciding" | "building" | "complete";

interface ToolEvent {
  event: string; content?: string; file?: string; size?: number;
  command?: string; success?: boolean; output?: string; files?: string[]; turns?: number;
}
interface ChatMsg {
  id: string; role: "user" | "assistant" | "system" | "decision";
  text: string; html?: string; streamingCode?: string;
  toolEvents?: ToolEvent[]; timestamp: number; files?: UploadedFile[];
  decisions?: { question: string; options: string[] }[];
}

const ACCEPT = ".txt,.py,.js,.ts,.tsx,.jsx,.css,.html,.json,.md,.yaml,.yml,.xml,.csv,.sh,.sql,.go,.java,.c,.cpp,.h,.rb,.rs,.swift,.pdf,.xlsx,.xls,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg";

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
function extractHtml(c: string) {
  const m1 = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?<\/html>)/i);
  if (m1) return m1[1];
  const m2 = c.match(/```html\n([\s\S]*?<\/html>)/i);
  if (m2) return m2[1];
  const m3 = c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
  if (m3) return m3[1];
  return undefined;
}

function wrapPartialHtml(code: string): string {
  if (code.includes("<!DOCTYPE") || code.includes("<html")) return code;
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>*{margin:0;padding:0;box-sizing:border-box}body{background:#0a0a0c;color:#f0ede8;font-family:system-ui,sans-serif;padding:20px}</style></head><body>${code}</body></html>`;
}

// ─────────────────────────────────────────────────────────────
// SUB-COMPONENTS
// ─────────────────────────────────────────────────────────────

/* ═══════════ SIGIL ═══════════ */
function Sigil({ size = 88 }: { size?: number }) {
  return (
    <div style={{ width: size, height: size, position: "relative" }}>
      <svg viewBox="0 0 88 88" style={{ width: "100%", height: "100%" }}>
        <circle cx="44" cy="44" r="42" fill="none" stroke="var(--border-1)" strokeWidth="0.4" />
        <circle cx="44" cy="44" r="30" fill="none" stroke="var(--border-0)" strokeWidth="0.4" />
        <circle cx="44" cy="44" r="18" fill="none" stroke="var(--border-0)" strokeWidth="0.3" opacity="0.5" />
        {/* Orbiting arcs */}
        <circle cx="44" cy="44" r="42" fill="none" stroke="var(--amber)" strokeWidth="1.8"
          strokeLinecap="round" strokeDasharray="66 198"
          style={{ animation: "educe-spin 12s linear infinite", transformOrigin: "center" }} />
        <circle cx="44" cy="44" r="30" fill="none" stroke="var(--amber-bright)" strokeWidth="1"
          strokeLinecap="round" strokeDasharray="38 150"
          style={{ animation: "educe-spin-r 18s linear infinite", transformOrigin: "center" }} opacity="0.5" />
        <circle cx="44" cy="44" r="18" fill="none" stroke="var(--amber)" strokeWidth="0.6"
          strokeLinecap="round" strokeDasharray="20 94"
          style={{ animation: "educe-spin 8s linear infinite", transformOrigin: "center" }} opacity="0.3" />
        {/* Core */}
        <circle cx="44" cy="44" r="3.5" fill="var(--amber)" opacity="0.8" />
        <circle cx="44" cy="44" r="8" fill="var(--amber)" opacity="0.05"
          style={{ animation: "educe-breathe 4s ease-in-out infinite" }} />
      </svg>
      <style>{`
        @keyframes educe-spin { to { transform: rotate(360deg); } }
        @keyframes educe-spin-r { to { transform: rotate(-360deg); } }
        @keyframes educe-breathe { 0%,100% { opacity: 0.04; } 50% { opacity: 0.12; } }
      `}</style>
    </div>
  );
}

/* ═══════════ EMPTY STATE ═══════════ */
function EmptyState({ onSend }: { onSend: (text: string) => void }) {
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const composingRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const starters = [
    { label: "番茄钟", prompt: "做一个番茄钟" },
    { label: "JSON 工具", prompt: "做一个JSON工具" },
    { label: "小游戏", prompt: "做一个小游戏" },
    { label: "数据看板", prompt: "做一个数据看板" },
    { label: "编辑器", prompt: "做一个编辑器" },
  ];

  function handleSend() {
    const t = input.trim();
    if (!t) return;
    onSend(t);
    setInput("");
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center relative overflow-hidden" style={{ minHeight: "100%" }}>
      {/* Atmospheric glow */}
      <div className="absolute pointer-events-none" style={{
        top: "28%", left: "50%", transform: "translate(-50%, -50%)",
        width: 600, height: 400,
        background: "radial-gradient(ellipse, rgba(212,148,76,0.06) 0%, transparent 65%)",
      }} />

      {/* Staggered entrance */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10"
      >
        <Sigil size={88} />
      </motion.div>

      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
        className="mt-10 mb-3 text-center"
        style={{
          fontFamily: "'Instrument Serif', Georgia, serif",
          fontSize: "38px",
          color: "var(--text-0)",
          letterSpacing: "-0.01em",
          lineHeight: 1.1,
        }}
      >
        想做点什么？
      </motion.h1>

      <motion.p
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.25, ease: [0.16, 1, 0.3, 1] }}
        className="mb-12 text-center"
        style={{ fontSize: "15px", color: "var(--text-3)", lineHeight: 1.6 }}
      >
        一个游戏、一个工具、一个想法——都行。
      </motion.p>

      {/* Input */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-[560px] relative z-10 px-6"
      >
        <div className="relative group">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={e => { composingRef.current = false; setInput((e.target as HTMLTextAreaElement).value); }}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); handleSend(); } }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="描述你想做的东西..."
            rows={1}
            className="w-full resize-none outline-none transition-all duration-300"
            style={{
              background: "var(--surface-1)",
              border: `1px solid ${focused ? "var(--amber)" : "var(--border-1)"}`,
              borderRadius: "16px",
              padding: "18px 60px 18px 22px",
              fontSize: "15px",
              fontFamily: "inherit",
              color: "var(--text-0)",
              lineHeight: 1.5,
              minHeight: "58px",
              maxHeight: "140px",
              boxShadow: focused
                ? "0 0 0 3px var(--amber-dim), 0 12px 40px rgba(0,0,0,0.3)"
                : "0 4px 20px rgba(0,0,0,0.15)",
            }}
          />
          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="absolute right-3 bottom-3 transition-all duration-200"
            style={{
              width: 40, height: 40,
              borderRadius: "12px",
              border: "none",
              background: input.trim() ? "var(--amber)" : "var(--surface-2)",
              color: input.trim() ? "var(--void)" : "var(--text-3)",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: input.trim() ? "pointer" : "default",
              transform: input.trim() ? "scale(1)" : "scale(0.95)",
              opacity: input.trim() ? 1 : 0.6,
            }}
          >
            <Send size={16} />
          </button>
        </div>
      </motion.div>

      {/* Starters */}
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="flex flex-wrap gap-2.5 justify-center mt-7 px-6 max-w-[560px] z-10"
      >
        {starters.map((s, i) => (
          <motion.button
            key={s.label}
            onClick={() => onSend(s.prompt)}
            whileHover={{ scale: 1.04, borderColor: "var(--amber)" }}
            whileTap={{ scale: 0.97 }}
            className="transition-colors duration-200"
            style={{
              padding: "8px 18px",
              borderRadius: "100px",
              fontSize: "13px",
              fontFamily: "inherit",
              color: "var(--text-2)",
              background: "transparent",
              border: "1px solid var(--border-1)",
              cursor: "pointer",
            }}
            onMouseEnter={e => {
              (e.target as HTMLElement).style.color = "var(--text-0)";
              (e.target as HTMLElement).style.background = "var(--amber-glow)";
              (e.target as HTMLElement).style.borderColor = "var(--amber)";
              (e.target as HTMLElement).style.boxShadow = "0 0 20px var(--amber-dim)";
            }}
            onMouseLeave={e => {
              (e.target as HTMLElement).style.color = "var(--text-2)";
              (e.target as HTMLElement).style.background = "transparent";
              (e.target as HTMLElement).style.borderColor = "var(--border-1)";
              (e.target as HTMLElement).style.boxShadow = "none";
            }}
          >
            {s.label}
          </motion.button>
        ))}
      </motion.div>
    </div>
  );
}

/* ═══════════ BRIEF BAR ═══════════ */
function BriefBar({ text, elapsed }: { text: string; elapsed: number }) {
  return (
    <div className="flex items-center gap-3" style={{
      padding: "10px 20px",
      borderBottom: "1px solid var(--border-0)",
      background: "var(--surface-0)",
    }}>
      <span style={{
        fontSize: "9px", fontWeight: 600, textTransform: "uppercase" as const,
        letterSpacing: "0.8px", color: "var(--amber)",
        padding: "3px 8px", background: "var(--amber-dim)", borderRadius: "4px",
      }}>任务</span>
      <span style={{ fontSize: "13px", color: "var(--text-1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>{text}</span>
      <span style={{
        fontSize: "12px", color: "var(--amber)",
        fontFamily: "'Geist Mono', monospace", fontVariantNumeric: "tabular-nums",
        padding: "2px 8px", background: "var(--amber-subtle)", borderRadius: "4px",
      }}>{elapsed}s</span>
    </div>
  );
}

/* ═══════════ PROCESS STRIP ═══════════ */
function ProcessStrip({ step, toolEvents, expanded, onToggle }: {
  step: number; toolEvents: ToolEvent[]; expanded: boolean; onToggle: () => void;
}) {
  const steps = ["分析需求", "搭建结构", "填充细节", "测试修复", "完成"];

  return (
    <div style={{
      position: "absolute", bottom: 0, left: 0, right: 0,
      background: "linear-gradient(transparent, rgba(10,10,12,0.92) 30%, rgba(10,10,12,0.98))",
      padding: "48px 24px 16px",
      zIndex: 5,
    }}>
      {/* Step dots */}
      <div className="flex items-center gap-0 mb-2">
        {steps.map((name, i) => (
          <div key={i} className="flex items-center">
            {i > 0 && <div style={{ width: 16, height: 1, background: i <= step ? "var(--amber-dim)" : "var(--border-0)", margin: "0 2px" }} />}
            <div className="flex items-center gap-1.5">
              <div style={{
                width: 7, height: 7, borderRadius: "50%",
                background: i < step ? "var(--pass)" : i === step ? "var(--amber)" : "var(--border-2)",
                boxShadow: i === step ? "0 0 10px var(--amber-dim)" : "none",
                transition: "all 0.4s ease",
              }} />
              <span style={{
                fontSize: "11px",
                color: i === step ? "var(--text-0)" : i < step ? "var(--text-2)" : "var(--text-3)",
                transition: "color 0.3s",
              }}>{name}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Activity toggle */}
      {toolEvents.length > 0 && (
        <div>
          <button onClick={onToggle} className="flex items-center gap-1.5 py-1 transition-colors" style={{ color: "var(--text-3)", fontSize: "11px", border: "none", background: "none", cursor: "pointer", fontFamily: "inherit" }}>
            <ChevronRight size={10} style={{ transform: expanded ? "rotate(90deg)" : "none", transition: "transform 0.2s" }} />
            详细过程
          </button>
          <AnimatePresence>
            {expanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="max-h-[200px] overflow-y-auto pt-1.5 space-y-1">
                  {toolEvents.map((evt, i) => (
                    <div key={i} className="flex items-start gap-2 text-[11px]" style={{ color: "var(--text-2)" }}>
                      <span style={{
                        width: 5, height: 5, borderRadius: "50%", marginTop: 5, flexShrink: 0,
                        background: evt.event === "thinking" ? "var(--text-3)"
                          : evt.event === "write_file" ? "var(--amber)"
                          : evt.event === "run" ? "var(--sage)"
                          : evt.success === false ? "var(--fail)"
                          : evt.event === "done" ? "var(--pass)" : "var(--text-3)",
                      }} />
                      <span className="flex-1 leading-relaxed">
                        {evt.event === "thinking" && <span style={{ fontStyle: "italic", color: "var(--text-3)" }}>{evt.content?.slice(0, 80)}</span>}
                        {evt.event === "write_file" && <span>写入 <code style={{ fontFamily: "'Geist Mono'", fontSize: "10px", background: "var(--surface-3)", padding: "0 4px", borderRadius: "3px", color: "var(--text-0)" }}>{evt.file}</code> {evt.size && <span style={{ color: "var(--text-3)" }}>({(evt.size / 1024).toFixed(1)} KB)</span>}</span>}
                        {evt.event === "run" && <span>运行 <code style={{ fontFamily: "'Geist Mono'", fontSize: "10px", background: "var(--surface-3)", padding: "0 4px", borderRadius: "3px", color: "var(--text-0)" }}>{evt.command?.slice(0, 40)}</code></span>}
                        {evt.event === "run_result" && (evt.success
                          ? <span style={{ color: "var(--pass)" }}>✓ 通过</span>
                          : <span style={{ color: "var(--fail)" }}>✗ {evt.output?.slice(0, 60)}</span>
                        )}
                        {evt.event === "done" && <span style={{ color: "var(--pass)" }}>✓ 完成 · {evt.turns}轮</span>}
                      </span>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

/* ═══════════ DECISION OVERLAY ═══════════ */
function DecisionOverlay({ decisions, onSubmit }: {
  decisions: { question: string; options: string[] }[];
  onSubmit: (choices: { question: string; choice: string }[]) => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});

  function select(q: string, opt: string) {
    setChoices(prev => ({ ...prev, [q]: opt }));
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 z-20 flex items-center justify-center"
      style={{ background: "rgba(10,10,12,0.82)", backdropFilter: "blur(8px)" }}
    >
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8 }}
        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border-1)",
          borderRadius: "16px",
          padding: "28px 32px",
          maxWidth: 500, width: "90%",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        <h3 style={{ fontSize: "16px", fontWeight: 600, color: "var(--text-0)", marginBottom: "4px" }}>先确认一下</h3>
        <p style={{ fontSize: "13px", color: "var(--text-2)", marginBottom: "22px" }}>几个选择，结果会更好。</p>

        {decisions.map((d, di) => (
          <div key={di} style={{ marginBottom: "16px" }}>
            <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-1)", marginBottom: "8px", textTransform: "uppercase" as const, letterSpacing: "0.4px" }}>{d.question}</div>
            <div className="flex flex-wrap gap-1.5">
              {d.options.map(opt => (
                <button key={opt} onClick={() => select(d.question, opt)}
                  className="transition-all duration-150"
                  style={{
                    padding: "8px 16px", borderRadius: "8px",
                    fontSize: "12px", fontFamily: "inherit",
                    border: `1px solid ${choices[d.question] === opt ? "var(--amber)" : "var(--border-1)"}`,
                    background: choices[d.question] === opt ? "var(--amber-dim)" : "transparent",
                    color: choices[d.question] === opt ? "var(--amber)" : "var(--text-2)",
                    cursor: "pointer",
                  }}
                >{opt}</button>
              ))}
            </div>
          </div>
        ))}

        <div className="flex gap-2 mt-6">
          <button onClick={() => onSubmit(Object.entries(choices).map(([q, c]) => ({ question: q, choice: c })))}
            style={{
              padding: "9px 22px", borderRadius: "8px",
              fontSize: "13px", fontWeight: 600, border: "none",
              background: "var(--amber)", color: "var(--void)",
              cursor: "pointer", fontFamily: "inherit",
            }}>确认开始</button>
          <button onClick={() => onSubmit([])}
            style={{
              padding: "9px 16px", borderRadius: "8px",
              fontSize: "13px", border: "none",
              background: "transparent", color: "var(--text-3)",
              cursor: "pointer", fontFamily: "inherit",
            }}>跳过</button>
        </div>
      </motion.div>
    </motion.div>
  );
}

/* ═══════════ PREVIEW CANVAS ═══════════ */
function PreviewCanvas({ html, streamingCode }: { html: string | null; streamingCode: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const lastUpdateRef = useRef(0);

  useEffect(() => {
    if (html && iframeRef.current) {
      iframeRef.current.srcdoc = html;
      return;
    }
    if (streamingCode && iframeRef.current) {
      const now = Date.now();
      if (now - lastUpdateRef.current < 600) return;
      lastUpdateRef.current = now;
      iframeRef.current.srcdoc = wrapPartialHtml(streamingCode);
    }
  }, [html, streamingCode]);

  const hasContent = !!(html || streamingCode);

  return (
    <div className="relative flex-1" style={{ background: "var(--surface-0)" }}>
      {/* Skeleton */}
      <AnimatePresence>
        {!hasContent && (
          <motion.div
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
            className="absolute inset-0 flex flex-col items-center justify-center gap-5"
          >
            {[200, 300, 140, 100].map((w, i) => (
              <div key={i} style={{
                width: w, height: i === 1 ? 180 : 16,
                background: "var(--surface-2)",
                borderRadius: "8px",
                animation: `skeleton-pulse 2s ease-in-out ${i * 0.2}s infinite`,
              }} />
            ))}
            <style>{`@keyframes skeleton-pulse { 0%,100% { opacity: 0.3; } 50% { opacity: 0.7; } }`}</style>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Live preview iframe */}
      {hasContent && (
        <motion.iframe
          ref={iframeRef}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          sandbox="allow-scripts allow-same-origin"
          className="absolute inset-0 w-full h-full border-none"
          style={{ background: "#fff" }}
        />
      )}
    </div>
  );
}

/* ═══════════ COMPLETE BAR ═══════════ */
function CompleteBar({ fileName, size, rounds, elapsed, onCopy, onDownload, onOpen }: {
  fileName: string; size: string; rounds: number; elapsed: number;
  onCopy: () => void; onDownload: () => void; onOpen: () => void;
}) {
  return (
    <motion.div
      initial={{ y: 60, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="flex items-center gap-4"
      style={{ padding: "12px 20px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}
    >
      <div style={{ width: 28, height: 28, borderRadius: "8px", background: "var(--pass-dim)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--pass)", fontSize: "13px" }}>✓</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-0)", fontFamily: "'Geist Mono', monospace" }}>{fileName}</div>
        <div className="flex gap-3 mt-0.5" style={{ fontSize: "11px", color: "var(--text-3)" }}>
          <span>{size}</span><span>{rounds}轮</span><span>{elapsed}s</span><span style={{ color: "var(--pass)" }}>✓ 通过</span>
        </div>
      </div>
      <div className="flex gap-1.5">
        <button onClick={onCopy} className="transition-all hover:bg-[var(--surface-2)]" style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid var(--border-1)", background: "none", color: "var(--text-1)", fontSize: "11px", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontFamily: "inherit" }}><Copy size={11} />复制</button>
        <button onClick={onDownload} className="transition-all hover:bg-[var(--surface-2)]" style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid var(--border-1)", background: "none", color: "var(--text-1)", fontSize: "11px", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontFamily: "inherit" }}><Download size={11} />下载</button>
        <button onClick={onOpen} className="transition-all" style={{ padding: "6px 14px", borderRadius: "6px", border: "none", background: "var(--amber)", color: "var(--void)", fontSize: "11px", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontFamily: "inherit" }}><ArrowUpRight size={11} />新窗口</button>
      </div>
    </motion.div>
  );
}

/* ═══════════ CONVERSATION THREAD ═══════════ */
function ConversationThread({ msgs, thinking, thinkingElapsed, expertName, onFeedback, fmtTime }: {
  msgs: ChatMsg[]; thinking: boolean; thinkingElapsed: number; expertName: string;
  onFeedback: (signal: "up" | "down", id: string) => void; fmtTime: (ts: number) => string;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[680px] mx-auto px-6 py-8 space-y-5">
        {msgs.map(msg => (
          <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            {msg.role === "user" ? (
              <div className="flex justify-end">
                <div style={{ maxWidth: "75%", padding: "10px 18px", borderRadius: "18px 18px 4px 18px", background: "var(--amber)", color: "var(--void)", fontSize: "14px", lineHeight: 1.5 }}>{msg.text}</div>
              </div>
            ) : msg.role === "system" ? (
              <div style={{ padding: "10px 16px", borderRadius: "10px", background: "var(--fail-dim)", color: "var(--fail)", fontSize: "13px", border: "1px solid var(--fail-dim)" }}>{msg.text}</div>
            ) : (
              <MessageBubble text={msg.text} timestamp={msg.timestamp} fmtTime={fmtTime} onFeedback={(s) => onFeedback(s, msg.id)} />
            )}
          </motion.div>
        ))}
        {thinking && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2.5 py-2">
            <div className="flex gap-1">
              {[0, 1, 2].map(i => (
                <div key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--amber)", animation: `dot-bounce 1.4s ease-in-out ${i * 0.2}s infinite` }} />
              ))}
            </div>
            <span style={{ fontSize: "13px", color: "var(--text-2)" }}>
              {expertName || "思考中"}{thinkingElapsed > 0 ? ` · ${thinkingElapsed}s` : ""}
            </span>
            <style>{`@keyframes dot-bounce { 0%,80%,100% { transform: translateY(0); opacity: 0.4; } 40% { transform: translateY(-5px); opacity: 1; } }`}</style>
          </motion.div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────
export default function Page() {
  // State machine
  const [phase, setPhase] = useState<AppPhase>("idle");
  const [mode, setMode] = useState<"build" | "conversation">("build");
  const [brief, setBrief] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [streamingCode, setStreamingCode] = useState("");
  const [html, setHtml] = useState<string | null>(null);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [buildStep, setBuildStep] = useState(0);
  const [decisions, setDecisions] = useState<{ question: string; options: string[] }[] | null>(null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [expandedLog, setExpandedLog] = useState(false);

  // Connection
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [thinkingElapsed, setThinkingElapsed] = useState(0);
  const [expertName, setExpertName] = useState("");

  // File upload
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Refs
  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const sidRef = useRef("");
  const sidebarRef = useRef<SidebarRef>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thinkingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);
  const phaseRef = useRef<AppPhase>("idle");
  const lastFileRef = useRef("");
  const lastSizeRef = useRef(0);

  useEffect(() => { phaseRef.current = phase; }, [phase]);

  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 768) setSidebarCollapsed(true);
  }, []);

  // WebSocket setup
  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    sidRef.current = sid;
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      setConnected(true);
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => setModel(d.model || "")).catch(() => {});
    });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "status") {
        if (msg.content === "thinking") {
          setThinking(true); setThinkingElapsed(0); setExpertName("");
          const ts = Date.now();
          thinkingTimerRef.current = setInterval(() => setThinkingElapsed(Math.floor((Date.now() - ts) / 1000)), 1000);
        } else if (msg.content === "pipeline_start") {
          setThinking(false);
          if (thinkingTimerRef.current) { clearInterval(thinkingTimerRef.current); thinkingTimerRef.current = null; }
          if (phaseRef.current === "building") return;
          setPhase("building"); setMode("build");
          setBuildStep(0); setStreamingCode(""); setHtml(null); setToolEvents([]); setExpandedLog(false);
          startRef.current = Date.now(); setElapsed(0);
          timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
        } else if (msg.content === "idle") {
          setThinking(false);
          if (thinkingTimerRef.current) { clearInterval(thinkingTimerRef.current); thinkingTimerRef.current = null; }
          if (phaseRef.current === "building") {
            setPhase("complete"); setBuildStep(4);
          } else if (phaseRef.current === "thinking") {
            setPhase("idle");
          }
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
          sidebarRef.current?.refresh();
        }
      } else if (msg.type === "agent_message" && (msg as any).msg_type !== "handoff") {
        setThinking(false);
        if (phaseRef.current === "building" || phaseRef.current === "complete") {
          const h = extractHtml(msg.content);
          if (h) setHtml(h);
          const evtFiles = (msg as any).files;
          if (evtFiles && evtFiles.length > 0) {
            lastFileRef.current = evtFiles[0];
          }
        } else {
          setMode("conversation");
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.role === "assistant" && last.text) {
              return [...p.slice(0, -1), { ...last, text: msg.content }];
            }
            return [...p, { id: Date.now().toString(), role: "assistant", text: msg.content, timestamp: Date.now() }];
          });
          if (phaseRef.current === "thinking") setPhase("idle");
        }
      } else if (msg.type === "chunk") {
        if (phaseRef.current === "building") {
          setStreamingCode(prev => prev + msg.content);
        } else {
          setMode("conversation");
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.role === "assistant" && !last.html) {
              return [...p.slice(0, -1), { ...last, text: last.text + msg.content }];
            }
            return [...p, { id: Date.now().toString(), role: "assistant", text: msg.content, timestamp: Date.now() }];
          });
        }
      } else if ((msg as any).type === "tool_event") {
        const evt = msg as unknown as ToolEvent;
        setToolEvents(prev => [...prev, evt]);
        // Update build step based on event type
        if (evt.event === "thinking") setBuildStep(s => Math.max(s, 0));
        else if (evt.event === "write_file") { setBuildStep(s => Math.max(s, 1)); if (evt.file) lastFileRef.current = evt.file; if (evt.size) lastSizeRef.current = evt.size; }
        else if (evt.event === "run") setBuildStep(s => Math.max(s, 3));
        else if (evt.event === "done") setBuildStep(4);
      } else if ((msg as any).type === "build_progress") {
        setBuildStep(s => Math.min(s + 1, 3));
      } else if ((msg as any).type === "decision_request") {
        setThinking(false);
        if (thinkingTimerRef.current) { clearInterval(thinkingTimerRef.current); thinkingTimerRef.current = null; }
        setDecisions((msg as any).decisions);
        setPhase("deciding");
      } else if ((msg as any).type === "expert") {
        setExpertName((msg as any).content || "");
      } else if (msg.type === "error") {
        setPhase("idle");
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        toast(msg.content, "error");
      }
    });

    return () => ws.close();
  }, []);

  // Actions
  function send(text: string) {
    const t = text.trim();
    if (!t) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) { toast("未连接", "error"); return; }

    setBrief(t);
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: t, timestamp: Date.now() }]);
    setPhase("thinking");
    setMode("build");
    setHtml(null); setStreamingCode(""); setToolEvents([]); setBuildStep(0);

    const fileIds = files.map(f => f.id);
    w.send(t, fileIds.length > 0 ? fileIds : undefined);
    setFiles([]);
  }

  function handleDecisionSubmit(choices: { question: string; choice: string }[]) {
    const w = wsRef.current;
    if (w && w.readyState === 1) {
      w.sendRaw({ type: "decision_response", decisions: choices });
    }
    setDecisions(null);
    setPhase("thinking");
  }

  function handleCopy() {
    if (html) navigator.clipboard.writeText(html);
  }
  function handleDownload() {
    if (!html) return;
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = lastFileRef.current || "output.html"; a.click();
    URL.revokeObjectURL(url);
  }
  function handleOpen() {
    if (!html) return;
    const blob = new Blob([html], { type: "text/html" });
    window.open(URL.createObjectURL(blob), "_blank");
  }

  function fmtTime(ts: number) {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  function reset() {
    setPhase("idle"); setMode("build"); setBrief(""); setMsgs([]);
    setHtml(null); setStreamingCode(""); setToolEvents([]); setElapsed(0);
    setDecisions(null); setBuildStep(0); setFiles([]);
  }

  // Derived state
  const isCanvas = phase !== "idle" && mode === "build";
  const isConvo = mode === "conversation" && msgs.length > 0;
  const showComplete = phase === "complete" && mode === "build" && (html || streamingCode);

  return (
    <div className="h-screen flex" style={{ background: "var(--void)" }}>
      <Sidebar ref={sidebarRef} collapsed={sidebarCollapsed} onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        activeSessionId={sidRef.current}
        onNewTask={reset}
        onTaskSelect={(task: any) => {
          if (task.turns && Array.isArray(task.turns)) {
            const newMsgs: ChatMsg[] = [];
            for (const turn of task.turns) {
              newMsgs.push({ id: `${turn.timestamp}-q`, role: "user", text: turn.question, timestamp: (turn.timestamp || 0) * 1000 });
              if (turn.response) {
                const h = extractHtml(turn.response);
                if (h) { setHtml(h); setMode("build"); setPhase("complete"); setBrief(turn.question); }
                else { newMsgs.push({ id: `${turn.timestamp}-a`, role: "assistant", text: turn.response, timestamp: (turn.timestamp || 0) * 1000 + 1 }); setMode("conversation"); }
              }
            }
            setMsgs(newMsgs);
          } else {
            const h = task.response ? extractHtml(task.response) : null;
            if (h) { setHtml(h); setMode("build"); setPhase("complete"); setBrief(task.request || task.title || ""); }
            else if (task.response) {
              setMsgs([
                { id: task.id + "-q", role: "user", text: task.request || task.title || "", timestamp: task.created_at * 1000 },
                { id: task.id + "-a", role: "assistant", text: task.response, timestamp: task.created_at * 1000 + 1 },
              ]);
              setMode("conversation");
              setPhase("idle");
            }
          }
        }}
      />

      {/* Main canvas */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Connection indicator */}
        <div className="absolute top-3 right-4 z-30 flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ background: "var(--surface-2)", border: "1px solid var(--border-0)" }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: connected ? "var(--pass)" : "var(--fail)" }} />
            <span style={{ fontSize: "10px", color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>{model || "..."}</span>
          </div>
        </div>

        <AnimatePresence mode="wait">
          {/* IDLE — Empty state */}
          {phase === "idle" && !isConvo && (
            <motion.div key="empty" exit={{ opacity: 0, y: -30 }} transition={{ duration: 0.35 }} className="flex-1 flex flex-col">
              <EmptyState onSend={send} />
            </motion.div>
          )}

          {/* CONVERSATION */}
          {(phase === "idle" || phase === "thinking") && isConvo && (
            <motion.div key="convo" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex-1 flex flex-col">
              <ConversationThread msgs={msgs} thinking={thinking} thinkingElapsed={thinkingElapsed} expertName={expertName}
                onFeedback={(signal, id) => { wsRef.current?.sendRaw({ type: "feedback", signal, message_id: id }); }}
                fmtTime={fmtTime} />
              {/* Follow-up input */}
              <div style={{ padding: "12px 20px 16px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
                <FollowUpInput onSend={send} placeholder="继续追问..." />
              </div>
            </motion.div>
          )}

          {/* THINKING (for build, before pipeline_start) */}
          {phase === "thinking" && mode === "build" && !isConvo && (
            <motion.div key="thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex-1 flex flex-col items-center justify-center">
              <Sigil size={64} />
              <motion.p
                initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                transition={{ delay: 0.3 }}
                className="mt-6" style={{ fontSize: "14px", color: "var(--text-2)" }}>
                {expertName || "思考中"}{thinkingElapsed > 0 ? ` · ${thinkingElapsed}s` : "..."}
              </motion.p>
            </motion.div>
          )}

          {/* BUILD / DECIDING / COMPLETE */}
          {isCanvas && (phase === "building" || phase === "deciding" || phase === "complete") && (
            <motion.div key="canvas" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 flex flex-col min-h-0">
              <BriefBar text={brief} elapsed={elapsed} />

              <div className="flex-1 relative min-h-0">
                <PreviewCanvas html={html} streamingCode={streamingCode} />
                {phase !== "complete" && <ProcessStrip step={buildStep} toolEvents={toolEvents} expanded={expandedLog} onToggle={() => setExpandedLog(!expandedLog)} />}

                {/* Decision overlay */}
                <AnimatePresence>
                  {phase === "deciding" && decisions && (
                    <DecisionOverlay decisions={decisions} onSubmit={handleDecisionSubmit} />
                  )}
                </AnimatePresence>
              </div>

              {/* Complete bar */}
              {showComplete && (
                <CompleteBar
                  fileName={lastFileRef.current || "output.html"}
                  size={lastSizeRef.current ? `${(lastSizeRef.current / 1024).toFixed(1)} KB` : `${(streamingCode.length / 1024).toFixed(1)} KB`}
                  rounds={toolEvents.filter(e => e.event === "write_file").length || 1}
                  elapsed={elapsed}
                  onCopy={handleCopy} onDownload={handleDownload} onOpen={handleOpen}
                />
              )}

              {/* Follow-up */}
              {phase === "complete" && (
                <div style={{ padding: "10px 20px 14px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
                  <FollowUpInput onSend={send} placeholder="加功能、改bug、问问题..." />
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} model={model} onModelChange={setModel} />
      <ToastContainer />
    </div>
  );
}

/* ═══════════ FOLLOW-UP INPUT ═══════════ */
function FollowUpInput({ onSend, placeholder }: { onSend: (text: string) => void; placeholder: string }) {
  const [text, setText] = useState("");
  const composingRef = useRef(false);

  return (
    <div className="relative">
      <input
        type="text" value={text} onChange={e => setText(e.target.value)}
        onCompositionStart={() => { composingRef.current = true; }}
        onCompositionEnd={e => { composingRef.current = false; setText((e.target as HTMLInputElement).value); }}
        onKeyDown={e => { if (e.key === "Enter" && !composingRef.current && text.trim()) { e.preventDefault(); onSend(text.trim()); setText(""); } }}
        placeholder={placeholder}
        className="w-full outline-none transition-all duration-200 focus:border-[var(--amber)]"
        style={{
          background: "var(--surface-1)", border: "1px solid var(--border-1)",
          borderRadius: "10px", padding: "10px 42px 10px 14px",
          fontSize: "13px", fontFamily: "inherit", color: "var(--text-0)",
        }}
      />
      <button onClick={() => { if (text.trim()) { onSend(text.trim()); setText(""); } }}
        className="absolute right-2 top-1/2 -translate-y-1/2 transition-all"
        style={{
          width: 28, height: 28, borderRadius: "6px", border: "none",
          background: text.trim() ? "var(--amber)" : "var(--surface-2)",
          color: text.trim() ? "var(--void)" : "var(--text-3)",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: text.trim() ? "pointer" : "default",
        }}>
        <Send size={12} />
      </button>
    </div>
  );
}
