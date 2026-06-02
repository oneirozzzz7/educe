"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Copy, Download, ArrowUpRight, ChevronRight, Paperclip } from "lucide-react";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/i18n";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { MessageBubble } from "@/components/message-bubble";
import { FileChips } from "@/components/file-chips";
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
  id: string; name: string; size: number; mime_type: string; is_image: boolean; error?: string; preview_url?: string;
}
interface Decision { question: string; options: string[]; }

const EASE = [0.16, 1, 0.3, 1] as const;
const ACCEPT = ".txt,.py,.js,.ts,.tsx,.jsx,.css,.html,.json,.md,.yaml,.yml,.xml,.csv,.sh,.sql,.go,.java,.c,.cpp,.h,.rb,.rs,.swift,.pdf,.xlsx,.xls,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg";

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
function Sigil({ size = 96 }: { size?: number }) {
  return (
    <svg viewBox="0 0 96 96" style={{ width: size, height: size }}>
      {/* Static rings — structure */}
      <circle cx="48" cy="48" r="46" fill="none" stroke="var(--border-1)" strokeWidth="0.5" />
      <circle cx="48" cy="48" r="33" fill="none" stroke="var(--border-1)" strokeWidth="0.4" />
      <circle cx="48" cy="48" r="20" fill="none" stroke="var(--border-0)" strokeWidth="0.3" opacity="0.6" />
      {/* Orbiting arcs — energy */}
      <circle cx="48" cy="48" r="46" fill="none" stroke="var(--amber)" strokeWidth="2"
        strokeLinecap="round" strokeDasharray="60 160"
        style={{ animation: "e-spin 10s linear infinite", transformOrigin: "center" }} />
      <circle cx="48" cy="48" r="33" fill="none" stroke="var(--amber-bright)" strokeWidth="1.2"
        strokeLinecap="round" strokeDasharray="40 168"
        opacity="0.55" style={{ animation: "e-spin-r 16s linear infinite", transformOrigin: "center" }} />
      <circle cx="48" cy="48" r="20" fill="none" stroke="var(--amber)" strokeWidth="0.7"
        strokeLinecap="round" strokeDasharray="22 104"
        opacity="0.35" style={{ animation: "e-spin 7s linear infinite", transformOrigin: "center" }} />
      {/* Core — the seed */}
      <circle cx="48" cy="48" r="10" fill="var(--amber)" opacity="0.04"
        style={{ animation: "e-breathe 4s ease-in-out infinite" }} />
      <circle cx="48" cy="48" r="4" fill="var(--amber)" opacity="0.85" />
      <circle cx="48" cy="48" r="2" fill="var(--text-0)" opacity="0.6" />
      <style>{`
        @keyframes e-spin{to{transform:rotate(360deg)}}
        @keyframes e-spin-r{to{transform:rotate(-360deg)}}
        @keyframes e-breathe{0%,100%{opacity:.03}50%{opacity:.1}}
      `}</style>
    </svg>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   EmptyState (no input — input is global now)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function EmptyState({ onSend }: { onSend: (t: string) => void }) {
  const { t } = useLocale();

  const starters: { key: Parameters<typeof t>[0]; prompt: string }[] = [
    { key: "starter.pomodoro", prompt: "做一个番茄钟" },
    { key: "starter.json", prompt: "做一个JSON工具" },
    { key: "starter.game", prompt: "做一个小游戏" },
    { key: "starter.dashboard", prompt: "做一个数据看板" },
  ];

  function submit() { onSend(starters[0].prompt); }

  return (
    <div className="flex-1 flex flex-col items-center relative overflow-hidden" style={{ justifyContent: "center", paddingBottom: "12%" }}>
      {/* Atmospheric glow — layered for depth */}
      <div className="absolute pointer-events-none" style={{ top: "25%", left: "50%", transform: "translate(-50%,-50%)", width: 700, height: 500, background: "radial-gradient(ellipse at center, rgba(212,148,76,0.08) 0%, rgba(212,148,76,0.03) 35%, transparent 65%)" }} />
      <div className="absolute pointer-events-none" style={{ top: "27%", left: "50%", transform: "translate(-50%,-50%)", width: 300, height: 300, background: "radial-gradient(circle, rgba(212,148,76,0.05) 0%, transparent 60%)", filter: "blur(40px)" }} />

      {/* Sigil */}
      <motion.div initial={{ opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1, ease: EASE }} className="relative z-10">
        <Sigil size={96} />
      </motion.div>

      {/* Title */}
      <motion.h1 initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.2, ease: EASE }}
        className="mt-14 mb-4 text-center z-10" style={{ fontFamily: "'Instrument Serif', Georgia, serif", fontSize: 36, color: "var(--text-0)", letterSpacing: "-0.015em", lineHeight: 1.15 }}>
        {t("empty.title")}
      </motion.h1>

      {/* Subtitle */}
      <motion.p initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.3, ease: EASE }}
        className="mb-10 text-center z-10" style={{ fontSize: 15, color: "var(--text-3)", lineHeight: 1.6, maxWidth: 420 }}>
        {t("empty.sub")}
      </motion.p>

      {/* Starters */}
      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.4, ease: EASE }}
        className="flex flex-wrap gap-2 justify-center px-6 max-w-[540px] z-10">
        {starters.map(s => (
          <button key={s.key} onClick={() => onSend(s.prompt)} className="starter-pill">
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
    <div className="flex items-center gap-3 shrink-0 relative" style={{ height: 42, padding: "0 24px", borderBottom: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px", color: "var(--amber)", padding: "3px 9px", background: "var(--amber-dim)", borderRadius: 4, border: "1px solid rgba(212,148,76,0.15)" }}>{t("brief.label")}</span>
      <span className="truncate" style={{ fontSize: 13, color: "var(--text-1)", flex: 1, fontWeight: 500 }}>{text}</span>
      <span style={{ fontSize: 12, color: "var(--amber)", fontFamily: "'Geist Mono', monospace", fontVariantNumeric: "tabular-nums", padding: "3px 10px", background: "rgba(212,148,76,0.04)", borderRadius: 5, border: "1px solid rgba(212,148,76,0.1)" }}>{elapsed}s</span>
      {/* Subtle amber accent line at bottom */}
      <div className="absolute bottom-0 left-[24px] right-[24px]" style={{ height: 1, background: "linear-gradient(90deg, var(--amber-dim) 0%, transparent 50%, var(--amber-dim) 100%)", opacity: 0.5 }} />
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BuildChatPanel (left side — conversation + process + input)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function BuildChatPanel({ brief, explanation, toolEvents, subPhase, decisions, onDecision, onSend, onStop, phase }: {
  brief: string; explanation: string; toolEvents: ToolEvent[]; subPhase: SubPhase;
  decisions: Decision[] | null; onDecision: (c: { question: string; choice: string }[]) => void;
  onSend: (t: string) => void; onStop: () => void; phase: AppPhase;
}) {
  const { t } = useLocale();
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [explanation, toolEvents]);

  return (
    <div className="flex flex-col min-h-0" style={{ width: "35%", minWidth: 300, maxWidth: 400, borderRight: "1px solid var(--border-0)", background: "var(--void)" }}>
      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto" style={{ padding: "16px 18px" }}>
        {/* User brief */}
        <div className="flex justify-end mb-4">
          <div className="user-bubble">{brief}</div>
        </div>

        {/* AI explanation text (streaming) */}
        {explanation && (
          <div className="mb-4" style={{ fontSize: 13, color: "var(--text-1)", lineHeight: 1.7 }}>
            {explanation}
            {subPhase === "building" && !explanation.endsWith("\n") && (
              <span style={{ display: "inline-block", width: 5, height: 14, background: "var(--amber)", borderRadius: 1, marginLeft: 2, verticalAlign: "text-bottom", animation: "e-blink .8s step-end infinite" }} />
            )}
          </div>
        )}

        {/* Tool events as inline markers */}
        {toolEvents.map((evt, i) => (
          <div key={i} className="flex items-center gap-2 mb-1.5" style={{ fontSize: 12 }}>
            <div style={{
              width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
              background: evt.event === "write_file" || evt.event === "write_file_result" ? "var(--amber)"
                : evt.event === "run" ? "var(--sage)"
                : evt.event === "run_result" ? (evt.success ? "var(--pass)" : "var(--fail)")
                : evt.event === "done" ? "var(--pass)" : "var(--text-3)",
            }} />
            <span style={{ color: "var(--text-2)" }}>
              {evt.event === "write_file" && <>{t("log.write")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3 }}>{evt.file}</code></>}
              {evt.event === "run" && <>{t("log.run")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3 }}>{evt.command?.slice(0, 40)}</code></>}
              {evt.event === "run_result" && <span style={{ color: evt.success ? "var(--pass)" : "var(--fail)" }}>{evt.success ? `✓ ${t("log.passed")}` : `✗ ${evt.output?.slice(0, 50)}`}</span>}
              {evt.event === "done" && <span style={{ color: "var(--pass)", fontWeight: 600 }}>✓ {t("log.done")}</span>}
              {evt.event === "thinking" && <span style={{ color: "var(--text-3)", fontStyle: "italic" }}>{evt.content?.slice(0, 60)}</span>}
            </span>
          </div>
        ))}

        {/* Thinking indicator when no events yet */}
        {toolEvents.length === 0 && !explanation && (
          <div className="flex items-center gap-2" style={{ fontSize: 13, color: "var(--text-2)" }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 2s ease-in-out infinite" }} />
            {t("thinking")}...
          </div>
        )}

        {/* Inline decision */}
        <AnimatePresence>
          {subPhase === "deciding" && decisions && (
            <InlineDecision decisions={decisions} onSubmit={onDecision} />
          )}
        </AnimatePresence>

        <div ref={endRef} />
      </div>

      {/* Input at bottom of chat panel */}
      <GlobalInput onSend={onSend} phase={phase} onStop={onStop} files={[]} onFileSelect={() => {}} onRemoveFile={() => {}} uploading={false} fileInputRef={{ current: null }} supportsVision={true} />
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ProcessBar (bottom thin progress strip)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function ProcessBar({ toolEvents, subPhase, expanded, onToggle, decisions, onDecision }: {
  toolEvents: ToolEvent[]; subPhase: SubPhase; expanded: boolean; onToggle: () => void;
  decisions: Decision[] | null; onDecision: (choices: { question: string; choice: string }[]) => void;
}) {
  const { t } = useLocale();

  const summary = toolEvents.map((evt, i) => {
    const isLast = i === toolEvents.length - 1 && subPhase !== "done";
    const color = evt.event === "thinking" ? "var(--text-3)"
      : evt.event === "write_file" || evt.event === "write_file_result" ? "var(--amber)"
      : evt.event === "run" ? "var(--sage)"
      : evt.event === "run_result" ? (evt.success ? "var(--pass)" : "var(--fail)")
      : evt.event === "done" ? "var(--pass)" : "var(--text-3)";

    let label = "";
    if (evt.event === "thinking") label = t("process.analyzing");
    else if (evt.event === "write_file" || evt.event === "write_file_result") label = `${t("log.write")} ${evt.file || ""}`;
    else if (evt.event === "run") label = t("log.run");
    else if (evt.event === "run_result") label = evt.success ? `✓` : `✗`;
    else if (evt.event === "done") label = `✓ ${t("log.done")}`;

    return { color, label, isLast };
  });

  return (
    <div className="shrink-0" style={{ borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      {/* Thin summary row */}
      <div className="flex items-center gap-1 px-5" style={{ height: 36 }}>
        {subPhase !== "done" && toolEvents.length === 0 && (
          <div className="flex items-center gap-2">
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--amber)", animation: "e-pulse 2s ease-in-out infinite" }} />
            <span style={{ fontSize: 12, color: "var(--text-2)" }}>{t("thinking")}...</span>
          </div>
        )}
        <div className="flex items-center gap-0 flex-1 overflow-hidden">
          {summary.slice(-6).map((s, i) => (
            <div key={i} className="flex items-center gap-0 shrink-0">
              {i > 0 && <span style={{ fontSize: 10, color: "var(--border-2)", margin: "0 6px" }}>→</span>}
              <div className="flex items-center gap-1.5">
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: s.color, boxShadow: s.isLast ? `0 0 6px ${s.color}` : "none", animation: s.isLast ? "e-pulse 2s ease-in-out infinite" : "none" }} />
                <span className="truncate" style={{ fontSize: 11, color: s.isLast ? "var(--text-1)" : "var(--text-3)", maxWidth: 140 }}>{s.label}</span>
              </div>
            </div>
          ))}
        </div>
        <button onClick={onToggle} className="flex items-center gap-1 shrink-0 ml-2 transition-colors hover:text-[var(--text-1)]" style={{ fontSize: 11, color: "var(--text-3)", border: "none", background: "none", cursor: "pointer", fontFamily: "inherit" }}>
          <ChevronRight size={10} style={{ transform: expanded ? "rotate(-90deg)" : "rotate(90deg)", transition: "transform 0.2s" }} />
          <span>{expanded ? "" : t("process.activity")}</span>
        </button>
      </div>

      {/* Expandable detail panel */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="max-h-[260px] overflow-y-auto px-5 pb-4 pt-1" style={{ borderTop: "1px solid var(--border-0)" }}>
              {/* Timeline */}
              <div className="relative" style={{ paddingLeft: 8 }}>
                {toolEvents.length > 1 && (
                  <div className="absolute" style={{ left: 8, top: 14, bottom: 14, width: 1, background: "linear-gradient(var(--border-1), var(--border-0))" }} />
                )}
                {toolEvents.map((evt, i) => (
                  <div key={i} className="flex gap-3 relative" style={{ padding: "6px 0" }}>
                    <div style={{
                      width: 17, height: 17, borderRadius: "50%", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1,
                      background: evt.event === "thinking" ? "var(--surface-3)"
                        : evt.event === "write_file" || evt.event === "write_file_result" ? "var(--amber-dim)"
                        : evt.event === "run" ? "var(--sage-dim)"
                        : evt.event === "run_result" ? (evt.success ? "var(--pass-dim)" : "var(--fail-dim)")
                        : evt.event === "done" ? "var(--pass-dim)" : "var(--surface-3)",
                    }}>
                      <svg width="9" height="9" viewBox="0 0 16 16" fill="currentColor" style={{
                        color: evt.event === "thinking" ? "var(--text-3)"
                          : evt.event === "write_file" || evt.event === "write_file_result" ? "var(--amber)"
                          : evt.event === "run" ? "var(--sage)"
                          : evt.event === "run_result" ? (evt.success ? "var(--pass)" : "var(--fail)")
                          : evt.event === "done" ? "var(--pass)" : "var(--text-3)",
                      }}>
                        {evt.event === "thinking" && <><circle cx="8" cy="8" r="2"/><circle cx="3" cy="8" r="1.5" opacity=".5"/><circle cx="13" cy="8" r="1.5" opacity=".5"/></>}
                        {(evt.event === "write_file" || evt.event === "write_file_result") && <path d="M3 2h7l3 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/>}
                        {evt.event === "run" && <path d="M4 2l10 6-10 6z"/>}
                        {evt.event === "run_result" && (evt.success ? <path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/> : <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>)}
                        {evt.event === "done" && <path d="M3 8l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>}
                        {!["thinking", "write_file", "write_file_result", "run", "run_result", "done"].includes(evt.event) && <circle cx="8" cy="8" r="3"/>}
                      </svg>
                    </div>
                    <div style={{ flex: 1, minWidth: 0, fontSize: 12, color: "var(--text-1)", lineHeight: 1.5 }}>
                      {evt.event === "thinking" && <span style={{ color: "var(--text-3)", fontStyle: "italic" }}>&ldquo;{evt.content?.slice(0, 100)}&rdquo;</span>}
                      {(evt.event === "write_file" || evt.event === "write_file_result") && <span>{t("log.write")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "1px 5px", borderRadius: 3, color: "var(--text-0)" }}>{evt.file}</code>{evt.size ? <span style={{ color: "var(--text-3)", marginLeft: 4 }}>({(evt.size / 1024).toFixed(1)} KB)</span> : null}</span>}
                      {evt.event === "run" && <span>{t("log.run")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "1px 5px", borderRadius: 3, color: "var(--text-0)" }}>{evt.command?.slice(0, 60)}</code></span>}
                      {evt.event === "run_result" && <span style={{ color: evt.success ? "var(--pass)" : "var(--fail)", fontWeight: 500 }}>{evt.success ? `✓ ${t("log.passed")}` : `✗ ${evt.output?.slice(0, 80)}`}</span>}
                      {evt.event === "done" && <span style={{ color: "var(--pass)", fontWeight: 600 }}>✓ {t("log.done")} · {evt.turns} {t("complete.rounds")}</span>}
                    </div>
                  </div>
                ))}
              </div>

              {/* Inline decision */}
              <AnimatePresence>
                {subPhase === "deciding" && decisions && (
                  <InlineDecision decisions={decisions} onSubmit={onDecision} />
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
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
          style={{ padding: "8px 20px", borderRadius: 6, fontSize: 13, fontWeight: 600, border: "none", background: "var(--amber)", color: "#111", cursor: "pointer", fontFamily: "inherit" }}>
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
function CodePreviewPanel({ streamingCode, html, rightPanel, setRightPanel, fileName, toolEvents, subPhase }: {
  streamingCode: string; html: string | null;
  rightPanel: "code" | "preview"; setRightPanel: (v: "code" | "preview") => void;
  fileName: string; toolEvents: ToolEvent[]; subPhase: SubPhase;
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
      // Try preview server first (supports multi-file projects + CDN)
      // Fall back to srcdoc for simple single-file HTML
      const previewUrl = `http://${window.location.hostname}:8080/`;
      fetch(previewUrl, { method: "HEAD", mode: "no-cors" }).then(() => {
        if (iframeRef.current) iframeRef.current.src = previewUrl;
      }).catch(() => {
        if (iframeRef.current) iframeRef.current.srcdoc = html;
      });
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
      <div className="flex items-center shrink-0" style={{ height: 38, padding: "0 16px", borderBottom: "1px solid var(--border-0)", background: showTabs ? "var(--surface-0)" : "var(--surface-1)" }}>
        {!showTabs ? (
          <>
            {streamingCode && <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)", marginRight: 10, animation: "e-pulse 2s ease-in-out infinite", boxShadow: "0 0 6px var(--amber-dim)" }} />}
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 12, color: "var(--text-1)", fontWeight: 500 }}>{fileName || "..."}</span>
            {streamingCode && <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)", marginLeft: "auto", background: "var(--surface-2)", padding: "2px 6px", borderRadius: 4 }}>{(streamingCode.length / 1024).toFixed(1)} KB</span>}
          </>
        ) : (
          <>
            {(["code", "preview"] as const).map(tab => (
              <button key={tab} onClick={() => setRightPanel(tab)}
                className="relative transition-colors" style={{ padding: "10px 16px", fontSize: 12, fontWeight: 500, color: rightPanel === tab ? "var(--text-0)" : "var(--text-3)", border: "none", background: "none", cursor: "pointer", fontFamily: "inherit" }}>
                {tab === "code" ? "Code" : "Preview"}
                {rightPanel === tab && <div className="absolute bottom-0 left-[16px] right-[16px]" style={{ height: 2, background: "var(--amber)", borderRadius: 1 }} />}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: "var(--text-3)", background: "var(--surface-2)", padding: "2px 8px", borderRadius: 4 }}>{fileName}</span>
          </>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 relative min-h-0">
        {/* Code view */}
        {rightPanel === "code" && (
          <div className="absolute inset-0 overflow-y-auto" onScroll={onCodeScroll} style={{ padding: "12px 0" }}>
            {lines.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-5 px-8">
                {/* Small breathing sigil */}
                <Sigil size={48} />
                {/* Dynamic status text */}
                <div className="text-center max-w-[400px]">
                  <div style={{ fontSize: 14, color: "var(--text-1)", marginBottom: 8 }}>
                    {subPhase === "thinking" ? t("process.analyzing") : subPhase === "building" ? t("process.structuring") : t("thinking")}...
                  </div>
                  {/* Show latest thinking content from tool events */}
                  {toolEvents.filter(e => e.event === "thinking" && e.content).slice(-1).map((evt, i) => (
                    <div key={i} style={{ fontSize: 13, color: "var(--text-3)", fontStyle: "italic", lineHeight: 1.6 }}>
                      &ldquo;{evt.content!.slice(0, 120)}{evt.content!.length > 120 ? "..." : ""}&rdquo;
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              lines.map((line, i) => (
                <div key={i} className="flex hover:bg-[var(--surface-1)] transition-colors duration-100" style={{ padding: "0 16px" }}>
                  <span style={{ width: 40, flexShrink: 0, textAlign: "right", paddingRight: 16, color: "var(--text-3)", fontSize: 11, userSelect: "none", fontFamily: "'Geist Mono', monospace", lineHeight: "1.7", borderRight: "1px solid var(--border-0)" }}>{i + 1}</span>
                  <span style={{ flex: 1, whiteSpace: "pre", fontFamily: "'Geist Mono', monospace", fontSize: 12.5, lineHeight: "1.7", color: "var(--text-1)", paddingLeft: 14 }}
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
            className="absolute inset-0 w-full h-full border-none" style={{ background: "#fff" }} />
        )}
      </div>
    </div>
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   GlobalInput — always visible at bottom of canvas
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function GlobalInput({ onSend, phase, onStop, files, onFileSelect, onRemoveFile, uploading, fileInputRef, supportsVision }: {
  onSend: (t: string) => void; phase: AppPhase; onStop?: () => void;
  files: UploadedFile[]; onFileSelect: (f: FileList) => void; onRemoveFile: (id: string) => void;
  uploading: boolean; fileInputRef: React.RefObject<HTMLInputElement | null>; supportsVision: boolean;
}) {
  const [text, setText] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const compRef = useRef(false);
  const { t } = useLocale();
  const isGenerating = phase === "active";
  const canSend = (text.trim() || files.length > 0) && !isGenerating;

  function submit() {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <div className="shrink-0" style={{ padding: "12px 20px 16px", background: "linear-gradient(transparent, var(--void) 8px)", backdropFilter: "blur(8px)" }}
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) onFileSelect(e.dataTransfer.files); }}>
      <div className="max-w-[680px] mx-auto">
        {/* File chips */}
        {files.length > 0 && (
          <div className="mb-2">
            <FileChips files={files} onRemove={onRemoveFile} supportsVision={supportsVision} />
          </div>
        )}
        {/* Drag overlay */}
        {dragOver && (
          <div className="mb-2 py-3 text-center text-[12px] rounded-xl border-2 border-dashed transition-all"
            style={{ borderColor: "var(--amber)", background: "var(--amber-dim)", color: "var(--amber)" }}>
            松手上传文件
          </div>
        )}
        <div className="relative">
          <textarea value={text} onChange={e => setText(e.target.value)}
            onCompositionStart={() => { compRef.current = true; }}
            onCompositionEnd={e => { compRef.current = false; setText((e.target as HTMLTextAreaElement).value); }}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !compRef.current) { e.preventDefault(); submit(); } }}
            placeholder={isGenerating ? (t("building") + "...") : t("empty.placeholder")}
            rows={1}
            className="educe-input"
            style={{ opacity: isGenerating ? 0.7 : 1, paddingLeft: 48 }}
          />
          {/* Paperclip button */}
          <button onClick={() => fileInputRef.current?.click()} disabled={uploading || isGenerating}
            className="absolute left-[10px] bottom-[10px] w-[36px] h-[36px] rounded-[10px] flex items-center justify-center transition-all hover:bg-[var(--surface-2)]"
            style={{ color: uploading ? "var(--amber)" : "var(--text-3)", border: "none", background: "none", cursor: isGenerating ? "default" : "pointer" }}
            title="上传文件">
            {uploading ? <span style={{ fontSize: 10, fontWeight: 700, color: "var(--amber)" }}>...</span> : <Paperclip size={15} />}
          </button>
          {/* Send / Stop button */}
          {isGenerating ? (
            <button onClick={onStop} className="absolute right-[8px] bottom-[9px] transition-all duration-200 hover:opacity-80"
              style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: "var(--fail)", color: "#111", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}
              title="Stop">
              <div style={{ width: 12, height: 12, borderRadius: 2, background: "var(--void)" }} />
            </button>
          ) : (
            <button onClick={submit} disabled={!canSend} className="absolute right-[8px] bottom-[9px] transition-all duration-200"
              style={{ width: 38, height: 38, borderRadius: 10, border: "none", background: canSend ? "var(--amber)" : "var(--surface-2)", color: canSend ? "#111" : "var(--text-3)", display: "flex", alignItems: "center", justifyContent: "center", cursor: canSend ? "pointer" : "default", opacity: canSend ? 1 : 0.5, transform: `scale(${canSend ? 1 : 0.93})` }}>
              <Send size={15} />
            </button>
          )}
          {/* Hidden file input */}
          <input ref={fileInputRef} type="file" multiple accept={ACCEPT} className="hidden"
            onChange={e => { if (e.target.files) onFileSelect(e.target.files); e.target.value = ""; }} />
        </div>
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
      className="flex items-center gap-4 shrink-0" style={{ padding: "14px 24px", borderTop: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      <div style={{ width: 30, height: 30, borderRadius: 8, background: "var(--pass-dim)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--pass)", fontSize: 14, boxShadow: "0 0 12px var(--pass-dim)" }}>✓</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-0)", fontFamily: "'Geist Mono', monospace" }}>{fileName}</div>
        <div className="flex gap-3 mt-1" style={{ fontSize: 11, color: "var(--text-3)" }}>
          <span>{size}</span>
          <span>{rounds} {t("complete.rounds")}</span>
          <span>{elapsed}s</span>
          <span style={{ color: "var(--pass)", fontWeight: 500 }}>✓ {t("complete.passed")}</span>
        </div>
      </div>
      <div className="flex gap-2">
        {[
          { fn: copy, icon: <Copy size={12} />, label: t("action.copy"), primary: false },
          { fn: download, icon: <Download size={12} />, label: t("action.download"), primary: false },
          { fn: open, icon: <ArrowUpRight size={12} />, label: t("action.open"), primary: true },
        ].map(b => (
          <button key={b.label} onClick={b.fn}
            className="complete-bar-btn"
            style={{
              padding: "7px 14px", borderRadius: 7,
              border: b.primary ? "none" : "1px solid var(--border-1)",
              background: b.primary ? "var(--amber)" : "var(--surface-2)",
              color: b.primary ? "var(--void)" : "var(--text-1)",
              fontSize: 12, fontWeight: b.primary ? 600 : 500,
              cursor: "pointer", display: "flex", alignItems: "center", gap: 5,
              fontFamily: "inherit",
              boxShadow: b.primary ? "0 2px 12px var(--amber-dim)" : "none",
            }}>
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
                  <div className="relative group/user shrink-0 max-w-[75%]">
                    <div className="user-bubble">{msg.text}</div>
                    <button onClick={() => navigator.clipboard.writeText(msg.text)}
                      className="absolute -left-8 top-1/2 -translate-y-1/2 w-6 h-6 rounded-md flex items-center justify-center opacity-0 group-hover/user:opacity-100 transition-opacity"
                      style={{ background: "var(--surface-2)", color: "var(--text-3)" }} title="Copy">
                      <Copy size={11} />
                    </button>
                  </div>
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
  const [hasArtifact, setHasArtifact] = useState(false);

  // ── Build state ──
  const [brief, setBrief] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [aiText, setAiText] = useState("");
  const [streamingCode, setStreamingCode] = useState("");
  const [html, setHtml] = useState<string | null>(null);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [rightPanel, setRightPanel] = useState<"code" | "preview">("code");
  const [expandedLog, setExpandedLog] = useState(false);
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

  // ── File upload ──
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    if (phase === "complete") {
      let finalHtml = html;
      if (!finalHtml && streamingCode && streamingCode.includes("</html>")) {
        finalHtml = extractHtml(streamingCode) || streamingCode;
        setHtml(finalHtml);
      }
      if (finalHtml) {
        const t = setTimeout(() => setRightPanel("preview"), 500);
        return () => clearTimeout(t);
      }
    }
  }, [phase, html, streamingCode]);

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
          // New build starting — reset old build state
          setSubPhase("building"); setHasArtifact(true);
          setHtml(null); setStreamingCode(""); setRightPanel("code"); setFileName(""); setFileSize(0);
          if (phaseRef.current === "idle" || phaseRef.current === "complete") {
            setPhase("active");
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
          // All chunks go to streamingCode; we split text/code in render via derived state
          setStreamingCode(prev => prev + msg.content);
        } else {
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
        if (phaseRef.current === "idle") { setPhase("active"); setHasArtifact(true); }
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

  // ── File Upload ──
  async function handleFileSelect(selectedFiles: FileList) {
    if (!selectedFiles || selectedFiles.length === 0) return;
    setUploading(true);
    const newFiles: UploadedFile[] = [];
    for (let i = 0; i < Math.min(selectedFiles.length, 5); i++) {
      const file = selectedFiles[i];
      const formData = new FormData();
      formData.append("file", file);
      try {
        const d = await new Promise<Record<string, unknown>>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `http://${API_HOST}/api/upload/${sidRef.current}`);
          xhr.onload = () => { try { resolve(JSON.parse(xhr.responseText)); } catch { reject(new Error("parse")); } };
          xhr.onerror = () => reject(new Error("network"));
          xhr.send(formData);
        });
        if (d.status === "ok" && d.file) {
          const uploaded = d.file as UploadedFile;
          // Generate preview URL for images
          if (uploaded.is_image && file.type.startsWith("image/")) {
            uploaded.preview_url = URL.createObjectURL(file);
          }
          newFiles.push(uploaded);
        } else {
          newFiles.push({ id: Date.now().toString(), name: file.name, size: file.size, mime_type: "", is_image: false, error: String(d.error || "failed") });
        }
      } catch {
        newFiles.push({ id: Date.now().toString(), name: file.name, size: file.size, mime_type: "", is_image: false, error: "上传失败" });
      }
    }
    setFiles(prev => [...prev, ...newFiles.filter(f => !f.error)]);
    if (newFiles.some(f => f.error)) toast(newFiles.filter(f => f.error).map(f => `${f.name}: ${f.error}`).join(", "), "error");
    setUploading(false);
  }

  function removeFile(id: string) {
    setFiles(prev => prev.filter(f => f.id !== id));
    fetch(`http://${API_HOST}/api/upload/${sidRef.current}/${id}`, { method: "DELETE" }).catch(() => {});
  }

  // ── Actions ──
  function send(text: string) {
    const v = text.trim(); if (!v && files.length === 0) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) { toast(t("error.disconnected"), "error"); return; }

    setBrief(v || files.map(f => f.name).join(", "));
    setPhase("active"); setSubPhase("thinking");
    setStreamingCode(""); setToolEvents([]); setDecisions(null);
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: v + (files.length > 0 ? `\n📎 ${files.map(f => f.name).join(", ")}` : ""), timestamp: Date.now() }]);
    startRef.current = Date.now(); setElapsed(0);
    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);

    const fileIds = files.map(f => f.id);
    w.send(v, fileIds.length > 0 ? fileIds : undefined);
    setFiles([]);
  }

  function handleDecision(choices: { question: string; choice: string }[]) {
    wsRef.current?.sendRaw({ type: "decision_response", decisions: choices });
    setDecisions(null); setSubPhase("thinking");
  }

  function reset() {
    setPhase("idle"); setSubPhase("thinking"); setHasArtifact(false); setBrief(""); setMsgs([]);
    setHtml(null); setStreamingCode(""); setToolEvents([]); setElapsed(0);
    setDecisions(null); setRightPanel("code"); setFileName(""); setFileSize(0);
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }

  function fmtTime(ts: number) { return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }

  const hasConversation = msgs.some(m => m.role === "assistant");
  const showArtifact = hasArtifact && (phase === "active" || phase === "complete");
  const supportsVision = /gpt-4o|claude|gemini/i.test(model);

  // Derived: split streamingCode into explanation text (before code marker) and actual code (after)
  const codeMarkerIdx = streamingCode.indexOf("```action:write_file");
  const buildExplanation = codeMarkerIdx > 0 ? streamingCode.slice(0, codeMarkerIdx).trim() : (codeMarkerIdx === -1 ? streamingCode : "");
  // Strip metadata header (```action:write_file\npath: xxx\n---\n) from code
  let buildCode = codeMarkerIdx >= 0 ? streamingCode.slice(codeMarkerIdx) : "";
  let derivedFileName = fileName;
  const headerEndIdx = buildCode.indexOf("---\n");
  if (headerEndIdx >= 0) {
    const headerBlock = buildCode.slice(0, headerEndIdx);
    const pathMatch = headerBlock.match(/path:\s*(.+)/);
    if (pathMatch) derivedFileName = pathMatch[1].trim();
    buildCode = buildCode.slice(headerEndIdx + 4);
  }

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
                if (h) { setHtml(h); setHasArtifact(true); setPhase("complete"); setSubPhase("done"); setBrief(turn.question); setRightPanel("preview"); }
                else { newMsgs.push({ id: `${turn.timestamp}-a`, role: "assistant", text: turn.response, timestamp: (turn.timestamp || 0) * 1000 + 1 }); }
              }
            }
            setMsgs(newMsgs);
          } else {
            const h = task.response ? extractHtml(task.response) : null;
            if (h) { setHtml(h); setHasArtifact(true); setPhase("complete"); setSubPhase("done"); setBrief(task.request || task.title || ""); setRightPanel("preview"); }
            else if (task.response) {
              setMsgs([
                { id: task.id + "-q", role: "user", text: task.request || task.title || "", timestamp: task.created_at * 1000 },
                { id: task.id + "-a", role: "assistant", text: task.response, timestamp: task.created_at * 1000 + 1 },
              ]);
              setPhase("idle");
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
          {/* IDLE — no messages */}
          {phase === "idle" && !hasConversation && (
            <motion.div key="empty" exit={{ opacity: 0, y: -30 }} transition={{ duration: 0.35 }} className="flex-1 flex flex-col">
              <EmptyState onSend={send} />
            </motion.div>
          )}

          {/* ACTIVE — unified chat + optional artifact */}
          {(phase !== "idle" || hasConversation) && (
            <motion.div key="active" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 flex flex-col min-h-0">
              {showArtifact && <BriefBar text={brief} elapsed={elapsed} />}
              <div className="flex flex-1 min-h-0">
                {/* Chat panel — always present, adapts width */}
                <div className="flex flex-col min-h-0 transition-all duration-300 flex-1"
                  style={showArtifact ? { width: "35%", minWidth: 300, maxWidth: 400, borderRight: "1px solid var(--border-0)", background: "var(--void)", flex: "none" } : { background: "var(--void)" }}>
                  {/* Scrollable chat content */}
                  <div className="flex-1 overflow-y-auto" style={{ padding: showArtifact ? "16px 18px" : "24px 28px 120px" }}>
                    {/* Constrain message width for readability */}
                    <div style={{ maxWidth: showArtifact ? "100%" : "760px", margin: showArtifact ? undefined : "0 auto" }}>
                    {/* User messages + AI replies */}
                    {msgs.map(msg => (
                      <div key={msg.id} className={`mb-4 ${msg.role === "user" ? "flex justify-end" : ""}`}>
                        {msg.role === "user" ? (
                          <div className="relative group/user shrink-0 max-w-[75%]">
                            <div className="user-bubble">{msg.text}</div>
                            <button onClick={() => navigator.clipboard.writeText(msg.text)}
                              className="absolute -left-8 top-1/2 -translate-y-1/2 w-6 h-6 rounded-md flex items-center justify-center opacity-0 group-hover/user:opacity-100 transition-opacity"
                              style={{ background: "var(--surface-2)", color: "var(--text-3)" }} title="Copy">
                              <Copy size={11} />
                            </button>
                          </div>
                        ) : (
                          <MessageBubble text={msg.text} timestamp={msg.timestamp} fmtTime={fmtTime} onFeedback={s => { wsRef.current?.sendRaw({ type: "feedback", signal: s, message_id: msg.id }); }} />
                        )}
                      </div>
                    ))}

                    {/* Build explanation (streaming text before code) */}
                    {showArtifact && buildExplanation && (
                      <div className="mb-4" style={{ fontSize: 13, color: "var(--text-1)", lineHeight: 1.7 }}>
                        {buildExplanation}
                        {subPhase === "building" && <span style={{ display: "inline-block", width: 5, height: 14, background: "var(--amber)", borderRadius: 1, marginLeft: 2, verticalAlign: "text-bottom", animation: "e-blink .8s step-end infinite" }} />}
                      </div>
                    )}

                    {/* Tool events — inside a subtle bordered box, part of AI response */}
                    {toolEvents.filter(evt =>
                      // Skip thinking events (already shown in buildExplanation)
                      evt.event !== "thinking" &&
                      // Skip events with no meaningful content
                      !(evt.event === "write_file_result" && !evt.file) &&
                      !(evt.event === "read_file_result") &&
                      // Skip empty write_file events
                      !(evt.event === "write_file" && !evt.file)
                    ).length > 0 && (
                      <div className="mb-4" style={{ padding: "10px 14px", borderRadius: 10, background: "var(--surface-1)", border: "1px solid var(--border-0)" }}>
                        {toolEvents.filter(evt =>
                          evt.event !== "thinking" &&
                          !(evt.event === "write_file_result" && !evt.file) &&
                          !(evt.event === "read_file_result") &&
                          !(evt.event === "write_file" && !evt.file)
                        ).map((evt, i) => (
                          <div key={i} className="flex items-center gap-2 py-1" style={{ fontSize: 12 }}>
                            <div style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                              background: evt.event === "write_file" || evt.event === "write_file_result" ? "var(--amber)"
                                : evt.event === "run" ? "var(--sage)"
                                : evt.event === "run_result" ? (evt.success ? "var(--pass)" : "var(--fail)")
                                : evt.event === "done" ? "var(--pass)" : "var(--text-3)" }} />
                            <span style={{ color: "var(--text-2)" }}>
                              {(evt.event === "write_file" || evt.event === "write_file_result") && evt.file && <>{t("log.write")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3 }}>{evt.file}</code>{evt.size ? <span style={{ marginLeft: 4, color: "var(--text-3)" }}>({(evt.size/1024).toFixed(1)}KB)</span> : null}</>}
                              {evt.event === "run" && evt.command && <>{t("log.run")} <code style={{ fontFamily: "'Geist Mono'", fontSize: 11, background: "var(--surface-3)", padding: "0 4px", borderRadius: 3 }}>{evt.command.slice(0, 50)}</code></>}
                              {evt.event === "run_result" && <span style={{ color: evt.success ? "var(--pass)" : "var(--fail)" }}>{evt.success ? `✓ ${t("log.passed")}` : `✗ ${evt.output?.slice(0, 60)}`}</span>}
                              {evt.event === "done" && <span style={{ color: "var(--pass)", fontWeight: 600 }}>✓ {t("log.done")}</span>}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Thinking indicator */}
                    {thinking && (
                      <div className="flex items-center gap-2 py-2" style={{ fontSize: 13, color: "var(--text-2)" }}>
                        <div className="flex gap-1">{[0, 1, 2].map(i => <div key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--amber)", animation: `e-dot 1.4s ease-in-out ${i * 0.2}s infinite` }} />)}</div>
                        {expertName || t("thinking")}{thinkingElapsed > 0 ? ` · ${thinkingElapsed}s` : ""}
                        <style>{`@keyframes e-dot{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-5px);opacity:1}}`}</style>
                      </div>
                    )}

                    {/* Inline decision */}
                    <AnimatePresence>
                      {subPhase === "deciding" && decisions && (
                        <InlineDecision decisions={decisions} onSubmit={handleDecision} />
                      )}
                    </AnimatePresence>
                    </div>{/* close maxWidth container */}
                  </div>

                  {/* Input — inside chat panel when artifact visible, at bottom otherwise */}
                  {showArtifact && (
                    <GlobalInput onSend={send} phase={phase} files={files} onFileSelect={handleFileSelect} onRemoveFile={removeFile} uploading={uploading} fileInputRef={fileInputRef} supportsVision={supportsVision} onStop={() => {
                      wsRef.current?.close(); setPhase("idle");
                      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
                    }} />
                  )}
                </div>

                {/* Artifact panel — slides in when hasArtifact */}
                <AnimatePresence>
                  {showArtifact && (
                    <motion.div key="artifact" initial={{ width: 0, opacity: 0 }} animate={{ width: "65%", opacity: 1 }} exit={{ width: 0, opacity: 0 }}
                      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }} className="flex flex-col min-h-0 overflow-hidden">
                      <CodePreviewPanel streamingCode={buildCode} html={html} rightPanel={rightPanel} setRightPanel={setRightPanel} fileName={derivedFileName} toolEvents={toolEvents} subPhase={subPhase} />
                      {phase === "complete" && html && (
                        <CompleteBar fileName={derivedFileName || "output.html"} size={fileSize ? `${(fileSize / 1024).toFixed(1)} KB` : `${(buildCode.length / 1024).toFixed(1)} KB`}
                          rounds={toolEvents.filter(e => e.event === "write_file").length || 1} elapsed={elapsed} html={html} />
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Global input — visible when no artifact panel (idle, conversation, thinking without pipeline) */}
        {!showArtifact && (
          <GlobalInput onSend={send} phase={phase} files={files} onFileSelect={handleFileSelect} onRemoveFile={removeFile} uploading={uploading} fileInputRef={fileInputRef} supportsVision={supportsVision} onStop={() => {
            wsRef.current?.close(); setPhase("idle");
            if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
          }} />
        )}
      </div>

      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} model={model} onModelChange={setModel} />
      <ToastContainer />
    </div>
  );
}
