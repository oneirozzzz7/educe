"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, Sparkles, ChevronDown, ChevronRight, ExternalLink,
  Check, Loader2, Settings, X,
} from "lucide-react";
import { createWS, AGENTS, API_HOST, type ServerMessage, type AgentId } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  steps?: StepInfo[];
  html?: string;
}

interface StepInfo { agent: AgentId; summary: string; done: boolean }

const AL: Record<string, string> = {
  project_manager: "规划", product_manager: "设计", architect: "架构",
  engineer: "编码", reviewer: "审查", crowd_user: "测试", memory_keeper: "沉淀",
};

const TEMPLATES = [
  ["🍅", "番茄钟", "帮我做一个番茄钟，25分钟倒计时，简洁美观"],
  ["🔧", "JSON工具", "做一个JSON格式化工具，支持语法高亮和错误提示"],
  ["🎮", "小游戏", "做一个贪吃蛇网页游戏"],
  ["📝", "编辑器", "做一个Markdown实时预览编辑器"],
  ["🧮", "计算器", "做一个科学计算器"],
];

export default function Page() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  const [curAgent, setCurAgent] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [settingsUrl, setSettingsUrl] = useState("");
  const [settingsKey, setSettingsKey] = useState("");

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const hasMessages = msgs.length > 0 || working;

  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    const ws = createWS(sid);
    wsRef.current = ws;
    ws.onConnect(() => { setConnected(true); fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => setModel(d.model || "")) });
    ws.onDisconnect(() => setConnected(false));
    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "status") {
        if (msg.content === "processing") {
          if (workingRef.current) return;
          workingRef.current = true;
          setWorking(true); setCurAgent("");
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: "", steps: [] }]);
        } else if (msg.content === "done") {
          workingRef.current = false;
          setWorking(false);
        }
      } else if (msg.type === "agent_message" && msg.msg_type !== "handoff") {
        if (!workingRef.current) {
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: msg.content }]);
        } else {
          setCurAgent(msg.sender);
          setMsgs(p => {
            const last = p[p.length - 1];
            if (last?.steps !== undefined) {
              const steps = [...(last.steps || []), { agent: msg.sender, summary: msg.summary || "", done: true }];
              return [...p.slice(0, -1), { ...last, steps, html: extractHtml(msg.content) || last.html }];
            }
            return p;
          });
        }
      } else if (msg.type === "chunk") setCurAgent(msg.sender);
      else if (msg.type === "error") { setWorking(false); setMsgs(p => [...p, { id: Date.now().toString(), role: "system", text: msg.content }]) }
    });
    return () => ws.close();
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [msgs, working]);

  function extractHtml(c: string) {
    const m = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?)```/) || c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    return m ? m[1] : undefined;
  }

  function send(text?: string) {
    const t = (text || input).trim();
    if (!t) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) {
      alert("未连接到后端，请确保 deepforge web 已启动 (端口7860)");
      return;
    }
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: t }]);
    w.send(t);
    setInput("");
  }

  const composingRef = useRef(false);

  const inputEl = (
    <div className="relative w-full">
      <textarea
        ref={inputRef}
        value={input}
        onChange={e => setInput(e.target.value)}
        onCompositionStart={() => { composingRef.current = true }}
        onCompositionEnd={(e) => { composingRef.current = false; setInput((e.target as HTMLTextAreaElement).value) }}
        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); send() } }}
        placeholder="做一个番茄钟、一个网页游戏、一个数据看板..."
        rows={1}
        className="w-full bg-white border border-gray-300/70 rounded-2xl px-5 py-3.5 pr-14 text-[15px] text-gray-800 resize-none outline-none min-h-[52px] max-h-[120px] shadow-[0_4px_20px_rgba(0,0,0,0.08)] focus:shadow-[0_4px_20px_rgba(0,0,0,0.1),0_0_0_3px_rgba(99,102,241,0.15)] focus:border-brand/50 transition-all placeholder:text-gray-400"
      />
      <button
        onClick={() => send()}
        disabled={!input.trim()}
        className={cn(
          "absolute right-3 bottom-3 w-9 h-9 rounded-xl flex items-center justify-center transition-all",
          input.trim() ? "bg-brand hover:bg-brand-hover text-white shadow-sm" : "bg-gray-100 text-gray-300 cursor-not-allowed"
        )}
      >
        <Send size={16} />
      </button>
    </div>
  );

  return (
    <div className="h-screen flex flex-col bg-[#F5F5F7]">
      {/* ─── Nav ─── */}
      <nav className="h-12 px-5 flex items-center bg-white/80 backdrop-blur-xl border-b border-gray-200/60 shrink-0 sticky top-0 z-50">
        <span className="text-[15px] font-bold tracking-tight">
          Deep<span className="bg-gradient-to-r from-brand to-purple-500 bg-clip-text text-transparent">Forge</span>
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-2.5">
          <div className={cn("flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full", connected ? "text-gray-500 bg-gray-100/80 border border-gray-200/60" : "text-red-500 bg-red-50 border border-red-200")}>
            <span className={cn("w-1.5 h-1.5 rounded-full", connected ? "bg-emerald-500" : "bg-red-500")} />
            {model || "..."}
          </div>
          <button onClick={() => {
            setShowSettings(true);
            fetch(`http://${API_HOST}/api/models`).then(r => r.json()).then(d => setModels(d.models || [])).catch(() => {});
            fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => { setSettingsUrl(d.base_url || ""); setModel(d.model || "") }).catch(() => {});
          }} className="w-7 h-7 rounded-lg border border-gray-200/60 bg-white/60 flex items-center justify-center text-gray-400 hover:text-brand hover:border-brand/30 transition-colors">
            <Settings size={13} />
          </button>
        </div>
      </nav>

      {/* ─── Empty State: 居中展示，输入框是核心 ─── */}
      {!hasMessages && (
        <div className="flex-1 flex items-center justify-center px-5">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-[600px] text-center">
            <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-gradient-to-br from-brand to-purple-500 flex items-center justify-center shadow-lg shadow-brand/20">
              <Sparkles className="text-white" size={24} />
            </div>
            <h1 className="text-[28px] font-semibold text-gray-900 tracking-tight">What will you build?</h1>
            <p className="mt-1.5 text-[14px] text-gray-400">Idea → Product, powered by multi-agent collaboration</p>

            <div className="mt-8 mb-5">
              {inputEl}
            </div>

            <div className="flex flex-wrap gap-2 justify-center">
              {TEMPLATES.map(([icon, label, prompt]) => (
                <button key={label as string} onClick={() => send(prompt as string)}
                  className="flex items-center gap-1.5 px-3.5 py-2 text-[13px] text-gray-500 bg-white border border-gray-200/80 rounded-full hover:border-brand/40 hover:text-brand shadow-sm hover:shadow transition-all">
                  <span>{icon}</span>{label}
                </button>
              ))}
            </div>
          </motion.div>
        </div>
      )}

      {/* ─── Chat State: 对话流 + 底部固定输入 ─── */}
      {hasMessages && (
        <>
          <main className="flex-1 overflow-y-auto">
            <div className="max-w-[700px] mx-auto px-5 py-6 pb-28">
              {msgs.map(msg => (
                <motion.div key={msg.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn("mb-5", msg.role === "user" && "flex justify-end")}>
                  {msg.role === "user" ? (
                    <div className="bg-brand text-white rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%] text-[14px] shadow-sm">{msg.text}</div>
                  ) : msg.steps !== undefined ? (
                    <WorkCard steps={msg.steps} html={msg.html} isActive={working && msg.id === msgs[msgs.length - 1]?.id} currentAgent={curAgent} />
                  ) : msg.role === "system" ? (
                    <div className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{msg.text}</div>
                  ) : (
                    <div className="text-[14px] text-gray-600 leading-relaxed whitespace-pre-line px-1">{msg.text}</div>
                  )}
                </motion.div>
              ))}
              <div ref={endRef} />
            </div>
          </main>

          <div className="fixed bottom-0 inset-x-0 bg-gradient-to-t from-[#F5F5F7] via-[#F5F5F7]/95 to-transparent pt-4 pb-4 px-5 z-40">
            <div className="max-w-[700px] mx-auto">
              {inputEl}
            </div>
          </div>
        </>
      )}

      {/* Settings */}
      <AnimatePresence>
        {showSettings && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-black/15 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowSettings(false)}>
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="bg-white rounded-2xl p-6 w-[420px] shadow-xl border border-gray-100" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-5">
                <h3 className="font-semibold text-gray-900 text-[15px]">模型设置</h3>
                <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
              </div>

              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">切换模型</label>
              <select
                value={model}
                onChange={e => setModel(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-brand mb-4 cursor-pointer"
              >
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>

              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">API Base URL</label>
              <input
                value={settingsUrl}
                onChange={e => setSettingsUrl(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-brand mb-4"
                placeholder="https://api.example.com/v1"
              />

              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">API Key</label>
              <input
                type="password"
                value={settingsKey}
                onChange={e => setSettingsKey(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-brand mb-1"
                placeholder="留空则保留当前Key"
              />
              <p className="text-[11px] text-gray-400 mb-5">仅保存在本地，不会上传</p>

              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowSettings(false)} className="px-4 py-2 text-sm text-gray-500 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">取消</button>
                <button
                  onClick={async () => {
                    const body: Record<string, string> = { model };
                    if (settingsUrl) body.base_url = settingsUrl;
                    if (settingsKey) body.api_key = settingsKey;
                    try {
                      const r = await fetch(`http://${API_HOST}/api/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
                      const d = await r.json();
                      if (d.status === "ok") { setModel(d.model); setShowSettings(false); }
                    } catch (e) { alert("保存失败") }
                  }}
                  className="px-4 py-2 text-sm text-white bg-brand rounded-lg hover:bg-brand-hover transition-colors"
                >保存</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ═══ WorkCard ═══ */
function WorkCard({ steps, html, isActive, currentAgent }: { steps: StepInfo[]; html?: string; isActive: boolean; currentAgent: string }) {
  const [expanded, setExpanded] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [blobUrl, setBlobUrl] = useState("");

  useEffect(() => {
    if (html) { const u = URL.createObjectURL(new Blob([html], { type: "text/html" })); setBlobUrl(u); return () => URL.revokeObjectURL(u) }
  }, [html]);

  return (
    <div className="bg-white border border-gray-200/60 rounded-2xl overflow-hidden shadow-sm">
      <button onClick={() => setExpanded(!expanded)} className="w-full px-4 py-3 flex items-center gap-2.5 hover:bg-gray-50/50 transition-colors">
        {isActive ? <Loader2 size={14} className="text-brand animate-spin" /> : <div className="w-4 h-4 rounded-full bg-emerald-100 flex items-center justify-center"><Check size={10} className="text-emerald-600" /></div>}
        <span className="text-[13px] font-medium text-gray-700 flex-1 text-left">{isActive ? `${AL[currentAgent] || "处理"}中...` : `完成 · ${steps.length} 步`}</span>
        <ChevronDown size={14} className={cn("text-gray-400 transition-transform", !expanded && "-rotate-90")} />
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t border-gray-100">
            <div className="px-4 py-2">
              {steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2 py-1.5">
                  <div className="w-4 h-4 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center"><Check size={9} className="text-emerald-500" /></div>
                  <span className="text-xs text-gray-600">{AL[s.agent] || s.agent}</span>
                  <span className="text-xs text-gray-400 truncate flex-1 text-right">{s.summary}</span>
                </div>
              ))}
              {isActive && (
                <div className="flex items-center gap-2 py-1.5">
                  <Loader2 size={13} className="text-brand animate-spin" />
                  <span className="text-xs text-brand font-medium">{AL[currentAgent] || "处理中"}...</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {html && (
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="flex items-center gap-3">
            <button onClick={() => setShowPreview(!showPreview)} className="text-xs font-medium text-brand hover:text-brand-hover flex items-center gap-1">
              {showPreview ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {showPreview ? "收起预览" : "查看产出物"}
            </button>
            {blobUrl && <a href={blobUrl} target="_blank" rel="noopener" className="text-[11px] text-gray-400 hover:text-gray-600 flex items-center gap-0.5">新窗口 <ExternalLink size={10} /></a>}
          </div>
          <AnimatePresence>
            {showPreview && blobUrl && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 420, opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <iframe src={blobUrl} className="w-full h-[400px] mt-3 border border-gray-200/60 rounded-xl bg-white" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
