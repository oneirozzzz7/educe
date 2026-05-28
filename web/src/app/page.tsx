"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { createWS, AGENTS, API_HOST, type ServerMessage, type AgentId } from "@/lib/ws";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agentSteps?: AgentStep[];
  hasFiles?: boolean;
  html?: string;
  timestamp: number;
}

interface AgentStep {
  agent: AgentId;
  summary: string;
  status: "active" | "done";
}

export default function Page() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [isWorking, setIsWorking] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [currentAgent, setCurrentAgent] = useState("");

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const workingMsgRef = useRef<string>("");

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
        if (msg.content === "processing") {
          setIsWorking(true);
          setStreamingText("");
          setCurrentAgent("");
          workingMsgRef.current = "";
        } else if (msg.content === "done") {
          setIsWorking(false);
          if (workingMsgRef.current) {
            setMessages(prev => [...prev, {
              id: Date.now().toString(),
              role: "assistant",
              content: workingMsgRef.current,
              timestamp: Date.now(),
            }]);
            workingMsgRef.current = "";
            setStreamingText("");
          }
        } else if (msg.content === "chat_done") {
          // handled by agent_message
        }
      } else if (msg.type === "agent_message") {
        if (!isWorking) {
          // 闲聊回复
          setMessages(prev => [...prev, {
            id: Date.now().toString(),
            role: "assistant",
            content: msg.content,
            timestamp: Date.now(),
          }]);
        } else {
          // 工作中的Agent消息
          setCurrentAgent(msg.sender);
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant" && last.agentSteps) {
              // 更新现有工作卡片
              const steps = [...last.agentSteps];
              steps.push({ agent: msg.sender, summary: msg.summary || "", status: "done" });
              return [...prev.slice(0, -1), { ...last, agentSteps: steps, hasFiles: msg.has_files, html: extractHtml(msg.content) || last.html }];
            } else {
              // 创建新的工作卡片
              return [...prev, {
                id: Date.now().toString(),
                role: "assistant",
                content: "",
                agentSteps: [{ agent: msg.sender, summary: msg.summary || "", status: "done" }],
                hasFiles: msg.has_files,
                html: extractHtml(msg.content),
                timestamp: Date.now(),
              }];
            }
          });
          workingMsgRef.current = msg.content;
        }
      } else if (msg.type === "chunk") {
        setStreamingText(prev => prev + msg.content);
        setCurrentAgent(msg.sender);
      } else if (msg.type === "error") {
        setIsWorking(false);
        setMessages(prev => [...prev, { id: Date.now().toString(), role: "system", content: `Error: ${msg.content}`, timestamp: Date.now() }]);
      }
    });

    return () => ws.close();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  function extractHtml(content: string): string | undefined {
    const m = content.match(/```filepath:[^\n]+\.html\n([\s\S]*?)```/) || content.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    return m ? m[1] : undefined;
  }

  function send() {
    const text = input.trim();
    if (!text || !wsRef.current) return;
    setMessages(prev => [...prev, { id: Date.now().toString(), role: "user", content: text, timestamp: Date.now() }]);
    wsRef.current.send(text);
    setInput("");
  }

  return (
    <div className="h-screen flex flex-col bg-[#212121] text-[#ececec]">
      {/* Header */}
      <header className="h-12 flex items-center px-5 border-b border-[#2f2f2f] shrink-0">
        <span className="text-sm font-semibold text-[#b4b4b4]">DeepForge</span>
        <span className="ml-3 text-xs text-[#666] bg-[#2f2f2f] px-2 py-0.5 rounded">{model || "..."}</span>
        <div className="flex-1" />
        <div className={`w-2 h-2 rounded-full ${connected ? "bg-[#10a37f]" : "bg-red-500"}`} />
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          {messages.length === 0 && !isWorking && (
            <div className="text-center py-20">
              <h1 className="text-2xl font-semibold text-[#ececec] mb-2">What can I build for you?</h1>
              <p className="text-sm text-[#999] mb-8">Describe what you want, 7 AI agents collaborate to create it</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {["做一个番茄钟", "做一个JSON格式化工具", "做一个计算器", "做一个贪吃蛇游戏", "做一个Markdown编辑器"].map(t => (
                  <button key={t} onClick={() => { setInput(t); }} className="px-3 py-1.5 text-xs text-[#999] bg-[#2f2f2f] hover:bg-[#3a3a3a] rounded-full border border-[#3a3a3a] hover:border-[#555] transition-colors">
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} className={`mb-6 ${msg.role === "user" ? "flex justify-end" : ""}`}>
              {msg.role === "user" ? (
                <div className="bg-[#2f2f2f] rounded-2xl px-4 py-2.5 max-w-[80%] text-sm">
                  {msg.content}
                </div>
              ) : msg.agentSteps ? (
                <WorkCard steps={msg.agentSteps} html={msg.html} isActive={isWorking && msg.id === messages[messages.length - 1]?.id} streamingText={streamingText} currentAgent={currentAgent} />
              ) : (
                <div className="text-sm text-[#d1d1d1] leading-relaxed whitespace-pre-line">
                  {msg.content}
                </div>
              )}
            </div>
          ))}

          {isWorking && messages[messages.length - 1]?.role !== "assistant" && (
            <WorkCard steps={[]} isActive={true} streamingText={streamingText} currentAgent={currentAgent} />
          )}

          <div ref={messagesEndRef} />
        </div>
      </main>

      {/* Input */}
      <div className="shrink-0 border-t border-[#2f2f2f] bg-[#212121]">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div className="relative">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Message DeepForge..."
              rows={1}
              className="w-full bg-[#2f2f2f] border border-[#3a3a3a] focus:border-[#555] rounded-xl px-4 py-3 pr-12 text-sm text-[#ececec] resize-none outline-none min-h-[48px] max-h-[120px] transition-colors placeholder-[#666]"
            />
            <button
              onClick={send}
              disabled={!input.trim() || !connected}
              className="absolute right-2 bottom-2 w-8 h-8 rounded-lg bg-[#ececec] disabled:bg-[#444] disabled:cursor-not-allowed flex items-center justify-center transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={input.trim() ? "#212121" : "#888"} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkCard({ steps, html, isActive, streamingText, currentAgent }: {
  steps: AgentStep[];
  html?: string;
  isActive: boolean;
  streamingText?: string;
  currentAgent?: string;
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

  const agentNames: Record<string, string> = {
    project_manager: "Planning", product_manager: "Designing", architect: "Architecting",
    engineer: "Coding", reviewer: "Reviewing", crowd_user: "Testing", memory_keeper: "Saving",
  };

  return (
    <div className="border border-[#3a3a3a] rounded-xl overflow-hidden bg-[#2a2a2a]">
      {/* Header */}
      <div className="px-4 py-3 flex items-center gap-2 cursor-pointer hover:bg-[#333]" onClick={() => setExpanded(!expanded)}>
        {isActive && <div className="w-2 h-2 rounded-full bg-[#10a37f] animate-pulse" />}
        {!isActive && steps.length > 0 && <div className="w-2 h-2 rounded-full bg-[#10a37f]" />}
        <span className="text-xs font-medium text-[#b4b4b4]">
          {isActive ? (currentAgent ? `${agentNames[currentAgent] || currentAgent}...` : "Working...") : `Completed · ${steps.length} steps`}
        </span>
        <span className="ml-auto text-xs text-[#666]">{expanded ? "▾" : "▸"}</span>
      </div>

      {/* Steps */}
      {expanded && steps.length > 0 && (
        <div className="px-4 pb-2 border-t border-[#333]">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-2 py-1.5 text-xs text-[#999]">
              <span className="text-[#10a37f]">✓</span>
              <span className="text-[#b4b4b4]">{agentNames[s.agent] || s.agent}</span>
              <span className="text-[#666] truncate flex-1">{s.summary}</span>
            </div>
          ))}
          {isActive && streamingText && (
            <div className="py-1.5 text-xs text-[#999]">
              <span className="animate-pulse mr-1">●</span>
              <span className="text-[#b4b4b4]">{agentNames[currentAgent || ""] || "Processing"}</span>
              <span className="text-[#666] ml-2">{streamingText.slice(-60)}</span>
            </div>
          )}
        </div>
      )}

      {/* Preview */}
      {html && (
        <div className="border-t border-[#333]">
          <div className="px-4 py-2 flex items-center gap-2">
            <button onClick={() => setShowPreview(!showPreview)} className="text-xs text-[#10a37f] hover:underline">
              {showPreview ? "Hide preview" : "Show preview"}
            </button>
            {blobUrl && <a href={blobUrl} target="_blank" rel="noopener" className="text-xs text-[#666] hover:text-[#999]">Open in new tab ↗</a>}
          </div>
          {showPreview && blobUrl && (
            <iframe src={blobUrl} className="w-full h-[400px] border-t border-[#333] bg-white" />
          )}
        </div>
      )}
    </div>
  );
}
