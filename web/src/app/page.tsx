"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, Sparkles, ChevronDown, ChevronRight, ExternalLink,
  Check, Loader2, Settings, X, Clock, Code2, Eye,
} from "lucide-react";
import { createWS, AGENTS, API_HOST, type ServerMessage, type AgentId } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  steps?: StepInfo[];
  html?: string;
  timestamp: number;
}

interface StepInfo { agent: string; summary: string; done: boolean }

export default function Page() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [working, setWorking] = useState(false);
  const [curAgent, setCurAgent] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [showSettings, setShowSettings] = useState(false);

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const workingRef = useRef(false);
  const composingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);

  const hasMessages = msgs.length > 0;

  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      setConnected(true);
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => setModel(d.model || ""));
    });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "status") {
        if (msg.content === "pipeline_start") {
          if (workingRef.current) return;
          workingRef.current = true;
          setWorking(true);
          setCurAgent("");
          setElapsed(0);
          startRef.current = Date.now();
          timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: "", steps: [], timestamp: Date.now() }]);
        } else if (msg.content === "idle") {
          workingRef.current = false;
          setWorking(false);
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        }
      } else if (msg.type === "agent_message" && msg.msg_type !== "handoff") {
        if (!workingRef.current) {
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: msg.content, timestamp: Date.now() }]);
        } else {
          setCurAgent(msg.sender);
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.steps !== undefined) {
              const steps = [...(last.steps || []), { agent: msg.sender, summary: msg.summary || "", done: true }];
              const html = extractHtml(msg.content) || last.html;
              return [...p.slice(0, -1), { ...last, steps, html, text: msg.content }];
            }
            return p;
          });
        }
      } else if (msg.type === "chunk") {
        setCurAgent(msg.sender);
      } else if (msg.type === "error") {
        workingRef.current = false;
        setWorking(false);
        if (timerRef.current) clearInterval(timerRef.current);
        setMsgs(p => [...p, { id: Date.now().toString(), role: "system", text: msg.content, timestamp: Date.now() }]);
      }
    });

    return () => ws.close();
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [msgs, working, elapsed]);

  function extractHtml(c: string) {
    const m = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?)```/) || c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    return m ? m[1] : undefined;
  }

  function send(text?: string) {
    const t = (text || input).trim();
    if (!t) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) { alert("未连接到后端(7860)"); return; }
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: t, timestamp: Date.now() }]);
    w.send(t);
    setInput("");
  }

  function formatTime(ts: number) {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  return (
    <div className="h-screen flex flex-col bg-[#F7F7F8]">
      {/* ─── 顶栏 ─── */}
      <nav className="h-12 px-5 flex items-center bg-white border-b border-gray-200/60 shrink-0 sticky top-0 z-50">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <Sparkles size={14} className="text-white" />
          </div>
          <span className="text-[15px] font-bold tracking-tight text-gray-900">
            Deep<span className="text-indigo-600">Forge</span>
          </span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-2">
          <div className={cn("flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border",
            connected ? "text-gray-500 bg-gray-50 border-gray-200" : "text-red-500 bg-red-50 border-red-200")}>
            <span className={cn("w-1.5 h-1.5 rounded-full", connected ? "bg-emerald-500" : "bg-red-500")} />
            {model || "..."}
          </div>
          <button onClick={() => {
            setShowSettings(true);
            fetch(`http://${API_HOST}/api/models`).then(r => r.json()).then(d => setModels(d.models || [])).catch(() => {});
          }} className="w-7 h-7 rounded-lg border border-gray-200 bg-white flex items-center justify-center text-gray-400 hover:text-indigo-600 hover:border-indigo-200 transition-colors">
            <Settings size={13} />
          </button>
        </div>
      </nav>

      {/* ─── 主区域 ─── */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-[720px] mx-auto px-5 py-6 pb-28 min-h-full flex flex-col">

          {/* 空状态 */}
          {!hasMessages && !working && (
            <div className="flex-1 flex items-center justify-center">
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="text-center w-full max-w-[560px]">
                <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                  <Sparkles className="text-white" size={24} />
                </div>
                <h1 className="text-2xl font-semibold text-gray-900 tracking-tight mb-1.5">What will you build?</h1>
                <p className="text-sm text-gray-400 mb-8">Idea → Product, powered by multi-agent collaboration</p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {[["🍅", "番茄钟"], ["🔧", "JSON工具"], ["🎮", "小游戏"], ["📝", "编辑器"], ["🧮", "计算器"]].map(([icon, label]) => (
                    <button key={label} onClick={() => send(`做一个${label}`)}
                      className="flex items-center gap-1.5 px-3.5 py-2 text-[13px] text-gray-500 bg-white border border-gray-200 rounded-full hover:border-indigo-300 hover:text-indigo-600 shadow-sm transition-all">
                      <span>{icon}</span>{label}
                    </button>
                  ))}
                </div>
              </motion.div>
            </div>
          )}

          {/* 消息列表 */}
          {hasMessages && (
            <div className="flex-1 flex flex-col justify-start pt-4">
              {msgs.map(msg => (
                <motion.div key={msg.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                  className={cn("mb-4", msg.role === "user" && "flex justify-end")}>

                  {msg.role === "user" ? (
                    <div className="flex flex-col items-end gap-0.5">
                      <div className="bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%] text-[14px] shadow-sm">{msg.text}</div>
                      <span className="text-[10px] text-gray-400 px-1">{formatTime(msg.timestamp)}</span>
                    </div>
                  ) : msg.steps !== undefined ? (
                    <WorkCard steps={msg.steps} html={msg.html} isActive={working && msg.id === msgs[msgs.length - 1]?.id}
                      currentAgent={curAgent} elapsed={elapsed} timestamp={msg.timestamp} />
                  ) : msg.role === "system" ? (
                    <div className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{msg.text}</div>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      {msg.text.length > 200 ? (
                        <ContentCard content={msg.text} />
                      ) : (
                        <div className="text-[14px] text-gray-600 leading-relaxed whitespace-pre-line px-1">{msg.text}</div>
                      )}
                      <span className="text-[10px] text-gray-400 px-1">{formatTime(msg.timestamp)}</span>
                    </div>
                  )}
                </motion.div>
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>
      </main>

      {/* ─── 输入框 ─── */}
      <div className="fixed bottom-0 inset-x-0 bg-gradient-to-t from-[#F7F7F8] via-[#F7F7F8]/95 to-transparent pt-4 pb-4 px-5 z-40">
        <div className="max-w-[720px] mx-auto relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onCompositionStart={() => { composingRef.current = true }}
            onCompositionEnd={e => { composingRef.current = false; setInput((e.target as HTMLTextAreaElement).value) }}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); send() } }}
            placeholder="描述你想创建的东西..."
            rows={1}
            className="w-full bg-white border border-gray-200 rounded-2xl px-5 py-3.5 pr-14 text-[15px] text-gray-800 resize-none outline-none min-h-[52px] max-h-[120px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] focus:shadow-[0_2px_12px_rgba(0,0,0,0.08),0_0_0_3px_rgba(99,102,241,0.12)] focus:border-indigo-300 transition-all placeholder:text-gray-400"
          />
          <button onClick={() => send()} disabled={!input.trim()}
            className={cn("absolute right-3 bottom-3 w-9 h-9 rounded-xl flex items-center justify-center transition-all",
              input.trim() ? "bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm" : "bg-gray-100 text-gray-300 cursor-not-allowed")}>
            <Send size={16} />
          </button>
        </div>
      </div>

      {/* ─── 设置弹窗 ─── */}
      <AnimatePresence>
        {showSettings && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/15 backdrop-blur-sm z-50 flex items-center justify-center"
            onClick={() => setShowSettings(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl p-6 w-[420px] shadow-xl border border-gray-100" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-5">
                <h3 className="font-semibold text-gray-900 text-[15px]">模型设置</h3>
                <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
              </div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">切换模型</label>
              <select value={model} onChange={e => setModel(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-indigo-400 mb-4 cursor-pointer">
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowSettings(false)} className="px-4 py-2 text-sm text-gray-500 bg-gray-100 rounded-lg hover:bg-gray-200">取消</button>
                <button onClick={async () => {
                  try {
                    const r = await fetch(`http://${API_HOST}/api/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
                    const d = await r.json();
                    if (d.status === "ok") { setModel(d.model); setShowSettings(false); }
                  } catch { alert("保存失败") }
                }} className="px-4 py-2 text-sm text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">保存</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ═══ WorkCard — Builder工作进度+产出物预览 ═══ */
function WorkCard({ steps, html, isActive, currentAgent, elapsed, timestamp }: {
  steps: StepInfo[]; html?: string; isActive: boolean; currentAgent: string; elapsed: number; timestamp: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [showCode, setShowCode] = useState(false);
  const [blobUrl, setBlobUrl] = useState("");

  useEffect(() => {
    if (html) { const u = URL.createObjectURL(new Blob([html], { type: "text/html" })); setBlobUrl(u); return () => URL.revokeObjectURL(u) }
  }, [html]);

  const LABELS: Record<string, string> = { builder: "Builder 编码", tester: "Tester 验证", planner: "Planner 规划" };
  const doneSteps = steps.filter(s => s.done);

  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
      {/* 头部 */}
      <button onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center gap-2.5 hover:bg-gray-50/50 transition-colors">
        {isActive ? <Loader2 size={15} className="text-indigo-500 animate-spin shrink-0" />
          : <div className="w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center shrink-0"><Check size={11} className="text-emerald-600" /></div>}
        <span className="text-[13px] font-medium text-gray-700 flex-1 text-left">
          {isActive ? `${LABELS[currentAgent] || currentAgent || "处理"}中...` : `完成 · ${doneSteps.length} 步`}
        </span>
        <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
          <Clock size={11} />
          <span>{isActive ? `${elapsed}s` : `${new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`}</span>
        </div>
        <ChevronDown size={14} className={cn("text-gray-400 transition-transform", !expanded && "-rotate-90")} />
      </button>

      {/* 步骤 */}
      {expanded && doneSteps.length > 0 && (
        <div className="border-t border-gray-100 px-4 py-2">
          {doneSteps.map((s, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5">
              <Check size={12} className="text-emerald-500 shrink-0" />
              <span className="text-xs text-gray-600 font-medium">{LABELS[s.agent] || s.agent}</span>
              <span className="text-xs text-gray-400 truncate flex-1 text-right">{s.summary}</span>
            </div>
          ))}
          {isActive && (
            <div className="flex items-center gap-2 py-1.5">
              <Loader2 size={12} className="text-indigo-500 animate-spin" />
              <span className="text-xs text-indigo-600 font-medium">{LABELS[currentAgent] || "处理中"}...</span>
            </div>
          )}
        </div>
      )}

      {/* 产出物预览 */}
      {html && (
        <div className="border-t border-gray-100">
          <div className="px-4 py-2.5 flex items-center gap-3">
            <button onClick={() => { setShowPreview(!showPreview); setShowCode(false); }}
              className={cn("text-xs font-medium flex items-center gap-1 transition-colors",
                showPreview ? "text-indigo-600" : "text-gray-500 hover:text-indigo-600")}>
              <Eye size={12} />{showPreview ? "收起预览" : "预览"}
            </button>
            <button onClick={() => { setShowCode(!showCode); setShowPreview(false); }}
              className={cn("text-xs font-medium flex items-center gap-1 transition-colors",
                showCode ? "text-indigo-600" : "text-gray-500 hover:text-indigo-600")}>
              <Code2 size={12} />{showCode ? "收起代码" : "代码"}
            </button>
            {blobUrl && (
              <a href={blobUrl} target="_blank" rel="noopener"
                className="text-[11px] text-gray-400 hover:text-indigo-600 flex items-center gap-0.5 ml-auto">
                新窗口 <ExternalLink size={10} />
              </a>
            )}
          </div>
          {showPreview && blobUrl && (
            <iframe src={blobUrl} className="w-full h-[400px] border-t border-gray-100 bg-white" />
          )}
          {showCode && (
            <pre className="w-full max-h-[300px] overflow-auto border-t border-gray-100 px-4 py-3 text-[11px] text-gray-600 font-mono bg-gray-50 whitespace-pre-wrap">
              {html.slice(0, 3000)}{html.length > 3000 ? "\n..." : ""}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

/* ═══ ContentCard — 长内容 ═══ */
function ContentCard({ content }: { content: string }) {
  const [collapsed, setCollapsed] = useState(content.length > 800);
  const rendered = content
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.+)$/gm, '<h3 class="text-[15px] font-semibold text-gray-800 mt-4 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-[17px] font-semibold text-gray-900 mt-5 mb-2">$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc text-gray-600">$1</li>')
    .replace(/\n\n/g, '<div class="h-2"></div>').replace(/\n/g, '<br/>');
  return (
    <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
      <div className="px-5 py-4">
        <div className={cn("text-[14px] text-gray-700 leading-relaxed", collapsed && "max-h-[250px] overflow-hidden")}
          style={collapsed ? { maskImage: "linear-gradient(black 60%, transparent)", WebkitMaskImage: "linear-gradient(black 60%, transparent)" } : {}}
          dangerouslySetInnerHTML={{ __html: rendered }} />
      </div>
      {content.length > 800 && (
        <button onClick={() => setCollapsed(!collapsed)}
          className="w-full px-5 py-2 text-xs font-medium text-indigo-600 border-t border-gray-100 hover:bg-gray-50">
          {collapsed ? "展开全部 ▼" : "收起 ▲"}
        </button>
      )}
    </div>
  );
}
