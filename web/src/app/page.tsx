"use client";

import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { Send, Loader2, Paperclip } from "lucide-react";
import { Logo, LogoBrand } from "@/components/logo";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { TopBar } from "@/components/top-bar";
import { WorkCard } from "@/components/work-card";
import { SettingsModal } from "@/components/settings-modal";
import { MessageBubble } from "@/components/message-bubble";
import { FileChips, type UploadedFile } from "@/components/file-chips";
import { ToastContainer, toast } from "@/components/toast";

interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  steps?: { agent: string; summary: string; done: boolean }[];
  html?: string;
  timestamp: number;
  files?: UploadedFile[];
}

interface TaskItem { id: string; request: string; project_type: string; created_at: number; response?: string }

const ACCEPT = ".txt,.py,.js,.ts,.tsx,.jsx,.css,.html,.json,.md,.yaml,.yml,.xml,.csv,.sh,.sql,.go,.java,.c,.cpp,.h,.rb,.rs,.swift,.pdf,.xlsx,.xls,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg";

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
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 768) setSidebarCollapsed(true);
  }, []);

  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const workingRef = useRef(false);
  const composingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startRef = useRef(0);
  const userScrolledRef = useRef(false);
  const mainRef = useRef<HTMLElement>(null);
  const sidRef = useRef("");
  const sidebarRef = useRef<SidebarRef>(null);

  const [thinking, setThinking] = useState(false);
  const [thinkingElapsed, setThinkingElapsed] = useState(0);
  const [expertName, setExpertName] = useState("");
  const thinkingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastUserMsgRef = useRef("");

  useEffect(() => {
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
    sidRef.current = sid;
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      setConnected(true);
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => setModel(d.model || ""));
    });
    ws.onDisconnect(() => setConnected(false));

    ws.onMessage((msg: ServerMessage) => {
      if (msg.type === "status") {
        if (msg.content === "thinking") {
          setThinking(true);
          setThinkingElapsed(0);
          setExpertName("");
          const ts = Date.now();
          thinkingTimerRef.current = setInterval(() => setThinkingElapsed(Math.floor((Date.now() - ts) / 1000)), 1000);
        } else if (msg.content === "pipeline_start") {
          setThinking(false);
          if (thinkingTimerRef.current) { clearInterval(thinkingTimerRef.current); thinkingTimerRef.current = null; }
          if (workingRef.current) return;
          workingRef.current = true;
          setWorking(true); setCurAgent(""); setElapsed(0);
          startRef.current = Date.now();
          timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
          setMsgs(p => [...p, { id: Date.now().toString(), role: "assistant", text: "", steps: [], timestamp: Date.now() }]);
        } else if (msg.content === "idle") {
          setThinking(false);
          if (thinkingTimerRef.current) { clearInterval(thinkingTimerRef.current); thinkingTimerRef.current = null; }
          workingRef.current = false; setWorking(false);
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
          sidebarRef.current?.refresh();
        }
      } else if (msg.type === "agent_message" && msg.msg_type !== "handoff") {
        setThinking(false);
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
      } else if ((msg as any).type === "expert") {
        setExpertName((msg as any).content || "");
      } else if (msg.type === "error") {
        workingRef.current = false; setWorking(false);
        if (timerRef.current) clearInterval(timerRef.current);
        setMsgs(p => [...p, { id: Date.now().toString(), role: "system", text: msg.content, timestamp: Date.now() }]);
      }
    });

    return () => ws.close();
  }, []);

  useEffect(() => {
    if (!userScrolledRef.current) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [msgs, elapsed]);

  function handleMainScroll() {
    const el = mainRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    userScrolledRef.current = !atBottom;
  }

  function extractHtml(c: string) {
    const m1 = c.match(/```filepath:[^\n]+\.html\n([\s\S]*?<\/html>)/i);
    if (m1) return m1[1];
    const m2 = c.match(/```html\n([\s\S]*?<\/html>)/i);
    if (m2) return m2[1];
    const m3 = c.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
    if (m3) return m3[1];
    return undefined;
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files;
    if (!selected || selected.length === 0) return;

    setUploading(true);
    setUploadProgress(0);
    const newFiles: UploadedFile[] = [];

    for (let i = 0; i < Math.min(selected.length, 5); i++) {
      const file = selected[i];
      const formData = new FormData();
      formData.append("file", file);

      try {
        const d = await new Promise<Record<string, unknown>>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `http://${API_HOST}/api/upload/${sidRef.current}`);
          xhr.upload.onprogress = (ev) => {
            if (ev.lengthComputable) {
              const fileProg = Math.round((ev.loaded / ev.total) * 100);
              const totalProg = Math.round(((i + fileProg / 100) / Math.min(selected.length, 5)) * 100);
              setUploadProgress(totalProg);
            }
          };
          xhr.onload = () => { try { resolve(JSON.parse(xhr.responseText)); } catch { reject(new Error("parse error")); } };
          xhr.onerror = () => reject(new Error("network error"));
          xhr.send(formData);
        });
        if (d.status === "ok" && d.file) {
          newFiles.push(d.file as UploadedFile);
        } else if (d.error) {
          newFiles.push({ id: Date.now().toString(), name: file.name, size: file.size, mime_type: "", is_image: false, error: String(d.error) });
        }
      } catch {
        newFiles.push({ id: Date.now().toString(), name: file.name, size: file.size, mime_type: "", is_image: false, error: "上传失败" });
      }
    }

    setFiles(prev => [...prev, ...newFiles.filter(f => !f.error)]);
    if (newFiles.some(f => f.error)) {
      const errors = newFiles.filter(f => f.error).map(f => `${f.name}: ${f.error}`).join("\n");
      setMsgs(p => [...p, { id: Date.now().toString(), role: "system", text: errors, timestamp: Date.now() }]);
    }

    setUploading(false);
    e.target.value = "";
  }

  function removeFile(id: string) {
    setFiles(prev => prev.filter(f => f.id !== id));
    fetch(`http://${API_HOST}/api/upload/${sidRef.current}/${id}`, { method: "DELETE" }).catch(() => {});
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles.length > 0) {
      const fakeEvent = { target: { files: droppedFiles, value: "" } } as unknown as React.ChangeEvent<HTMLInputElement>;
      handleFileSelect(fakeEvent);
    }
  }

  function send(text?: string) {
    const t = (text || input).trim();
    if (!t && files.length === 0) return;
    const w = wsRef.current;
    if (!w || w.readyState !== 1) { toast("未连接到后端服务", "error"); return; }

    const displayText = files.length > 0 ? `${t}\n📎 ${files.map(f => f.name).join(", ")}` : t;
    setMsgs(p => [...p, { id: Date.now().toString(), role: "user", text: displayText, timestamp: Date.now(), files: [...files] }]);
    lastUserMsgRef.current = t;

    const fileIds = files.map(f => f.id);
    w.send(t, fileIds.length > 0 ? fileIds : undefined);
    setInput("");
    setFiles([]);
    userScrolledRef.current = false;
  }

  function fmtTime(ts: number) {
    return new Date(ts).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  const hasMessages = msgs.length > 0;
  const canSend = input.trim() || files.length > 0;

  return (
    <div className="h-screen flex" style={{ background: "var(--bg)" }}>
      {/* 侧栏 */}
      <Sidebar ref={sidebarRef} collapsed={sidebarCollapsed} onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onNewTask={() => { setMsgs([]); setWorking(false); setFiles([]); }}
        onTaskSelect={(task: any) => {
          if (task.turns && Array.isArray(task.turns)) {
            const newMsgs: ChatMsg[] = [];
            for (const turn of task.turns) {
              newMsgs.push({ id: `${turn.timestamp}-q`, role: "user", text: turn.question, timestamp: (turn.timestamp || 0) * 1000 });
              if (turn.response) {
                const html = extractHtml(turn.response);
                if (html) {
                  newMsgs.push({ id: `${turn.timestamp}-a`, role: "assistant", text: "", steps: [{ agent: "builder", summary: "已生成代码", done: true }], html, timestamp: (turn.timestamp || 0) * 1000 + 1 });
                } else {
                  newMsgs.push({ id: `${turn.timestamp}-a`, role: "assistant", text: turn.response, timestamp: (turn.timestamp || 0) * 1000 + 1 });
                }
              }
            }
            setMsgs(newMsgs);
          } else {
            const newMsgs: ChatMsg[] = [{ id: task.id + "-q", role: "user", text: task.request || task.title || "", timestamp: task.created_at * 1000 }];
            if (task.response) {
              const html = extractHtml(task.response);
              if (html) {
                newMsgs.push({ id: task.id + "-a", role: "assistant", text: "", steps: [{ agent: "builder", summary: "已生成代码", done: true }], html, timestamp: task.created_at * 1000 + 1 });
              } else {
                newMsgs.push({ id: task.id + "-a", role: "assistant", text: task.response, timestamp: task.created_at * 1000 + 1 });
              }
            }
            setMsgs(newMsgs);
          }
        }} />

      {/* 主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar model={model} connected={connected} onOpenSettings={() => setShowSettings(true)} />

        <main ref={mainRef} className="flex-1 overflow-y-auto" onScroll={handleMainScroll}>
          <div className="max-w-[740px] mx-auto px-5 py-6 pb-28 min-h-full flex flex-col">

            {/* 空状态 */}
            {!hasMessages && !working && (
              <div className="flex-1 flex items-center justify-center">
                <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="text-center w-full max-w-[560px]">
                  <div className="flex justify-center mb-6">
                    <LogoBrand size={52} />
                  </div>
                  <h1 className="text-[26px] font-semibold tracking-tight mb-1.5" style={{ color: "var(--text)" }}>想做点什么？</h1>
                  <p className="text-[14px] mb-10" style={{ color: "var(--text-3)" }}>描述你的想法，智能体会帮你实现</p>
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
                        <div className="rounded-2xl rounded-br-sm px-4 py-2.5 text-[14px] text-white shadow-sm whitespace-pre-line" style={{ background: "var(--brand)" }}>{msg.text}</div>
                        <span className="text-[10px] px-1" style={{ color: "var(--text-4)" }}>{fmtTime(msg.timestamp)}</span>
                      </div>
                    ) : msg.steps !== undefined ? (
                      <WorkCard steps={msg.steps} html={msg.html} isActive={working && msg.id === msgs[msgs.length - 1]?.id}
                        currentAgent={curAgent} elapsed={elapsed} timestamp={msg.timestamp} />
                    ) : msg.role === "system" ? (
                      <div className="text-sm rounded-xl px-4 py-3 flex items-center gap-3" style={{ background: "var(--error-light)", color: "var(--error)", border: "1px solid var(--error)" }}>
                        <span className="flex-1">{msg.text}</span>
                        <button onClick={() => { if (lastUserMsgRef.current) send(lastUserMsgRef.current); }}
                          className="shrink-0 px-3 py-1 text-xs rounded-lg font-medium"
                          style={{ background: "var(--error)", color: "white" }}>重试</button>
                      </div>
                    ) : (
                      <MessageBubble text={msg.text} timestamp={msg.timestamp} fmtTime={fmtTime} />
                    )}
                  </motion.div>
                ))}
                {thinking && !working && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 px-1 py-2">
                    <Loader2 size={14} className="animate-spin" style={{ color: "var(--brand)" }} />
                    <span className="text-sm" style={{ color: "var(--text-2)" }}>
                      {expertName ? `🎓 ${expertName}` : "思考"}{thinkingElapsed > 0 ? ` · ${thinkingElapsed}s` : "..."}
                    </span>
                  </motion.div>
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>
        </main>

        {/* 输入区 */}
        <div className="fixed bottom-0 right-0 pt-4 pb-4 px-5 z-40" style={{ left: sidebarCollapsed ? "48px" : "var(--sidebar-width)", background: `linear-gradient(transparent, var(--bg) 30%)` }}
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}>
          <div className="max-w-[740px] mx-auto">
            {dragging && (
              <div className="mb-2 rounded-xl py-4 text-center text-sm font-medium border-2 border-dashed"
                style={{ borderColor: "var(--brand)", background: "var(--brand-light)", color: "var(--brand)" }}>
                松手上传文件
              </div>
            )}
            {/* 文件chips */}
            <FileChips files={files} onRemove={removeFile} />

            {/* 输入框 */}
            <div className="relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onCompositionStart={() => { composingRef.current = true }}
                onCompositionEnd={e => { composingRef.current = false; setInput((e.target as HTMLTextAreaElement).value) }}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !composingRef.current) { e.preventDefault(); send() } }}
                placeholder={files.length > 0 ? "想让我怎么处理？" : "问我任何问题，或上传文件"}
                rows={1}
                className="w-full rounded-2xl pl-12 pr-14 py-3.5 text-[15px] resize-none outline-none min-h-[52px] max-h-[120px] transition-all"
                style={{
                  background: "var(--bg-elevated)", border: "1px solid var(--border)", color: "var(--text)",
                  boxShadow: "var(--shadow-input)",
                }}
                onFocus={e => { e.target.style.borderColor = "var(--brand)"; e.target.style.boxShadow = "var(--shadow-input), 0 0 0 3px var(--brand-subtle)" }}
                onBlur={e => { e.target.style.borderColor = "var(--border)"; e.target.style.boxShadow = "var(--shadow-input)" }}
              />

              {/* 上传按钮 */}
              <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
                className="absolute left-3 bottom-3 w-9 h-9 rounded-xl flex items-center justify-center transition-all hover:bg-[var(--brand-subtle)]"
                style={{ color: uploading ? "var(--brand)" : "var(--text-3)" }}
                title="上传文件">
                {uploading ? (
                  <span className="text-[10px] font-bold tabular-nums" style={{ color: "var(--brand)" }}>{uploadProgress}%</span>
                ) : (
                  <Paperclip size={16} />
                )}
              </button>

              {/* 发送按钮 */}
              <button onClick={() => send()} disabled={!canSend}
                className={cn("absolute right-3 bottom-3 w-9 h-9 rounded-xl flex items-center justify-center transition-all",
                  canSend ? "text-white shadow-sm" : "cursor-not-allowed")}
                style={{ background: canSend ? "var(--brand)" : "var(--bg-sunken)", color: canSend ? "white" : "var(--text-4)" }}>
                <Send size={16} />
              </button>

              {/* 隐藏file input */}
              <input ref={fileInputRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={handleFileSelect} />
            </div>
          </div>
        </div>
      </div>

      {/* 设置 */}
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} model={model} onModelChange={setModel} />
      <ToastContainer />
    </div>
  );
}
