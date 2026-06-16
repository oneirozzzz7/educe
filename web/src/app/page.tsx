"use client";

import { useReducer, useRef, useEffect, useState } from "react";
import { marked } from "marked";
import { reducer, INITIAL_STATE, type AppState, type AppEvent, type PendingAction } from "@/lib/state";
import { mapWsMessage } from "@/lib/ws-handler";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { SettingsModal } from "@/components/settings-modal";
import { LogoMark } from "@/components/logo";
import { ConvergencePanel } from "@/components/convergence-panel";
import { FeedbackButton } from "@/components/feedback-button";

marked.setOptions({ gfm: true, breaks: true });

function stripActionPrefix(code: string): string {
  return code.replace(/^```action:\w+\n(?:[\w_]+:.*\n)*---\n/gm, "").replace(/```\s*$/g, "").trim();
}

function CodePreviewPanel({ fileUrl, runOutput, cachedCode, sessionId }: { fileUrl: string; runOutput: string; cachedCode: string; sessionId: string }) {
  const [code, setCode] = useState("");
  const [output, setOutput] = useState(runOutput);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (cachedCode) { setCode(stripActionPrefix(cachedCode)); return; }
    fetch(fileUrl).then(r => r.text()).then(setCode).catch(() => setCode("// 加载失败"));
  }, [fileUrl, cachedCode]);

  useEffect(() => { if (runOutput) setOutput(runOutput); }, [runOutput]);

  async function handleRun() {
    setRunning(true);
    try {
      const res = await fetch(`http://${API_HOST}/api/run/${sessionId}`, { method: "POST" });
      const data = await res.json();
      setOutput(data.output || "（无输出）");
    } catch (e) {
      setOutput("请求失败");
    }
    setRunning(false);
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button onClick={handleRun} disabled={running}
          style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid var(--border-1)", background: running ? "var(--surface-2)" : "var(--accent-dim)", color: "var(--accent)", fontSize: 12, cursor: running ? "wait" : "pointer", fontWeight: 500 }}>
          {running ? "运行中..." : "▶ 运行"}
        </button>
        {output && <span style={{ fontSize: 11, color: "var(--text-3)" }}>↓ 输出</span>}
      </div>
      {output && (
        <div style={{ background: "var(--surface-0)", border: "1px solid var(--border-0)", borderRadius: 8, padding: 12 }}>
          <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--pass)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", margin: 0 }}>{output}</pre>
        </div>
      )}
      <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--text-1)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>{code || "加载中..."}</pre>
    </div>
  );
}

// ═══ 历史列表项 ═══

interface HistoryItem {
  id: string;
  title: string;
  event_count: number;
  type: string;
  updated_at: number;
}

