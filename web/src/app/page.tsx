"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Sparkles,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Check,
  Loader2,
  Settings,
  Plus,
  Clock,
  X,
} from "lucide-react";
import { createWS, AGENTS, API_HOST, type ServerMessage, type AgentId } from "@/lib/ws";
import { cn } from "@/lib/utils";

/* ═══════ Types ═══════ */
interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  steps?: StepInfo[];
  html?: string;
  ts: number;
}

interface StepInfo {
  agent: AgentId;
  summary: string;
  done: boolean;
}

const AGENT_LABELS: Record<string, string> = {
  project_manager: "规划",
  product_manager: "设计",
  architect: "架构",
  engineer: "编码",
  reviewer: "审查",
  crowd_user: "测试",
  memory_keeper: "沉淀",
};

/* ═══════ Page ═══════ */
export default function Page() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [working, setWorking] = useState(false);
  const [curAgent, setCurAgent] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      setConnected(true);
      fetch(`http://${API_HOST}/api/status`)
        .then((r) => r.json())
        .then((d) => setModel(d.model || ""));
    });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "status") {
        if (msg.content === "processing") {
          setWorking(true);
          setCurAgent("");
          setMsgs((p) => [
            ...p,
            {
              id: Date.now().toString(),
              role: "assistant",
              text: "",
              steps: [],
              ts: Date.now(),
            },
          ]);
        } else if (msg.content === "done") {
          setWorking(false);
        }
      } else if (msg.type === "agent_message" && msg.msg_type !== "handoff") {
        if (!working) {
          setMsgs((p) => [
            ...p,
            { id: Date.now().toString(), role: "assistant", text: msg.content, ts: Date.now() },
          ]);
        } else {
          setCurAgent(msg.sender);
          setMsgs((p) => {
            const last = p[p.length - 1];
            if (last?.steps !== undefined) {
              const steps = [...(last.steps || [])];
              steps.push({ agent: msg.sender, summary: msg.summary || "", done: true });
              const html = extractHtml(msg.content) || last.html;
              return [...p.slice(0, -1), { ...last, steps, html }];
            }
            return p;
          });
        }
      } else if (msg.type === "chunk") {
        setCurAgent(msg.sender);
      } else if (msg.type === "error") {
        setWorking(false);
        setMsgs((p) => [
          ...p,
          { id: Date.now().toString(), role: "system", text: msg.content, ts: Date.now() },
        ]);
      }
    });

    return () => ws.close();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, working]);

  function extractHtml(c: string) {
    const m =
      c.match(/```filepath:[^\n]+\.html\n([\s\S]*?)```/) ||
      c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    return m ? m[1] : undefined;
  }

  function send() {
    const t = input.trim();
    if (!t || !wsRef.current) return;
    setMsgs((p) => [...p, { id: Date.now().toString(), role: "user", text: t, ts: Date.now() }]);
    wsRef.current.send(t);
    setInput("");
    inputRef.current?.focus();
  }

  const empty = msgs.length === 0 && !working;

  return (
    <div className="h-screen flex flex-col">
      {/* ─── Nav ─── */}
      <nav className="h-13 px-6 flex items-center bg-white border-b border-gray-100 shrink-0">
        <span className="text-[15px] font-bold tracking-tight text-gray-900">
          Deep
          <span className="bg-gradient-to-r from-brand to-purple-500 bg-clip-text text-transparent">
            Forge
          </span>
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border",
              connected
                ? "text-gray-500 bg-gray-50 border-gray-200"
                : "text-red-500 bg-red-50 border-red-200"
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                connected ? "bg-emerald-500" : "bg-red-500"
              )}
            />
            {model || "..."}
          </div>
          <button
            onClick={() => setShowSettings(true)}
            className="w-8 h-8 rounded-lg border border-gray-200 flex items-center justify-center text-gray-400 hover:text-brand hover:border-brand-100 transition-colors"
          >
            <Settings size={14} />
          </button>
        </div>
      </nav>

      {/* ─── Chat ─── */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-[720px] mx-auto px-5 py-8 pb-32">
          {/* Empty state */}
          <AnimatePresence>
            {empty && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-center justify-center min-h-[55vh] text-center gap-5"
              >
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand to-purple-500 flex items-center justify-center shadow-lg shadow-brand/20">
                  <Sparkles className="text-white" size={24} />
                </div>
                <div>
                  <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">
                    What will you build?
                  </h1>
                  <p className="mt-1.5 text-sm text-gray-500">
                    描述你想创建的东西，7个AI Agent协作帮你完成
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 justify-center mt-1">
                  {[
                    ["🍅", "番茄钟", "帮我做一个番茄钟，25分钟倒计时"],
                    ["🔧", "JSON工具", "做一个JSON格式化工具，语法高亮"],
                    ["🎮", "小游戏", "做一个贪吃蛇游戏"],
                    ["📝", "编辑器", "做一个Markdown实时预览编辑器"],
                    ["🧮", "计算器", "做一个科学计算器"],
                  ].map(([icon, label, prompt]) => (
                    <button
                      key={label}
                      onClick={() => {
                        setInput(prompt);
                        setTimeout(send, 0);
                      }}
                      className="flex items-center gap-1.5 px-3.5 py-2 text-[13px] text-gray-600 bg-white border border-gray-200 rounded-full hover:border-brand hover:text-brand shadow-subtle hover:shadow-card transition-all"
                    >
                      <span>{icon}</span>
                      {label}
                    </button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Messages */}
          {msgs.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className={cn("mb-6", msg.role === "user" && "flex justify-end")}
            >
              {msg.role === "user" ? (
                <div className="bg-brand text-white rounded-2xl rounded-br-sm px-4 py-2.5 max-w-[75%] text-[14px] shadow-subtle">
                  {msg.text}
                </div>
              ) : msg.steps !== undefined ? (
                <WorkCard
                  steps={msg.steps}
                  html={msg.html}
                  isActive={working && msg.id === msgs[msgs.length - 1]?.id}
                  currentAgent={curAgent}
                />
              ) : msg.role === "system" ? (
                <div className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
                  {msg.text}
                </div>
              ) : (
                <div className="text-[14px] text-gray-600 leading-relaxed whitespace-pre-line">
                  {msg.text}
                </div>
              )}
            </motion.div>
          ))}

          <div ref={endRef} />
        </div>
      </main>

      {/* ─── Input ─── */}
      <div className="fixed bottom-0 inset-x-0 bg-gradient-to-t from-[#fafafa] via-[#fafafa] to-transparent pt-6 pb-5 px-5 z-40">
        <div className="max-w-[720px] mx-auto relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="描述你想创建的东西..."
            rows={1}
            className="w-full bg-white border border-gray-200 rounded-xl px-4 py-3 pr-12 text-[14px] text-gray-800 resize-none outline-none min-h-[48px] max-h-[120px] shadow-input focus:shadow-input-focus focus:border-brand transition-all placeholder:text-gray-400"
          />
          <button
            onClick={send}
            disabled={!input.trim() || !connected}
            className={cn(
              "absolute right-2 bottom-2 w-8 h-8 rounded-lg flex items-center justify-center transition-all",
              input.trim() && connected
                ? "bg-brand hover:bg-brand-hover text-white shadow-subtle"
                : "bg-gray-100 text-gray-300 cursor-not-allowed"
            )}
          >
            <Send size={15} />
          </button>
        </div>
      </div>

      {/* Settings modal placeholder */}
      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 backdrop-blur-sm z-50 flex items-center justify-center"
            onClick={() => setShowSettings(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl p-6 w-[400px] shadow-xl border border-gray-100"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">设置</h3>
                <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-gray-600">
                  <X size={16} />
                </button>
              </div>
              <p className="text-sm text-gray-500">模型: {model}</p>
              <p className="text-xs text-gray-400 mt-2">更多设置功能开发中...</p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ═══════ Work Card ═══════ */
function WorkCard({
  steps,
  html,
  isActive,
  currentAgent,
}: {
  steps: StepInfo[];
  html?: string;
  isActive: boolean;
  currentAgent: string;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showPreview, setShowPreview] = useState(false);
  const [blobUrl, setBlobUrl] = useState("");

  useEffect(() => {
    if (html) {
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      setBlobUrl(url);
      return () => URL.revokeObjectURL(url);
    }
  }, [html]);

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-card">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center gap-2.5 hover:bg-gray-50 transition-colors"
      >
        {isActive ? (
          <Loader2 size={14} className="text-brand animate-spin" />
        ) : (
          <Check size={14} className="text-emerald-500" />
        )}
        <span className="text-[13px] font-medium text-gray-700 flex-1 text-left">
          {isActive
            ? `${AGENT_LABELS[currentAgent] || "处理"}中...`
            : `完成 · ${steps.length} 步`}
        </span>
        <ChevronDown
          size={14}
          className={cn("text-gray-400 transition-transform", !expanded && "-rotate-90")}
        />
      </button>

      {/* Steps */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            className="overflow-hidden border-t border-gray-100"
          >
            <div className="px-4 py-2">
              {steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2 py-1.5">
                  <div className="w-4 h-4 rounded-full bg-emerald-50 border border-emerald-200 flex items-center justify-center">
                    <Check size={10} className="text-emerald-500" />
                  </div>
                  <span className="text-xs text-gray-600">
                    {AGENT_LABELS[s.agent] || s.agent}
                  </span>
                  <span className="text-xs text-gray-400 truncate flex-1 text-right">
                    {s.summary}
                  </span>
                </div>
              ))}
              {isActive && (
                <div className="flex items-center gap-2 py-1.5">
                  <Loader2 size={14} className="text-brand animate-spin" />
                  <span className="text-xs text-brand font-medium">
                    {AGENT_LABELS[currentAgent] || "处理中"}...
                  </span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview */}
      {html && (
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowPreview(!showPreview)}
              className="text-xs font-medium text-brand hover:text-brand-hover flex items-center gap-1"
            >
              {showPreview ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {showPreview ? "收起预览" : "查看产出物"}
            </button>
            {blobUrl && (
              <a
                href={blobUrl}
                target="_blank"
                rel="noopener"
                className="text-[11px] text-gray-400 hover:text-gray-600 flex items-center gap-0.5"
              >
                新窗口 <ExternalLink size={10} />
              </a>
            )}
          </div>
          <AnimatePresence>
            {showPreview && blobUrl && (
              <motion.div initial={{ height: 0 }} animate={{ height: 420 }} exit={{ height: 0 }} className="overflow-hidden">
                <iframe
                  src={blobUrl}
                  className="w-full h-[400px] mt-3 border border-gray-200 rounded-lg bg-white"
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
