"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { createWS, AGENTS, API_HOST, type ServerMessage, type AgentId } from "@/lib/ws";
import { TopBar } from "@/components/top-bar";
import { HomeView } from "@/components/home-view";
import { WorkView } from "@/components/work-view";
import { ResultView } from "@/components/result-view";

type AppState = "home" | "working" | "done";

interface StepState {
  id: AgentId;
  status: "wait" | "active" | "done";
  summary: string;
  time: string;
}

export default function Page() {
  const [state, setState] = useState<AppState>("home");
  const [chatMessages, setChatMessages] = useState<{role: string; content: string}[]>([]);
  const [task, setTask] = useState("");
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [steps, setSteps] = useState<StepState[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [html, setHtml] = useState("");
  const [code, setCode] = useState("");

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);

  const initSteps = useCallback((): StepState[] => {
    return AGENTS.map((a) => ({ id: a.id, status: "wait" as const, summary: "", time: "" }));
  }, []);

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
      if (msg.type === "agent_message") {
        if (msg.msg_type !== "handoff" && msg.summary) {
          setSteps((prev) => {
            const next = [...prev];
            const idx = next.findIndex((s) => s.id === msg.sender);
            if (idx >= 0) {
              next[idx] = { ...next[idx], status: "done", summary: msg.summary, time: elapsedStr() };
              if (idx + 1 < next.length) {
                next[idx + 1] = { ...next[idx + 1], status: "active" };
              }
            }
            return next;
          });
        }
        if (msg.has_files) {
          const m = msg.content.match(/```filepath:[^\n]+\.html\n([\s\S]*?)```/) ||
                    msg.content.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
          if (m) { setHtml(m[1]); setCode(m[1]); }
        }
      } else if (msg.type === "status") {
        if (msg.content === "processing") {
          setState("working");
          setSteps(() => { const s = initSteps(); s[0].status = "active"; return s; });
          setHtml(""); setCode("");
          startRef.current = Date.now();
          timerRef.current = setInterval(() => {
            setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
          }, 1000);
        } else if (msg.content === "done") {
          if (timerRef.current) clearInterval(timerRef.current);
          setState("done");
        } else if (msg.content === "chat_done") {
          // 闲聊完成——不改变state，消息已通过agent_message添加
        }
      } else if (msg.type === "error") {
        if (timerRef.current) clearInterval(timerRef.current);
      }

      // 所有agent_message都追加到聊天记录
      if (msg.type === "agent_message") {
        setChatMessages((prev) => [...prev, { role: "assistant", content: msg.content }]);
      }
    });

    return () => ws.close();
  }, [initSteps]);

  function elapsedStr() {
    return Math.floor((Date.now() - startRef.current) / 1000) + "s";
  }

  function send(text: string) {
    if (!text.trim() || !wsRef.current) return;
    setTask(text.trim());
    setChatMessages((prev) => [...prev, { role: "user", content: text.trim() }]);
    wsRef.current.send(text.trim());
  }

  function newTask() {
    setState("home");
    setTask("");
    setChatMessages([]);
    setSteps(initSteps());
    setHtml("");
    setCode("");
    if (timerRef.current) clearInterval(timerRef.current);
    setElapsed(0);
  }

  const showChat = state === "home" && chatMessages.length > 0;

  return (
    <>
      <TopBar model={model} connected={connected} onNew={newTask} />
      <main className="flex-1 overflow-hidden flex flex-col">
        {state === "home" && (
          showChat ? (
            <div className="flex-1 flex flex-col">
              <div className="flex-1 overflow-y-auto px-5 py-6 flex flex-col items-center gap-3">
                {chatMessages.map((m, i) => (
                  <div key={i} className={`max-w-xl w-full rounded-xl p-4 text-sm ${
                    m.role === "user"
                      ? "bg-accent/10 border border-accent/20 text-neutral-200 self-end"
                      : "bg-surface border border-border text-neutral-300"
                  }`}>
                    <p className="whitespace-pre-line">{m.content}</p>
                  </div>
                ))}
              </div>
              <div className="border-t border-border px-5 py-3 flex gap-2 items-end">
                <input
                  type="text"
                  placeholder="继续对话或描述你想创建的东西..."
                  className="flex-1 bg-surface border border-border-bright rounded-xl px-4 py-3 text-sm text-white outline-none focus:border-accent"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      const val = (e.target as HTMLInputElement).value.trim();
                      if (val) { send(val); (e.target as HTMLInputElement).value = ""; }
                    }
                  }}
                />
                <button
                  onClick={(e) => {
                    const input = (e.currentTarget.previousElementSibling as HTMLInputElement);
                    if (input.value.trim()) { send(input.value.trim()); input.value = ""; }
                  }}
                  className="w-10 h-10 rounded-full bg-accent flex items-center justify-center shrink-0"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                </button>
              </div>
            </div>
          ) : (
            <HomeView onSend={send} />
          )
        )}
        {state === "working" && (
          <WorkView task={task} steps={steps} elapsed={elapsed} onSend={send} />
        )}
        {state === "done" && (
          <ResultView task={task} steps={steps} elapsed={elapsed} html={html} code={code} onSend={send} onNew={newTask} />
        )}
      </main>
    </>
  );
}