function HistorySidebar({ open, currentId, onSelect, onNew }: {
  open: boolean; currentId: string;
  onSelect: (id: string) => void; onNew: () => void;
}) {
  const [items, setItems] = useState<HistoryItem[]>([]);

  useEffect(() => {
    fetch(`http://${API_HOST}/api/tasks`)
      .then(r => r.json())
      .then(d => setItems(d.tasks || []))
      .catch(() => {});
  }, [currentId]); // 切换 session 后刷新列表

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* 新建按钮 */}
      <button
        onClick={onNew}
        style={{
          margin: open ? "12px 12px 8px" : "8px 4px",
          padding: open ? "8px 12px" : "8px",
          borderRadius: "var(--radius-sm)",
          border: "1px solid var(--border-2)",
          background: "transparent",
          color: "var(--text-2)",
          fontSize: open ? 13 : 16,
          cursor: "pointer",
          transition: "all 0.2s",
          textAlign: "center",
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-2)"; e.currentTarget.style.color = "var(--text-2)"; }}
      >
        {open ? "+ 新对话" : "+"}
      </button>

      {/* 历史列表 */}
      {open && (
        <div style={{ flex: 1, overflow: "auto", padding: "0 8px" }}>
          <div style={{ padding: "8px 8px 4px", fontSize: 10, color: "var(--text-3)", fontWeight: 500, letterSpacing: "0.5px", textTransform: "uppercase" }}>
            历史
          </div>
          {items.map(item => (
            <div
              key={item.id}
              onClick={() => onSelect(item.id)}
              style={{
                padding: "8px 10px",
                marginBottom: 2,
                borderRadius: "var(--radius-sm)",
                cursor: "pointer",
                background: item.id === currentId ? "var(--accent-dim)" : "transparent",
                transition: "background 0.15s",
              }}
              onMouseEnter={e => { if (item.id !== currentId) e.currentTarget.style.background = "var(--surface-2)"; }}
              onMouseLeave={e => { if (item.id !== currentId) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ fontSize: 12, color: "var(--text-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {item.type === "code" ? "🔨 " : "💬 "}{item.title}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}>
                {item.event_count}条 · {formatRelativeTime(item.updated_at)}
              </div>
            </div>
          ))}
          {items.length === 0 && (
            <div style={{ padding: "16px 8px", fontSize: 12, color: "var(--text-3)", textAlign: "center" }}>
              暂无历史
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatRelativeTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

// ═══ 知识管理面板 ═══

function KnowledgePanel({ onRefresh }: { onRefresh?: () => void }) {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetch(`http://${API_HOST}/api/knowledge`)
      .then(r => r.json())
      .then(d => { setEntries(d.entries || []); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (entryId: string) => {
    try {
      await fetch(`http://${API_HOST}/api/knowledge/${entryId}`, { method: "DELETE" });
      load();
    } catch {}
  };

  if (loading) return <div style={{ color: "var(--text-3)", fontSize: 13, padding: 8 }}>加载中...</div>;
  if (entries.length === 0) return (
    <div style={{ color: "var(--text-3)", fontSize: 13, padding: 8, lineHeight: 1.6 }}>
      暂无记忆。<br/>通过对话告诉我你的偏好，我会记住。
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {entries.map((e: any) => (
        <div key={e.id} style={{
          padding: "12px 14px", borderRadius: "var(--radius-sm)",
          background: "var(--surface-2)", border: "1px solid var(--border-0)",
        }}>
          <div style={{ fontSize: 13, color: "var(--text-0)", marginBottom: 6, lineHeight: 1.5 }}>{e.preview}</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: 11, color: "var(--text-3)", display: "flex", gap: 6, alignItems: "center" }}>
              <span>{e.domain || "通用"}</span>
              <span style={{ opacity: 0.3 }}>·</span>
              <span style={{ color: e.source === "user" ? "var(--pass)" : "var(--accent)" }}>
                {e.source === "user" ? "用户" : "系统"}
              </span>
              <span style={{ opacity: 0.3 }}>·</span>
              <span>{e.maturity}</span>
            </div>
            <button
              onClick={() => handleDelete(e.id)}
              style={{ background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", fontSize: 12, padding: "2px 6px", borderRadius: 4, transition: "all 0.15s" }}
              onMouseEnter={e => { e.currentTarget.style.color = "var(--fail)"; e.currentTarget.style.background = "var(--fail-dim)"; }}
              onMouseLeave={e => { e.currentTarget.style.color = "var(--text-3)"; e.currentTarget.style.background = "none"; }}
            >删除</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ═══ 事件渲染器 ═══

function EventRenderer({ event, sessionId, onOpenPreview }: { event: AppEvent; sessionId?: string; onOpenPreview?: (file: string) => void }) {
  switch (event.type) {
    case "user_input":
      return (
        <div style={{ textAlign: "right", marginBottom: 10 }}>
          <span className="user-msg">{event.content}</span>
          <div style={{ fontSize: 9, color: "var(--text-3)", marginTop: 3 }}>
            {new Date(event.ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
      );

    case "ai_reply":
    case "ai_reply_streaming":
      return (
        <div style={{ marginBottom: 10 }}>
          <div className="ai-reply">
            <div className="ai-reply-bar" style={{ minHeight: 16 }} />
            <div className="ai-reply-content md" dangerouslySetInnerHTML={{ __html: marked.parse(event.content || "") as string }} />
          </div>
          {event.type === "ai_reply" && (
            <div style={{ fontSize: 9, color: "var(--text-3)", marginTop: 3 }}>
              {new Date(event.ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </div>
          )}
        </div>
      );

    case "transcript":
      return null; // handled by BuildProcessLine aggregation

    case "action_confirm":
      return null; // handled inline by pendingConfirm

    case "user_confirm":
      return (
        <div className={`status-bar ${event.decision === "confirm" ? "status-bar-success" : ""}`} style={{ marginBottom: 8 }}>
          {event.decision === "confirm" ? "✅ 已确认" : "⊘ 已取消"}
          {event.note && ` · 补充：${event.note}`}
        </div>
      );

    case "action_executed":
      return null; // absorbed into build process

    case "build_start":
      return null; // absorbed into build process

    case "build_complete":
      if (!event.success) {
        return <div className="status-bar status-bar-error" style={{ marginBottom: 8 }}>❌ 构建失败</div>;
      }
      return null; // ArtifactCard rendered separately below events list

    case "error":
      return (
        <div className="status-bar status-bar-error" style={{ marginBottom: 8 }}>
          ❌ {event.content}
        </div>
      );

    default:
      return null;
  }
}

// ═══ 构建过程聚合行 ═══

function BuildProcessLine({ events, startIdx }: { events: AppEvent[]; startIdx: number }) {
  const steps: string[] = [];
  for (let i = startIdx; i < events.length; i++) {
    const e = events[i];
    if (e.type === "transcript" && e.content) {
      steps.push(e.content);
    } else if (e.type === "build_start") {
      continue;
    } else if (e.type === "action_executed") {
      continue;
    } else {
      break;
    }
  }
  if (steps.length === 0) return null;
  return (
    <div style={{ marginBottom: 8, fontSize: 10, color: "var(--pass)", display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
      {steps.map((s, i) => (
        <span key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {i > 0 && <span style={{ color: "var(--text-3)" }}>→</span>}
          <span>✓ {s}</span>
        </span>
      ))}
    </div>
  );
}

// ═══ 产物卡片 ═══

function ArtifactCard({ file, sessionId, version, onOpen, active }: {
  file: string; sessionId: string; version?: number; onOpen: () => void; active?: boolean;
}) {
  const isHtml = /\.(html?|svg)$/i.test(file);
  const ext = file.split(".").pop()?.toUpperCase() || "";
  return (
    <div
      onClick={onOpen}
      style={{
        margin: "6px 0 14px", border: `1px solid ${active ? "var(--accent)" : "var(--border-1)"}`,
        borderRadius: 10, background: "var(--surface-1)", display: "flex", cursor: "pointer",
        maxWidth: 560, height: 72, overflow: "hidden", transition: "all 0.2s",
        boxShadow: active ? "0 0 0 1px var(--accent), 0 4px 12px rgba(167,139,250,0.1)" : "none",
      }}
      onMouseEnter={e => { if (!active) { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.transform = "translateY(-1px)"; } }}
      onMouseLeave={e => { if (!active) { e.currentTarget.style.borderColor = "var(--border-1)"; e.currentTarget.style.transform = "none"; } }}
    >
      {isHtml ? (
        <div style={{ width: 90, flexShrink: 0, background: "white", borderRight: "1px solid var(--border-0)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ transform: "scale(0.3)", transformOrigin: "center", textAlign: "center", color: "#1d1d1f", fontFamily: "-apple-system, sans-serif" }}>
            <div style={{ width: 10, height: 10, background: "#ff6b6b", borderRadius: "50%", margin: "2px auto" }} />
            <div style={{ fontSize: 28, fontWeight: 200 }}>25:00</div>
          </div>
        </div>
      ) : (
        <div style={{ width: 90, flexShrink: 0, background: "var(--surface-0)", borderRight: "1px solid var(--border-0)", fontFamily: "'SF Mono', monospace", fontSize: 6.5, color: "var(--text-3)", lineHeight: 1.3, padding: 6, overflow: "hidden", whiteSpace: "pre" }}>
          {`import time\ndef countdown():\n    count = 10\n    while True:\n        print(count)\n        if count == 0:\n            break\n        time.sleep(1)\n        count -= 1`}
        </div>
      )}
      <div style={{ flex: 1, padding: "10px 12px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 2 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-0)", display: "flex", alignItems: "center", gap: 6 }}>
          {file}
          {version && <span style={{ fontSize: 8, padding: "1px 5px", borderRadius: 3, background: "rgba(110,231,183,0.08)", color: "var(--pass)", border: "1px solid rgba(110,231,183,0.1)" }}>v{version}</span>}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-3)" }}>
          {ext} {!isHtml && <span style={{ color: "var(--pass)" }}>· ▶ 可运行</span>}
        </div>
      </div>
    </div>
  );
}

// ═══ 产物卡片（构建中） ═══

function ArtifactCardBuilding({ file, fileCount, elapsed }: {
  file: string; fileCount: number; elapsed: number;
}) {
  const ext = file.split(".").pop()?.toUpperCase() || "";
  return (
    <div
      className="artifact-building"
      style={{
        margin: "6px 0 14px", border: "1px solid var(--accent)",
        borderRadius: 10, background: "var(--surface-1)", display: "flex",
        maxWidth: 560, height: 72, overflow: "hidden", opacity: 0.85,
        animation: "artifactPulse 2s ease-in-out infinite",
      }}
    >
      <div style={{ width: 90, flexShrink: 0, background: "var(--surface-0)", borderRight: "1px solid var(--border-0)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 24, height: 24, border: "2px solid var(--accent)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
      </div>
      <div style={{ flex: 1, padding: "10px 12px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 2 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-0)", display: "flex", alignItems: "center", gap: 6 }}>
          {file}
          {fileCount > 1 && <span style={{ fontSize: 8, padding: "1px 5px", borderRadius: 3, background: "rgba(167,139,250,0.08)", color: "var(--accent)", border: "1px solid rgba(167,139,250,0.15)" }}>{fileCount} files</span>}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 6 }}>
          <span>{ext}</span>
          <span style={{ color: "var(--accent)" }}>构建中... {elapsed}s</span>
        </div>
      </div>
    </div>
  );
}

// ═══ 主页面 ═══

export default function Home() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { events, stream, phase, pendingConfirm, connected, model } = state;
  const isBuilding = phase === "building";
  const isThinking = stream.thinking;

  // ── WebSocket ──
  useEffect(() => {
    let sid = localStorage.getItem("educe_session_id");
    if (!sid) {
      sid = crypto.randomUUID?.() ?? Date.now().toString(36);
      localStorage.setItem("educe_session_id", sid);
    }
    dispatch({ type: "SET_SESSION_ID", value: sid });
    const ws = createWS(sid);
    wsRef.current = ws;

    ws.onConnect(() => {
      dispatch({ type: "SET_CONNECTED", value: true });
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => {
        dispatch({ type: "SET_MODEL", value: d.model || "" });
      }).catch(() => {});
    });
    ws.onDisconnect(() => dispatch({ type: "SET_CONNECTED", value: false }));
    ws.onMessage((msg: ServerMessage) => {
      const actions = mapWsMessage(msg);
      if (!actions) return;
      if (Array.isArray(actions)) { actions.forEach(a => dispatch(a)); }
      else { dispatch(actions); }
    });

    return () => { ws.close(); };
  }, []);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [events.length, stream.thinking]);
  useEffect(() => { if (!isThinking) return; const t = setInterval(() => dispatch({ type: "TICK_THINKING" }), 1000); return () => clearInterval(t); }, [isThinking]);
  useEffect(() => { if (!isBuilding) return; const t = setInterval(() => dispatch({ type: "TICK_BUILD" }), 1000); return () => clearInterval(t); }, [isBuilding]);

  function send(text: string) {
    if (!text.trim()) return;
    dispatch({ type: "APPEND_EVENT", event: { type: "user_input", ts: Date.now() / 1000, content: text.trim() } });
    wsRef.current?.send(text.trim());
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleConfirm() {
    const supplement = document.querySelector<HTMLTextAreaElement>(".confirm-card-input");
    const note = supplement?.value?.trim() || "";
    wsRef.current?.sendRaw({ type: "action_confirm_response", decision: "confirm", note });
    dispatch({ type: "ACTION_CONFIRMED" });
  }

  function handleCancel() {
    wsRef.current?.sendRaw({ type: "action_confirm_response", decision: "cancel" });
    dispatch({ type: "ACTION_CANCELLED" });
  }

  function handleNewChat() {
    const newSid = crypto.randomUUID?.() ?? Date.now().toString(36);
    localStorage.setItem("educe_session_id", newSid);
    window.location.reload();
  }

  function handleSelectSession(id: string) {
    localStorage.setItem("educe_session_id", id);
    window.location.reload();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(e.currentTarget.value); }
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: "var(--bg)" }}>

      {/* ── 侧边栏 ── */}
      <div style={{
        width: state.sidebarOpen ? "var(--sidebar-width-open)" : "var(--sidebar-width)",
        background: "var(--bg)",
        borderRight: "1px solid var(--border-0)",
        transition: "width 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* 折叠按钮 */}
        <button
          onClick={() => dispatch({ type: "TOGGLE_SIDEBAR" })}
          style={{ width: 48, height: 48, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", transition: "color 0.2s", flexShrink: 0 }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--accent)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--text-3)")}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="3" width="12" height="1.5" rx="0.75" fill="currentColor" opacity="0.8"/>
            <rect x="2" y="7.25" width="8" height="1.5" rx="0.75" fill="currentColor" opacity="0.5"/>
            <rect x="2" y="11.5" width="10" height="1.5" rx="0.75" fill="currentColor" opacity="0.3"/>
          </svg>
        </button>

        <HistorySidebar
          open={state.sidebarOpen}
          currentId={state.sessionId}
          onSelect={handleSelectSession}
          onNew={handleNewChat}
        />
      </div>

      {/* ── 主内容区 ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* 顶栏 */}
        <div style={{
          height: 44, display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 20px", borderBottom: "1px solid var(--border-0)", flexShrink: 0, background: "var(--surface-0)",
        }}>
          <LogoMark size={15} />
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {connected && (
              <span onClick={() => dispatch({ type: "TOGGLE_SETTINGS" })}
                style={{ fontSize: 10, color: "var(--text-2)", display: "flex", alignItems: "center", gap: 5, cursor: "pointer", transition: "color 0.2s" }}
                onMouseEnter={e => (e.currentTarget.style.color = "var(--text-0)")}
                onMouseLeave={e => (e.currentTarget.style.color = "var(--text-2)")}>
                <span style={{ width: 4, height: 4, borderRadius: "50%", background: "var(--pass)" }} />
                {model}
              </span>
            )}
            <button onClick={() => dispatch({ type: "TOGGLE_KNOWLEDGE" })}
              style={{ background: "none", border: "none", color: "var(--text-2)", cursor: "pointer", fontSize: 14, padding: 4, transition: "color 0.2s" }}
              onMouseEnter={e => (e.currentTarget.style.color = "var(--accent)")}
              onMouseLeave={e => (e.currentTarget.style.color = "var(--text-2)")}
              title="知识管理">🧠</button>
          </div>
        </div>

        {/* 内容 = 对话 + 右侧预览面板 */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

          {/* 对话区 */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* 事件流 */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 0 100px" }}>
          <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 32px" }}>
            {events.length === 0 && !isThinking && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: "12vh", position: "relative", gap: 24 }}>
                <div style={{ position: "absolute", top: "10vh", left: "50%", transform: "translateX(-50%)", width: 320, height: 180, background: "radial-gradient(ellipse at center, rgba(167,139,250,0.06) 0%, transparent 70%)", pointerEvents: "none" }} />
                <LogoMark size={48} />
                <div style={{ fontSize: 24, color: "var(--text-2)", fontWeight: 300, letterSpacing: "0.05em" }}>Educe</div>
                <div style={{ fontSize: 13, color: "var(--text-3)", maxWidth: 400, textAlign: "center", lineHeight: 1.6 }}>
                  说出你想做的事，Educe 帮你执行并验证。<br/>遇到问题会自动修复，搞不定会诚实告诉你。
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 500, marginTop: 8 }}>
                  {[
                    "帮我写一个 Python 脚本统计当前目录所有文件的大小",
                    "用 pandas 处理 CSV 算每列平均值",
                    "做一个 Flask 待办 API 能增删改查",
                  ].map((example, idx) => (
                    <button key={idx} onClick={() => { if (inputRef.current) { inputRef.current.value = example; send(example); } }}
                      style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--border-1)", background: "var(--surface-1)", color: "var(--text-2)", fontSize: 12, cursor: "pointer", transition: "all 0.15s", textAlign: "left" }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-1)"; e.currentTarget.style.color = "var(--text-2)"; }}
                    >{example}</button>
                  ))}
                </div>
              </div>
            )}

            {(() => {
              const rendered: React.ReactNode[] = [];
              let i = 0;
              while (i < events.length) {
                const event = events[i];
                // Aggregate build process lines
                if (event.type === "build_start" || (event.type === "transcript" && i > 0 && (events[i-1]?.type === "user_confirm" || events[i-1]?.type === "build_start" || events[i-1]?.type === "transcript" || events[i-1]?.type === "action_executed"))) {
                  const startIdx = event.type === "build_start" ? i + 1 : i;
                  let endIdx = startIdx;
                  while (endIdx < events.length && (events[endIdx].type === "transcript" || events[endIdx].type === "action_executed" || events[endIdx].type === "build_start")) {
                    endIdx++;
                  }
                  if (endIdx > startIdx) {
                    rendered.push(<BuildProcessLine key={`bp-${i}`} events={events} startIdx={startIdx} />);
                    i = endIdx;
                    continue;
                  }
                }
                // Skip action_confirm if pendingConfirm is active
                if (event.type === "action_confirm" && pendingConfirm && i >= events.length - 2) {
                  i++;
                  continue;
                }
                rendered.push(
                  <EventRenderer
                    key={`${event.type}-${i}`}
                    event={event}
                    sessionId={state.sessionId}
                    onOpenPreview={(file) => dispatch({ type: "OPEN_PREVIEW", file })}
                  />
                );
                i++;
              }
              return rendered;
            })()}

            {/* ArtifactCardBuilding: show during build when files are being written */}
            {phase === "building" && state.buildingFiles.length > 0 && (
              <ArtifactCardBuilding
                file={state.buildingFiles[state.buildingFiles.length - 1]}
                fileCount={state.buildingFiles.length}
                elapsed={state.stream.buildElapsed}
              />
            )}

            {/* ArtifactCard: show after build complete */}
            {phase !== "building" && state.codeFiles.length > 0 && (
              <ArtifactCard
                file={state.codeFiles[0]}
                sessionId={state.sessionId}
                version={state.currentVersion || 1}
                onOpen={() => dispatch({ type: "OPEN_PREVIEW", file: state.codeFiles[0] })}
                active={state.buildExpanded && state.previewFile === state.codeFiles[0]}
              />
            )}

            {pendingConfirm && (
              <div className="confirm-card" style={{ marginBottom: 16 }}>
                <div className="confirm-card-title">确认执行</div>
                {pendingConfirm.map((a, i) => (
                  <div key={i} className="confirm-card-item">
                    {a.type === "build" ? "🔨 " : "🧠 "}{a.display}
                  </div>
                ))}
                <textarea className="confirm-card-input" placeholder="补充你的想法（可选）" rows={2} />
                <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                  <button className="btn-primary" onClick={handleConfirm}>确认</button>
                  <button className="btn-ghost" onClick={handleCancel}>取消</button>
                </div>
              </div>
            )}

            {isThinking && (
              <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
                <div className="thinking-dots"><span /><span /><span /></div>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>思考中 · {stream.thinkingElapsed}s</span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        </div>

        {/* 输入框 */}
        <div style={{ padding: "12px 32px 20px", flexShrink: 0 }}>
          <ConvergencePanel sessionId={state.sessionId} />
          <div style={{ maxWidth: 960, margin: "0 auto", position: "relative" }}>
            <textarea ref={inputRef} className="main-input" placeholder={isBuilding ? "构建中... 可以补充想法" : "Think it. Build it."} onKeyDown={handleKeyDown} rows={1} />
            <button onClick={() => inputRef.current && send(inputRef.current.value)}
              style={{ position: "absolute", right: 12, bottom: 12, background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: 18 }}>➤</button>
          </div>
        </div>
        </div>{/* 关闭对话区 flex-col */}

      {/* ── 右侧预览面板 ── */}
      {state.buildExpanded && (state.previewFile || state.codeFiles.length > 0 || isBuilding) && (
        <div style={{ width: "50%", borderLeft: "1px solid var(--border-1)", background: "var(--surface-0)", display: "flex", flexDirection: "column", flexShrink: 0, transition: "width 0.3s cubic-bezier(0.16, 1, 0.3, 1)" }}>
          <div style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", borderBottom: "1px solid var(--border-0)", flexShrink: 0 }}>
            <span style={{ fontSize: 12, color: "var(--text-1)", fontWeight: 500 }}>
              {isBuilding ? `🔨 构建中... ${stream.buildElapsed}s` : `✅ ${state.previewFile || state.codeFiles[0] || ""}`}
            </span>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {!isBuilding && (state.previewFile || state.codeFiles[0]) && (
                <>
                  <a href={`http://${API_HOST}/preview/${state.sessionId.slice(0, 16)}/${state.previewFile || state.codeFiles[0]}`} target="_blank" rel="noopener"
                    style={{ fontSize: 11, color: "var(--accent)", textDecoration: "none", padding: "3px 8px", borderRadius: 5, background: "rgba(167,139,250,0.08)" }}>新标签 ↗</a>
                </>
              )}
              <button onClick={() => dispatch({ type: "CLOSE_PREVIEW" })}
                style={{ background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", fontSize: 16, width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 6 }}
                onMouseEnter={e => { e.currentTarget.style.background = "var(--surface-2)"; e.currentTarget.style.color = "var(--text-0)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = "var(--text-3)"; }}>×</button>
            </div>
          </div>
          {isBuilding ? (
            <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
              {stream.code ? (
                <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--text-1)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{stripActionPrefix(stream.code)}</pre>
              ) : (
                <div style={{ color: "var(--text-3)", fontSize: 13 }}>等待代码生成...</div>
              )}
            </div>
          ) : (state.previewFile || state.codeFiles[0])?.match(/\.(html?|svg)$/) ? (
            <iframe
              src={`http://${API_HOST}/preview/${state.sessionId.slice(0, 16)}/${state.previewFile || state.codeFiles[0]}`}
              style={{ flex: 1, border: "none", width: "100%", margin: 10, borderRadius: 10 }}
              sandbox="allow-scripts allow-same-origin"
            />
          ) : (
            <CodePreviewPanel
              fileUrl={`http://${API_HOST}/preview/${state.sessionId.slice(0, 16)}/${state.previewFile || state.codeFiles[0]}`}
              runOutput={stream.runOutput}
              cachedCode={stream.code}
              sessionId={state.sessionId}
            />
          )}
        </div>
      )}

      </div>{/* 关闭 content flex-row */}
      </div>{/* 关闭 main flex-col */}

      {/* ── 设置弹窗 ── */}
      {state.showSettings && (
        <SettingsModal open={true} onClose={() => dispatch({ type: "TOGGLE_SETTINGS" })} model={model} onModelChange={m => dispatch({ type: "SET_MODEL", value: m })} />
      )}

      {/* ── 知识管理面板 ── */}
      {state.knowledgeOpen && (
        <>
          <div onClick={() => dispatch({ type: "TOGGLE_KNOWLEDGE" })} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.3)", zIndex: 200 }} />
          <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: 360, background: "var(--surface-1)", borderLeft: "1px solid var(--border-1)", zIndex: 201, display: "flex", flexDirection: "column", boxShadow: "var(--shadow-md)", animation: "slide-in-right 0.25s cubic-bezier(0.16, 1, 0.3, 1)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border-0)" }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-0)" }}>🧠 知识管理</span>
              <button onClick={() => dispatch({ type: "TOGGLE_KNOWLEDGE" })} style={{ background: "none", border: "none", color: "var(--text-2)", cursor: "pointer", fontSize: 16 }}>✕</button>
            </div>
            <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
              <KnowledgePanel />
            </div>
          </div>
        </>
      )}

      {/* 反馈按钮 */}
      <FeedbackButton sessionId={state.sessionId} />
    </div>
  );
}
