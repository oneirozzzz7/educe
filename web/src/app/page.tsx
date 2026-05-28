"use client";

import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { Send } from "lucide-react";
import { Logo } from "@/components/logo";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { Sidebar } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";
import { WorkCard } from "@/components/work-card";
import { SettingsModal } from "@/components/settings-modal";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  steps?: { agent: string; summary: string; done: boolean }[];
  html?: string;
  timestamp: number;
}

export default function Page() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [working, setWorking] = useState(false);
  const [curAgent, setCurAgent] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const workingRef = useRef(false);
  const composingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);

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
          setWorking(true); setCurAgent(""); setElapsed(0);
          startRef.current = Date.now();
          timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: "", steps: [], timestamp: Date.now() }]);
        } else if (msg.content === "idle") {
          workingRef.current = false; setWorking(false);
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
              return [...p.slice(0, -1), { ...last, steps, html: extractHtml(msg.content) || last.html, text: msg.content }];
            }
            return p;
          });
        }
      } else if (msg.type === "chunk") {
        setCurAgent(msg.sender);
      } else if (msg.type === "error") {
        workingRef.current = false; setWorking(false);
        if (timerRef.current) clearInterval(timerRef.current);
        setMsgs(p => [...p, { id: Date.now().toString(), role: "system", text: msg.content, timestamp: Date.now() }]);
      }
    });

    return () => ws.close();
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [msgs, elapsed]);

  function extractHtml(c: string) {
    // 方法1: filepath格式——贪婪匹配到</html>
    const m1 = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?<\/html>)/i);
    if (m1) return m1[1];
    // 方法2: 裸HTML
    const m2 = c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    if (m2) return m2[1];
    return undefined;
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

  function fmtTime(ts: number) {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  const hasMessages = msgs.length > 0;

  return (
    <div className="h-screen flex" style={{ background: "var(--bg)" }}>
      {/* 侧栏 */}
      <Sidebar collapsed={sidebarCollapsed} onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onNewTask={() => { setMsgs([]); setWorking(false); }}
        onTaskSelect={(task) => { setMsgs([{ id: task.id, role: "user", text: task.request, timestamp: task.created_at * 1000 }]); }} />

      {/* 主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar model={model} connected={connected} onOpenSettings={() => setShowSettings(true)} />

        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[740px] mx-auto px-5 py-6 pb-28 min-h-full flex flex-col">

            {/* 空状态 */}
            {!hasMessages && !working && (
              <div className="flex-1 flex items-center justify-center">
                <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="text-center w-full max-w-[560px]">
                  <div className="mx-auto mb-5">
                  <Logo size={56} />
                </div>
                  <h1 className="text-2xl font-semibold tracking-tight mb-1.5" style={{ color: "var(--text)" }}>What will you build?</h1>
                  <p className="text-sm mb-8" style={{ color: "var(--text-3)" }}>Idea → Product, powered by multi-agent collaboration</p>
                  <div className="flex flex-wrap gap-2 justify-center">
                    {[["🍅", "番茄钟"], ["🔧", "JSON工具"], ["🎮", "小游戏"], ["📝", "编辑器"], ["🧮", "计算器"]].map(([icon, label]) => (
                      <button key={label} onClick={() => send(`做一个${label}`)}
                        className="flex items-center gap-1.5 px-3.5 py-2 text-[13px] rounded-full border transition-all hover:shadow-sm"
                        style={{ background: "var(--bg-elevated)", borderColor: "var(--border)", color: "var(--text-2)" }}>
                        <span>{icon}</span>{label}
                      </button>
                    ))}
                  </div>
                </motion.div>
              </div>
            )}

            {/* 消息列表 */}
            {(hasMessages || working) && (
              <div className="flex flex-col gap-4 pt-2">
                {msgs.map(msg => (
                  <motion.div key={msg.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    className={cn("", msg.role === "user" && "flex justify-end")}>

                    {msg.role === "user" ? (
                      <div className="flex flex-col items-end gap-0.5 max-w-[75%]">
                        <div className="rounded-2xl rounded-br-sm px-4 py-2.5 text-[14px] text-white shadow-sm" style={{ background: "var(--brand)" }}>{msg.text}</div>
                        <span className="text-[10px] px-1" style={{ color: "var(--text-4)" }}>{fmtTime(msg.timestamp)}</span>
                      </div>
                    ) : msg.steps !== undefined ? (
                      <WorkCard steps={msg.steps} html={msg.html} isActive={working && msg.id === msgs[msgs.length - 1]?.id}
                        currentAgent={curAgent} elapsed={elapsed} timestamp={msg.timestamp} />
                    ) : msg.role === "system" ? (
                      <div className="text-sm rounded-xl px-4 py-3" style={{ background: "var(--error-light)", color: "var(--error)", border: "1px solid var(--error)" }}>{msg.text}</div>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        <div className="text-[14px] leading-relaxed whitespace-pre-line px-1" style={{ color: "var(--text-2)" }}>{msg.text}</div>
                        <span className="text-[10px] px-1" style={{ color: "var(--text-4)" }}>{fmtTime(msg.timestamp)}</span>
                      </div>
                    )}
                  </motion.div>
                ))}
                <div ref={endRef} />
              </div>
            )}
          </div>
        </main>

        {/* 输入框 */}
        <div className="fixed bottom-0 right-0 pt-4 pb-4 px-5 z-40" style={{ left: sidebarCollapsed ? "48px" : "var(--sidebar-width)", background: `linear-gradient(transparent, var(--bg) 30%)` }}>
          <div className="max-w-[740px] mx-auto relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onCompositionStart={() => { composingRef.current = true }}
              onCompositionEnd={e => { composingRef.current = false; setInput((e.target as HTMLTextAreaElement).value) }}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); send() } }}
              placeholder="描述你想创建的东西..."
              rows={1}
              className="w-full rounded-2xl px-5 py-3.5 pr-14 text-[15px] resize-none outline-none min-h-[52px] max-h-[120px] transition-all"
              style={{
                background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text)",
                boxShadow: "var(--shadow-input)",
              }}
              onFocus={e => { e.target.style.borderColor = "var(--brand)"; e.target.style.boxShadow = "var(--shadow-input), 0 0 0 3px var(--brand-subtle)" }}
              onBlur={e => { e.target.style.borderColor = "var(--border)"; e.target.style.boxShadow = "var(--shadow-input)" }}
            />
            <button onClick={() => send()} disabled={!input.trim()}
              className={cn("absolute right-3 bottom-3 w-9 h-9 rounded-xl flex items-center justify-center transition-all",
                input.trim() ? "text-white shadow-sm" : "cursor-not-allowed")}
              style={{ background: input.trim() ? "var(--brand)" : "var(--bg-sunken)", color: input.trim() ? "white" : "var(--text-4)" }}>
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* 设置 */}
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} model={model} onModelChange={setModel} />
    </div>
  );
}
