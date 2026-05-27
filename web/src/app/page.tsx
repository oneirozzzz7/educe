"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { createWS, AGENTS, type ServerMessage, type AgentId } from "@/lib/ws";
import { TopBar } from "@/components/top-bar";
import { HomeView } from "@/components/home-view";
import { WorkView } from "@/components/work-view";
import { ResultView } from "@/components/result-view";

type AppState = "home" | "working" | "done" | "chat";

interface StepState {
  id: AgentId;
  status: "wait" | "active" | "done";
  summary: string;
  time: string;
}

export default function Page() {
  const [state, setState] = useState<AppState>("home");
  const [chatReply, setChatReply] = useState("");
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
      fetch(`http://${process.env.NEXT_PUBLIC_API_HOST || "localhost:7860"}/api/status`)
        .then((r) => r.json())
        .then((d) => setModel(d.model || ""));
    });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "agent_message") {
        if (state === "home" || state === "chat") {
          setChatReply(msg.content);
          setState("chat");
          return;
        }
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
          if (m) {
            setHtml(m[1]);
            setCode(m[1]);
          }
        }
      } else if (msg.type === "status") {
        if (msg.content === "processing") {
          setState("working");
          setSteps(() => {
            const s = initSteps();
            s[0].status = "active";
            return s;
          });
          setHtml("");
          setCode("");
          startRef.current = Date.now();
          timerRef.current = setInterval(() => {
            setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
          }, 1000);
        } else if (msg.content === "done") {
          if (timerRef.current) clearInterval(timerRef.current);
          setState("done");
        }
      } else if (msg.type === "error") {
        if (timerRef.current) clearInterval(timerRef.current);
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
    wsRef.current.send(text.trim());
  }

  function newTask() {
    setState("home");
    setTask("");
    setChatReply("");
    setSteps(initSteps());
    setHtml("");
    setCode("");
    if (timerRef.current) clearInterval(timerRef.current);
    setElapsed(0);
  }

  return (
    <>
      <TopBar model={model} connected={connected} onNew={newTask} />
      <main className="flex-1 overflow-hidden flex flex-col">
        {state === "home" && <HomeView onSend={send} />}
        {state === "chat" && (
          <div className="flex-1 flex flex-col items-center justify-center px-5">
            <div className="max-w-lg w-full bg-surface rounded-xl border border-border p-6 mb-6">
              <p className="text-sm text-neutral-300 whitespace-pre-line">{chatReply}</p>
            </div>
            <div className="max-w-lg w-full">
              <HomeView onSend={(t) => { setChatReply(""); send(t); }} />
            </div>
          </div>
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
