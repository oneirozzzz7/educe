"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Copy, Download, ArrowUpRight, ChevronRight } from "lucide-react";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/i18n";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { MessageBubble } from "@/components/message-bubble";
import { ToastContainer, toast } from "@/components/toast";

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Types
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
type AppPhase = "idle" | "active" | "complete";
type SubPhase = "thinking" | "deciding" | "building" | "done";

interface ToolEvent {
  event: string; content?: string; file?: string; size?: number;
  command?: string; success?: boolean; output?: string; files?: string[]; turns?: number;
}
interface ChatMsg {
  id: string; role: "user" | "assistant" | "system";
  text: string; timestamp: number;
}
interface UploadedFile {
  id: string; name: string; size: number; mime_type: string; is_image: boolean; error?: string;
}
interface Decision { question: string; options: string[]; }

const EASE = [0.16, 1, 0.3, 1] as const;

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
   Sigil
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function Sigil({ size = 88 }: { size?: number }) {
  return (
    <svg viewBox="0 0 88 88" style={{ width: size, height: size }}>
      <circle cx="44" cy="44" r="42" fill="none" stroke="var(--border-1)" strokeWidth="0.4" />
      <circle cx="44" cy="44" r="30" fill="none" stroke="var(--border-0)" strokeWidth="0.4" />
      <circle cx="44" cy="44" r="18" fill="none" stroke="var(--border-0)" strokeWidth="0.3" opacity="0.5" />
      <circle cx="44" cy="44" r="42" fill="none" stroke="var(--amber)" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="66 198" style={{ animation: "e-spin 12s linear infinite", transformOrigin: "center" }} />
      <circle cx="44" cy="44" r="30" fill="none" stroke="var(--amber-bright)" strokeWidth="1" strokeLinecap="round" strokeDasharray="38 150" opacity="0.5" style={{ animation: "e-spin-r 18s linear infinite", transformOrigin: "center" }} />
      <circle cx="44" cy="44" r="18" fill="none" stroke="var(--amber)" strokeWidth="0.6" strokeLinecap="round" strokeDasharray="20 94" opacity="0.3" style={{ animation: "e-spin 8s linear infinite", transformOrigin: "center" }} />
      <circle cx="44" cy="44" r="8" fill="var(--amber)" opacity="0.05" style={{ animation: "e-breathe 4s ease-in-out infinite" }} />
      <circle cx="44" cy="44" r="3.5" fill="var(--amber)" opacity="0.8" />
      <style>{`
        @keyframes e-spin{to{transform:rotate(360deg)}}
        @keyframes e-spin-r{to{transform:rotate(-360deg)}}
        @keyframes e-breathe{0%,100%{opacity:.04}50%{opacity:.12}}
      `}</style>
    </svg>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   EmptyState
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function EmptyState({ onSend }: { onSend: (t: string) => void }) {
  const [input, setInput] = useState("");
  const [focused, setFocused] = useState(false);
  const compRef = useRef(false);
  const { t } = useLocale();

  const starters: { key: Parameters<typeof t>[0]; prompt: string }[] = [
    { key: "starter.pomodoro", prompt: "做一个番茄钟" },
    { key: "starter.json", prompt: "做一个JSON工具" },
    { key: "starter.game", prompt: "做一个小游戏" },
    { key: "starter.dashboard", prompt: "做一个数据看板" },
    { key: "starter.editor", prompt: "做一个编辑器" },
  ];

  function submit() { const v = input.trim(); if (v) { onSend(v); setInput(""); } }

  return (
    <div className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
      {/* Glow */}
      <div className="absolute pointer-events-none" style={{ top: "28%", left: "50%", transform: "translate(-50%,-50%)", width: 600, height: 400, background: "radial-gradient(ellipse, rgba(212,148,76,0.06) 0%, transparent 65%)" }} />

      <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.8, ease: EASE }} className="relative z-10">
        <Sigil size={88} />
      </motion.div>

      <motion.h1 initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.15, ease: EASE }}
        className="mt-10 mb-3 text-center z-10" style={{ fontFamily: "'Instrument Serif', Georgia, serif", fontSize: 38, color: "var(--text-0)", letterSpacing: "-0.01em", lineHeight: 1.1 }}>
        {t("empty.title")}
      </motion.h1>

      <motion.p initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.25, ease: EASE }}
        className="mb-12 text-center z-10" style={{ fontSize: 15, color: "var(--text-3)", lineHeight: 1.6 }}>
        {t("empty.sub")}
      </motion.p>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.35, ease: EASE }}
        className="w-full max-w-[560px] relative z-10 px-6">
        <div className="relative">
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onCompositionStart={() => { compRef.current = true; }} onCompositionEnd={e => { compRef.current = false; setInput((e.target as HTMLTextAreaElement).value); }}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !compRef.current) { e.preventDefault(); submit(); } }}
            onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
            placeholder={t("empty.placeholder")} rows={1}
            className="w-full resize-none outline-none transition-all duration-300"
            style={{ background: "var(--surface-1)", border: `1px solid ${focused ? "var(--amber)" : "var(--border-1)"}`, borderRadius: 16, padding: "18px 60px 18px 22px", fontSize: 15, fontFamily: "inherit", color: "var(--text-0)", lineHeight: 1.5, minHeight: 58, maxHeight: 140, boxShadow: focused ? "0 0 0 3px var(--amber-dim), 0 12px 40px rgba(0,0,0,0.3)" : "0 4px 20px rgba(0,0,0,0.15)" }} />
          <button onClick={submit} disabled={!input.trim()} className="absolute right-[10px] bottom-[10px] transition-all duration-200"
            style={{ width: 40, height: 40, borderRadius: 12, border: "none", background: input.trim() ? "var(--amber)" : "var(--surface-2)", color: input.trim() ? "var(--void)" : "var(--text-3)", display: "flex", alignItems: "center", justifyContent: "center", cursor: input.trim() ? "pointer" : "default", opacity: input.trim() ? 1 : 0.6, transform: `scale(${input.trim() ? 1 : 0.95})` }}>
            <Send size={16} />
          </button>
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.5, ease: EASE }}
        className="flex flex-wrap gap-2.5 justify-center mt-7 px-6 max-w-[560px] z-10">
        {starters.map(s => (
          <button key={s.key} onClick={() => onSend(s.prompt)}
            className="transition-all duration-200 hover:scale-[1.04] active:scale-[0.97]"
            style={{ padding: "8px 18px", borderRadius: 100, fontSize: 13, fontFamily: "inherit", color: "var(--text-2)", background: "transparent", border: "1px solid var(--border-1)", cursor: "pointer" }}
            onMouseEnter={e => { const s = (e.currentTarget as HTMLElement).style; s.color = "var(--text-0)"; s.background = "var(--amber-glow)"; s.borderColor = "var(--amber)"; s.boxShadow = "0 0 20px var(--amber-dim)"; }}
            onMouseLeave={e => { const s = (e.currentTarget as HTMLElement).style; s.color = "var(--text-2)"; s.background = "transparent"; s.borderColor = "var(--border-1)"; s.boxShadow = "none"; }}>
            {t(s.key)}
          </button>
        ))}
      </motion.div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BriefBar
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function BriefBar({ text, elapsed }: { text: string; elapsed: number }) {
  const { t } = useLocale();
  return (
    <div className="flex items-center gap-3 shrink-0" style={{ height: 40, padding: "0 20px", borderBottom: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <span style={{ fontSize: 9, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.8px", color: "var(--amber)", padding: "3px 8px", background: "var(--amber-dim)", borderRadius: 4 }}>{t("brief.label")}</span>
      <span className="truncate" style={{ fontSize: 13, color: "var(--text-1)", flex: 1 }}>{text}</span>
      <span style={{ fontSize: 12, color: "var(--amber)", fontFamily: "'Geist Mono', monospace", fontVariantNumeric: "tabular-nums", padding: "2px 8px", background: "rgba(212,148,76,0.03)", borderRadius: 4 }}>{elapsed}s</span>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ProcessPanel (left)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function ProcessPanel({ toolEvents, subPhase, decisions, onDecision }: {
  toolEvents: ToolEvent[]; subPhase: SubPhase;
  decisions: Decision[] | null; onDecision: (choices: { question: string; choice: string }[]) => void;
}) {
  const { t } = useLocale();
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [toolEvents, subPhase]);

  const dotColor: Record<string, string> = {
    thinking: "var(--text-3)", write_file: "var(--amber)", write_file_result: "var(--amber)",
    run: "var(--sage)", run_result: "var(--sage)", done: "var(--pass)", read_file_result: "var(--text-3)",
  };

  return (
    <div className="flex flex-col min-h-0" style={{ width: "35%", minWidth: 280, maxWidth: 380, borderRight: "1px solid var(--border-0)" }}>
      {/* Header */}
      <div className="flex items-center gap-2 shrink-0" style={{ height: 36, padding: "0 18px", borderBottom: "1px solid var(--border-0)" }}>
        {subPhase !== "done" && <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 2s ease-in-out infinite" }} />}
        {subPhase === "done" && <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--pass)" }} />}
        <span style={{ fontSize: 11, fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-2)" }}>
          {subPhase === "done" ? t("process.done") : t("process.header")}
        </span>
        <style>{`@keyframes e-pulse{0%,100%{opacity:1}50%{opacity:.4}}`}</style>
      </div>

      {/* Activity list */}
      <div className="flex-1 overflow-y-auto" style={{ padding: "14px 16px" }}>
        {/* Thinking placeholder before first event */}
        {toolEvents.length === 0 && subPhase === "thinking" && (
          <div className="flex items-center gap-2.5">
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--text-3)", animation: "e-pulse 2s ease-in-out infinite" }} />
            <span style={{ fontSize: 13, color: "var(--text-2)" }}>{t("thinking")}...</span>
          </div>
        )}

        {toolEvents.map((evt, i) => (
          <motion.div key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }}
            className="flex gap-2.5" style={{ padding: "5px 0" }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: evt.event === "run_result" ? (evt.success ? "var(--pass)" : "var(--fail)") : (dotColor[evt.event] || "var(--text-3)"), marginTop: 6, flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              {evt.event === "thinking" && (
                <>
                  <div style={{ fontSize: 13, color: "var(--text-1)" }}>{t("process.analyzing")}</div>
                  {evt.content && <div className="truncate" style={{ fontSize: 12, color: "var(--text-3)", fontStyle: "italic", marginTop: 2, maxWidth: "100%" }}>{evt.content.slice(0, 80)}</div>}
                </>
              )}
              {evt.event === "write_file" && (
                <div style={{ fontSize: 13, color: "var(--text-1)" }}>
                  {t("log.write")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3, color: "var(--text-0)" }}>{evt.file}</code>
                  {evt.size ? <span style={{ fontSize: 11, color: "var(--text-3)", marginLeft: 6 }}>({(evt.size / 1024).toFixed(1)} KB)</span> : null}
                </div>
              )}
              {evt.event === "run" && (
                <div style={{ fontSize: 13, color: "var(--text-1)" }}>
                  {t("log.run")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3, color: "var(--text-0)" }}>{evt.command?.slice(0, 50)}</code>
                </div>
              )}
              {evt.event === "run_result" && (
                <div style={{ fontSize: 12, color: evt.success ? "var(--pass)" : "var(--fail)" }}>
                  {evt.success ? `✓ ${t("log.passed")}` : `✗ ${evt.output?.slice(0, 60)}`}
                </div>
              )}
              {evt.event === "done" && (
                <div style={{ fontSize: 13, color: "var(--pass)", fontWeight: 500 }}>
                  ✓ {t("log.done")} · {evt.turns} {t("complete.rounds")}
                </div>
              )}
            </div>
          </motion.div>
        ))}

        {/* Inline decision card */}
        <AnimatePresence>
          {subPhase === "deciding" && decisions && (
            <InlineDecision decisions={decisions} onSubmit={onDecision} />
          )}
        </AnimatePresence>
        <div ref={endRef} />
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   InlineDecision (inside ProcessPanel)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function InlineDecision({ decisions, onSubmit }: { decisions: Decision[]; onSubmit: (c: { question: string; choice: string }[]) => void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const { t } = useLocale();

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.3, ease: EASE }}
      style={{ margin: "10px 0", background: "var(--surface-1)", border: "1px solid var(--border-1)", borderRadius: 12, padding: "18px 20px" }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-0)", marginBottom: 3 }}>{t("decision.title")}</div>
      <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 16 }}>{t("decision.sub")}</div>
      {decisions.map((d, i) => (
        <div key={i} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-1)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.4px" }}>{d.question}</div>
          <div className="flex flex-wrap gap-1.5">
            {d.options.map(opt => (
              <button key={opt} onClick={() => setChoices(p => ({ ...p, [d.question]: opt }))}
                className="transition-all duration-150"
                style={{ padding: "7px 14px", borderRadius: 6, fontSize: 12, fontFamily: "inherit", border: `1px solid ${choices[d.question] === opt ? "var(--amber)" : "var(--border-1)"}`, background: choices[d.question] === opt ? "var(--amber-dim)" : "transparent", color: choices[d.question] === opt ? "var(--amber)" : "var(--text-2)", cursor: "pointer" }}>
                {opt}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="flex gap-2 mt-4">
        <button onClick={() => onSubmit(Object.entries(choices).map(([q, c]) => ({ question: q, choice: c })))}
          style={{ padding: "8px 20px", borderRadius: 6, fontSize: 13, fontWeight: 600, border: "none", background: "var(--amber)", color: "var(--void)", cursor: "pointer", fontFamily: "inherit" }}>
          {t("decision.confirm")}
        </button>
        <button onClick={() => onSubmit([])}
          style={{ padding: "8px 14px", borderRadius: 6, fontSize: 13, border: "none", background: "transparent", color: "var(--text-3)", cursor: "pointer", fontFamily: "inherit" }}>
          {t("decision.skip")}
        </button>
      </div>
    </motion.div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   CodePreviewPanel (right)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function CodePreviewPanel({ streamingCode, html, rightPanel, setRightPanel, fileName }: {
  streamingCode: string; html: string | null;
  rightPanel: "code" | "preview"; setRightPanel: (v: "code" | "preview") => void;
  fileName: string;
}) {
  const { t } = useLocale();
  const codeEndRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const lines = streamingCode ? streamingCode.split("\n") : [];

  useEffect(() => {
    if (!userScrolledRef.current && rightPanel === "code") {
      codeEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [streamingCode, rightPanel]);

  useEffect(() => {
    if (rightPanel === "preview" && html && iframeRef.current) {
      iframeRef.current.srcdoc = html;
    }
  }, [rightPanel, html]);

  const hasPreview = !!html;
  const showTabs = hasPreview;

  function onCodeScroll(e: React.UIEvent) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    userScrolledRef.current = !atBottom;
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0" style={{ background: "var(--surface-0)" }}>
      {/* Tab bar */}
      <div className="flex items-center shrink-0" style={{ height: 36, padding: "0 16px", borderBottom: "1px solid var(--border-0)", background: showTabs ? "var(--surface-0)" : "var(--surface-1)" }}>
        {!showTabs ? (
          <>
            {streamingCode && <div style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--amber)", marginRight: 8, animation: "e-pulse 2s ease-in-out infinite" }} />}
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 12, color: "var(--text-1)" }}>{fileName || "..."}</span>
            {streamingCode && <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)", marginLeft: "auto" }}>{(streamingCode.length / 1024).toFixed(1)} KB</span>}
          </>
        ) : (
          <>
            {(["code", "preview"] as const).map(tab => (
              <button key={tab} onClick={() => setRightPanel(tab)}
                className="relative transition-colors" style={{ padding: "10px 14px", fontSize: 12, fontWeight: 500, color: rightPanel === tab ? "var(--text-0)" : "var(--text-3)", border: "none", background: "none", cursor: "pointer", fontFamily: "inherit" }}>
                {tab === "code" ? "Code" : "Preview"}
                {rightPanel === tab && <div className="absolute bottom-0 left-[14px] right-[14px]" style={{ height: 1.5, background: "var(--amber)", borderRadius: 1 }} />}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)" }}>{fileName}</span>
          </>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 relative min-h-0">
        {/* Code view */}
        {rightPanel === "code" && (
          <div className="absolute inset-0 overflow-y-auto" onScroll={onCodeScroll} style={{ padding: "12px 0" }}>
            {lines.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-4">
                {[200, 300, 140].map((w, i) => (
                  <div key={i} style={{ width: w, height: i === 1 ? 160 : 14, background: "var(--surface-2)", borderRadius: 8, animation: `e-skel 2s ease-in-out ${i * 0.2}s infinite` }} />
                ))}
                <style>{`@keyframes e-skel{0%,100%{opacity:.3}50%{opacity:.7}}`}</style>
              </div>
            ) : (
              lines.map((line, i) => (
                <div key={i} className="flex hover:bg-[var(--surface-1)] transition-colors" style={{ padding: "0 16px" }}>
                  <span style={{ width: 36, flexShrink: 0, textAlign: "right", paddingRight: 14, color: "var(--text-3)", fontSize: 11, userSelect: "none", fontFamily: "'Geist Mono', monospace", lineHeight: "1.7" }}>{i + 1}</span>
                  <span style={{ flex: 1, whiteSpace: "pre", fontFamily: "'Geist Mono', monospace", fontSize: 12.5, lineHeight: "1.7", color: "var(--text-1)" }}
                    dangerouslySetInnerHTML={{ __html: highlightLine(line) + (i === lines.length - 1 ? '<span style="display:inline-block;width:7px;height:16px;background:var(--amber);vertical-align:text-bottom;margin-left:1px;border-radius:1px;animation:e-blink .8s step-end infinite"></span>' : "") }} />
                </div>
              ))
            )}
            <div ref={codeEndRef} />
            <style>{`@keyframes e-blink{50%{opacity:0}}`}</style>
          </div>
        )}

        {/* Preview */}
        {rightPanel === "preview" && html && (
          <motion.iframe ref={iframeRef} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5 }}
            sandbox="allow-scripts allow-same-origin" className="absolute inset-0 w-full h-full border-none" style={{ background: "#fff" }} />
        )}
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   FollowUpInput
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function FollowUpInput({ onSend, placeholder }: { onSend: (t: string) => void; placeholder: string }) {
  const [text, setText] = useState("");
  const compRef = useRef(false);
  return (
    <div style={{ padding: "10px 20px 14px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <div className="relative">
        <input type="text" value={text} onChange={e => setText(e.target.value)}
          onCompositionStart={() => { compRef.current = true; }} onCompositionEnd={e => { compRef.current = false; setText((e.target as HTMLInputElement).value); }}
          onKeyDown={e => { if (e.key === "Enter" && !compRef.current && text.trim()) { e.preventDefault(); onSend(text.trim()); setText(""); } }}
          placeholder={placeholder}
          className="w-full outline-none transition-all duration-200 focus:border-[var(--amber)]"
          style={{ background: "var(--surface-1)", border: "1px solid var(--border-1)", borderRadius: 10, padding: "10px 42px 10px 14px", fontSize: 13, fontFamily: "inherit", color: "var(--text-0)" }} />
        <button onClick={() => { if (text.trim()) { onSend(text.trim()); setText(""); } }}
          className="absolute right-[5px] top-1/2 -translate-y-1/2 transition-all"
          style={{ width: 28, height: 28, borderRadius: 6, border: "none", background: text.trim() ? "var(--amber)" : "var(--surface-2)", color: text.trim() ? "var(--void)" : "var(--text-3)", display: "flex", alignItems: "center", justifyContent: "center", cursor: text.trim() ? "pointer" : "default" }}>
          <Send size={12} />
        </button>
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   CompleteBar
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function CompleteBar({ fileName, size, rounds, elapsed, html }: {
  fileName: string; size: string; rounds: number; elapsed: number; html: string;
}) {
  const { t } = useLocale();
  function copy() { navigator.clipboard.writeText(html); }
  function download() { const b = new Blob([html], { type: "text/html" }); const u = URL.createObjectURL(b); const a = document.createElement("a"); a.href = u; a.download = fileName; a.click(); URL.revokeObjectURL(u); }
  function open() { const b = new Blob([html], { type: "text/html" }); window.open(URL.createObjectURL(b), "_blank"); }

  return (
    <motion.div initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.4, ease: EASE }}
      className="flex items-center gap-4 shrink-0" style={{ padding: "12px 20px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <div style={{ width: 28, height: 28, borderRadius: 8, background: "var(--pass-dim)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--pass)", fontSize: 13 }}>✓</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-0)", fontFamily: "'Geist Mono', monospace" }}>{fileName}</div>
        <div className="flex gap-3 mt-0.5" style={{ fontSize: 11, color: "var(--text-3)" }}>
          <span>{size}</span><span>{rounds} {t("complete.rounds")}</span><span>{elapsed}s</span><span style={{ color: "var(--pass)" }}>✓ {t("complete.passed")}</span>
        </div>
      </div>
      <div className="flex gap-1.5">
        {[
          { fn: copy, icon: <Copy size={11} />, label: t("action.copy"), primary: false },
          { fn: download, icon: <Download size={11} />, label: t("action.download"), primary: false },
          { fn: open, icon: <ArrowUpRight size={11} />, label: t("action.open"), primary: true },
        ].map(b => (
          <button key={b.label} onClick={b.fn} className="transition-all hover:opacity-90"
            style={{ padding: "6px 12px", borderRadius: 6, border: b.primary ? "none" : "1px solid var(--border-1)", background: b.primary ? "var(--amber)" : "none", color: b.primary ? "var(--void)" : "var(--text-1)", fontSize: 11, fontWeight: b.primary ? 600 : 400, cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontFamily: "inherit" }}>
            {b.icon}{b.label}
          </button>
        ))}
      </div>
    </motion.div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ConversationView
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function ConversationView({ msgs, thinking, thinkingElapsed, expertName, onSend, onFeedback, fmtTime }: {
  msgs: ChatMsg[]; thinking: boolean; thinkingElapsed: number; expertName: string;
  onSend: (t: string) => void; onFeedback: (s: "up" | "down", id: string) => void; fmtTime: (ts: number) => string;
}) {
  const { t } = useLocale();
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, thinking]);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[680px] mx-auto px-6 py-8 space-y-5">
          {msgs.map(msg => (
            <motion.div key={msg.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              {msg.role === "user" ? (
                <div className="flex justify-end">
                  <div style={{ maxWidth: "75%", padding: "10px 18px", borderRadius: "18px 18px 4px 18px", background: "var(--amber)", color: "var(--void)", fontSize: 14, lineHeight: 1.5 }}>{msg.text}</div>
                </div>
              ) : msg.role === "system" ? (
                <div style={{ padding: "10px 16px", borderRadius: 10, background: "var(--fail-dim)", color: "var(--fail)", fontSize: 13, border: "1px solid var(--fail-dim)" }}>{msg.text}</div>
              ) : (
                <MessageBubble text={msg.text} timestamp={msg.timestamp} fmtTime={fmtTime} onFeedback={s => onFeedback(s, msg.id)} />
              )}
            </motion.div>
          ))}
          {thinking && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2.5 py-2">
              <div className="flex gap-1">{[0, 1, 2].map(i => <div key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--amber)", animation: `e-dot 1.4s ease-in-out ${i * 0.2}s infinite` }} />)}</div>
              <span style={{ fontSize: 13, color: "var(--text-2)" }}>{expertName || t("thinking")}{thinkingElapsed > 0 ? ` · ${thinkingElapsed}s` : ""}</span>
              <style>{`@keyframes e-dot{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-5px);opacity:1}}`}</style>
            </motion.div>
          )}
          <div ref={endRef} />
        </div>
      </div>
      <FollowUpInput onSend={onSend} placeholder={t("convo.placeholder")} />
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   PAGE (root)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
export default function Page() {
  const { t } = useLocale();

  // ── State machine ──
  const [phase, setPhase] = useState<AppPhase>("idle");
  const [subPhase, setSubPhase] = useState<SubPhase>("thinking");
  const [mode, setMode] = useState<"build" | "conversation">("build");

  // ── Build state ──
  const [brief, setBrief] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [streamingCode, setStreamingCode] = useState("");
  const [html, setHtml] = useState<string | null>(null);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [rightPanel, setRightPanel] = useState<"code" | "preview">("code");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);

  // ── Conversation state ──
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [thinking, setThinking] = useState(false);
  const [thinkingElapsed, setThinkingElapsed] = useState(0);
  const [expertName, setExpertName] = useState("");

  // ── UI ──
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // ── Refs ──
  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const sidRef = useRef("");
  const sidebarRef = useRef<SidebarRef>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);
  const phaseRef = useRef<AppPhase>("idle");
  const subRef = useRef<SubPhase>("thinking");

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { subRef.current = subPhase; }, [subPhase]);
  useEffect(() => { if (typeof window !== "undefined" && window.innerWidth < 768) setSidebarCollapsed(true); }, []);

  // ── Auto switch to preview on complete ──
  useEffect(() => {
    if (phase === "complete" && html) {
      const t = setTimeout(() => setRightPanel("preview"), 500);
      return () => clearTimeout(t);
    }
  }, [phase, html]);

  // ── WebSocket ──
  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    sidRef.current = sid;
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => { setConnected(true); fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => setModel(d.model || "")).catch(() => {}); });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      // ── status ──
      if (msg.type === "status") {
        if (msg.content === "thinking") {
          setThinking(true); setThinkingElapsed(0); setExpertName("");
          const ts = Date.now();
          thTimerRef.current = setInterval(() => setThinkingElapsed(Math.floor((Date.now() - ts) / 1000)), 1000);
        } else if (msg.content === "pipeline_start") {
          setThinking(false);
          if (thTimerRef.current) { clearInterval(thTimerRef.current); thTimerRef.current = null; }
          if (subRef.current === "building") return;
          setSubPhase("building");
          if (phaseRef.current === "idle") {
            setPhase("active"); setMode("build");
            startRef.current = Date.now(); setElapsed(0);
            timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
          }
        } else if (msg.content === "idle") {
          setThinking(false);
          if (thTimerRef.current) { clearInterval(thTimerRef.current); thTimerRef.current = null; }
          if (phaseRef.current === "active") {
            setPhase("complete"); setSubPhase("done");
          }
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
          sidebarRef.current?.refresh();
        }
      }
      // ── agent_message ──
      else if (msg.type === "agent_message" && (msg as any).msg_type !== "handoff") {
        setThinking(false);
        if (phaseRef.current === "active" || phaseRef.current === "complete") {
          const h = extractHtml(msg.content);
          if (h) setHtml(h);
          if ((msg as any).files?.length) setFileName((msg as any).files[0]);
        } else {
          setMode("conversation");
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.role === "assistant" && last.text) return [...p.slice(0, -1), { ...last, text: msg.content }];
            return [...p, { id: Date.now().toString(), role: "assistant", text: msg.content, timestamp: Date.now() }];
          });
        }
      }
      // ── chunk ──
      else if (msg.type === "chunk") {
        if (phaseRef.current === "active" && subRef.current === "building") {
          setStreamingCode(prev => prev + msg.content);
        } else {
          setMode("conversation");
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.role === "assistant") return [...p.slice(0, -1), { ...last, text: last.text + msg.content }];
            return [...p, { id: Date.now().toString(), role: "assistant", text: msg.content, timestamp: Date.now() }];
          });
        }
      }
      // ── tool_event ──
      else if ((msg as any).type === "tool_event") {
        const evt = msg as unknown as ToolEvent;
        setToolEvents(prev => [...prev, evt]);
        if (evt.event === "write_file") { if (evt.file) setFileName(evt.file); if (evt.size) setFileSize(evt.size); }
      }
      // ── decision_request ──
      else if ((msg as any).type === "decision_request") {
        setThinking(false);
        if (thTimerRef.current) { clearInterval(thTimerRef.current); thTimerRef.current = null; }
        setDecisions((msg as any).decisions);
        setSubPhase("deciding");
        if (phaseRef.current === "idle") { setPhase("active"); setMode("build"); }
      }
      // ── expert ──
      else if ((msg as any).type === "expert") { setExpertName((msg as any).content || ""); }
      // ── error ──
      else if (msg.type === "error") {
        setPhase("idle"); if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        toast(msg.content, "error");
      }
    });

    return () => ws.close();
  }, []);

  // ── Actions ──
  function send(text: string) {
    const v = text.trim(); if (!v) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) { toast(t("error.disconnected"), "error"); return; }

    setBrief(v);
    setPhase("active"); setSubPhase("thinking"); setMode("build");
    setHtml(null); setStreamingCode(""); setToolEvents([]); setRightPanel("code"); setDecisions(null); setFileName(""); setFileSize(0);
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: v, timestamp: Date.now() }]);
    startRef.current = Date.now(); setElapsed(0);
    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);

    w.send(v);
  }

  function handleDecision(choices: { question: string; choice: string }[]) {
    wsRef.current?.sendRaw({ type: "decision_response", decisions: choices });
    setDecisions(null); setSubPhase("thinking");
  }

  function reset() {
    setPhase("idle"); setSubPhase("thinking"); setMode("build"); setBrief(""); setMsgs([]);
    setHtml(null); setStreamingCode(""); setToolEvents([]); setElapsed(0);
    setDecisions(null); setRightPanel("code"); setFileName(""); setFileSize(0);
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }

  function fmtTime(ts: number) { return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }

  const isConvo = mode === "conversation" && msgs.some(m => m.role === "assistant");
  const isBuild = mode === "build" && (phase === "active" || phase === "complete");

  return (
    <div className="h-screen flex" style={{ background: "var(--void)" }}>
      <Sidebar ref={sidebarRef} collapsed={sidebarCollapsed} onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        activeSessionId={sidRef.current} onNewTask={reset} onOpenSettings={() => setShowSettings(true)}
        onTaskSelect={(task: any) => {
          if (task.turns && Array.isArray(task.turns)) {
            const newMsgs: ChatMsg[] = [];
            for (const turn of task.turns) {
              newMsgs.push({ id: `${turn.timestamp}-q`, role: "user", text: turn.question, timestamp: (turn.timestamp || 0) * 1000 });
              if (turn.response) {
                const h = extractHtml(turn.response);
                if (h) { setHtml(h); setMode("build"); setPhase("complete"); setSubPhase("done"); setBrief(turn.question); setRightPanel("preview"); }
                else { newMsgs.push({ id: `${turn.timestamp}-a`, role: "assistant", text: turn.response, timestamp: (turn.timestamp || 0) * 1000 + 1 }); setMode("conversation"); }
              }
            }
            setMsgs(newMsgs);
          } else {
            const h = task.response ? extractHtml(task.response) : null;
            if (h) { setHtml(h); setMode("build"); setPhase("complete"); setSubPhase("done"); setBrief(task.request || task.title || ""); setRightPanel("preview"); }
            else if (task.response) {
              setMsgs([
                { id: task.id + "-q", role: "user", text: task.request || task.title || "", timestamp: task.created_at * 1000 },
                { id: task.id + "-a", role: "assistant", text: task.response, timestamp: task.created_at * 1000 + 1 },
              ]);
              setMode("conversation"); setPhase("idle");
            }
          }
        }} />

      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Connection dot */}
        <div className="absolute top-3 right-4 z-30">
          <button onClick={() => setShowSettings(true)} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full transition-colors hover:bg-[var(--surface-2)]" style={{ background: "var(--surface-1)", border: "1px solid var(--border-0)", cursor: "pointer" }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: connected ? "var(--pass)" : "var(--fail)" }} />
            <span style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "'Geist Mono', monospace" }}>{model || "..."}</span>
          </button>
        </div>

        <AnimatePresence mode="wait">
          {/* IDLE */}
          {phase === "idle" && !isConvo && (
            <motion.div key="empty" exit={{ opacity: 0, y: -30 }} transition={{ duration: 0.35 }} className="flex-1 flex flex-col">
              <EmptyState onSend={send} />
            </motion.div>
          )}

          {/* CONVERSATION */}
          {isConvo && (
            <motion.div key="convo" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex-1 flex flex-col">
              <ConversationView msgs={msgs} thinking={thinking} thinkingElapsed={thinkingElapsed} expertName={expertName}
                onSend={send} onFeedback={(s, id) => { wsRef.current?.sendRaw({ type: "feedback", signal: s, message_id: id }); }} fmtTime={fmtTime} />
            </motion.div>
          )}

          {/* BUILD (active / complete) */}
          {isBuild && !isConvo && (
            <motion.div key="build" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 flex flex-col min-h-0">
              <BriefBar text={brief} elapsed={elapsed} />
              <div className="flex flex-1 min-h-0">
                <ProcessPanel toolEvents={toolEvents} subPhase={subPhase} decisions={decisions} onDecision={handleDecision} />
                <CodePreviewPanel streamingCode={streamingCode} html={html} rightPanel={rightPanel} setRightPanel={setRightPanel} fileName={fileName} />
              </div>
              {phase === "complete" && html && (
                <CompleteBar fileName={fileName || "output.html"} size={fileSize ? `${(fileSize / 1024).toFixed(1)} KB` : `${(streamingCode.length / 1024).toFixed(1)} KB`}
                  rounds={toolEvents.filter(e => e.event === "write_file").length || 1} elapsed={elapsed} html={html} />
              )}
              {phase === "complete" && <FollowUpInput onSend={send} placeholder={t("followup.placeholder")} />}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} model={model} onModelChange={setModel} />
      <ToastContainer />
    </div>
  );
}
