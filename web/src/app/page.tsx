"use client";

import { useReducer, useRef, useEffect, useState, useCallback } from "react";
import { marked } from "marked";
import { reducer, INITIAL_STATE, type AppState, type AppEvent } from "@/lib/state";
import { mapWsMessage } from "@/lib/ws-handler";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { SettingsModal } from "@/components/settings-modal";
import { LogoMark, LogoBrand } from "@/components/logo";

marked.setOptions({ gfm: true, breaks: true });

// ═══ 事件渲染器 ═══

function EventRenderer({ event }: { event: AppEvent }) {
  switch (event.type) {
    case "user_input":
      return (
        <div style={{ textAlign: "right", marginBottom: 16 }}>
          <span className="user-msg">{event.content}</span>
          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4 }}>
            {new Date(event.ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
      );

    case "ai_reply":
    case "ai_reply_streaming":
      return (
        <div style={{ marginBottom: 16 }}>
          <div className="ai-reply">
            <div className="ai-reply-bar" style={{ minHeight: 20 }} />
            <div className="ai-reply-content md" dangerouslySetInnerHTML={{ __html: marked.parse(event.content || "") as string }} />
          </div>
          {event.type === "ai_reply" && (
            <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4 }}>
              {new Date(event.ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
            </div>
          )}
        </div>
      );

    case "transcript":
      return (
        <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", flexShrink: 0 }} />
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>
            {event.phase && `[${event.phase}] `}{event.content}
          </span>
          {event.elapsed > 0 && (
            <span style={{ fontSize: 11, color: "var(--text-3)", marginLeft: "auto" }}>{event.elapsed}s</span>
          )}
        </div>
      );

    case "action_confirm":
      return (
        <div className="confirm-card" style={{ marginBottom: 16 }}>
          <div className="confirm-card-title">确认执行</div>
          {(event.actions || []).map((a: any, i: number) => (
            <div key={i} className="confirm-card-item">
              {a.type === "build" ? "🔨 " : "🧠 "}{a.display}
            </div>
          ))}
        </div>
      );

    case "user_confirm":
      return (
        <div className={`status-bar ${event.decision === "confirm" ? "status-bar-success" : ""}`} style={{ marginBottom: 12 }}>
          {event.decision === "confirm" ? "✅" : "⊘"} {event.decision === "confirm" ? "已确认" : "已取消"}
          {event.note && ` · ${event.note}`}
        </div>
      );

    case "action_executed":
      return (
        <div className={`status-bar ${event.success ? "status-bar-success" : "status-bar-error"}`} style={{ marginBottom: 12 }}>
          {event.success ? "✅" : "❌"} {event.action}: {event.result?.slice(0, 80)}
        </div>
      );

    case "knowledge_change":
      return (
        <div className="status-bar" style={{ marginBottom: 12 }}>
          🧠 {event.op === "add" ? "已记住" : event.op === "delete" ? "已删除" : event.op}: {event.content}
        </div>
      );

    case "build_start":
      return (
        <div className="status-bar" style={{ marginBottom: 12 }}>
          🔨 开始构建...
        </div>
      );

    case "build_complete":
      return (
        <div className={`status-bar ${event.success ? "status-bar-success" : "status-bar-error"}`} style={{ marginBottom: 12 }}>
          {event.success ? "✅" : "❌"} 构建{event.success ? "完成" : "失败"}
          {event.files?.length > 0 && ` · ${event.files.join(", ")}`}
        </div>
      );

    case "error":
      return (
        <div className="status-bar status-bar-error" style={{ marginBottom: 12 }}>
          ❌ {event.content}
        </div>
      );

    default:
      return null;
  }
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
    const sid = crypto.randomUUID?.() ?? Date.now().toString(36);
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

  // ── 自动滚动 ──
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, stream.thinking]);

  // ── 思考计时器 ──
  useEffect(() => {
    if (!isThinking) return;
    const t = setInterval(() => dispatch({ type: "TICK_THINKING" }), 1000);
    return () => clearInterval(t);
  }, [isThinking]);

  // ── 构建计时器 ──
  useEffect(() => {
    if (!isBuilding) return;
    const t = setInterval(() => dispatch({ type: "TICK_BUILD" }), 1000);
    return () => clearInterval(t);
  }, [isBuilding]);

  // ── 发送消息 ──
  function send(text: string) {
    if (!text.trim()) return;
    const event: AppEvent = { type: "user_input", ts: Date.now() / 1000, content: text.trim() };
    dispatch({ type: "APPEND_EVENT", event });
    wsRef.current?.send(text.trim());
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleConfirm() {
    wsRef.current?.send("确认");
    dispatch({ type: "ACTION_CONFIRMED" });
  }

  function handleCancel() {
    wsRef.current?.send("取消");
    dispatch({ type: "ACTION_CONFIRMED" });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(e.currentTarget.value);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", background: "var(--bg)" }}>

      {/* ── 侧边栏（窄） ── */}
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
        <button
          onClick={() => dispatch({ type: "TOGGLE_SIDEBAR" })}
          style={{ width: 48, height: 52, display: "flex", alignItems: "center", justifyContent: "center", background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", transition: "color 0.2s" }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--accent)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--text-3)")}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="3" width="12" height="1.5" rx="0.75" fill="currentColor" opacity="0.8"/>
            <rect x="2" y="7.25" width="8" height="1.5" rx="0.75" fill="currentColor" opacity="0.5"/>
            <rect x="2" y="11.5" width="10" height="1.5" rx="0.75" fill="currentColor" opacity="0.3"/>
          </svg>
        </button>
        {state.sidebarOpen && (
          <div style={{ padding: "12px 16px", fontSize: 11, color: "var(--text-3)", fontWeight: 500, letterSpacing: "0.5px", textTransform: "uppercase" }}>
            历史
          </div>
        )}
      </div>

      {/* ── 主内容区 ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        {/* 顶栏 */}
        <div style={{
          height: 52,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          borderBottom: "1px solid var(--border-1)",
          flexShrink: 0,
          background: "var(--surface-1)",
        }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-0)", letterSpacing: "-0.3px" }}><LogoMark size={18} /></span>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {connected && (
              <span style={{ fontSize: 11, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--pass)" }} />
                {model}
              </span>
            )}
            <button
              onClick={() => dispatch({ type: "TOGGLE_KNOWLEDGE" })}
              style={{ background: "none", border: "none", color: "var(--text-2)", cursor: "pointer", fontSize: 16, padding: 4, transition: "color 0.2s" }}
              onMouseEnter={e => (e.currentTarget.style.color = "var(--accent)")}
              onMouseLeave={e => (e.currentTarget.style.color = "var(--text-2)")}
              title="知识管理"
            >🧠</button>
            <button
              onClick={() => dispatch({ type: "TOGGLE_SETTINGS" })}
              style={{ background: "none", border: "none", color: "var(--text-2)", cursor: "pointer", fontSize: 16, padding: 4, transition: "color 0.2s" }}
              onMouseEnter={e => (e.currentTarget.style.color = "var(--text-0)")}
              onMouseLeave={e => (e.currentTarget.style.color = "var(--text-2)")}
              title="设置"
            >⚙</button>
          </div>
        </div>

        {/* 事件流 */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 28px 100px" }}>
          <div style={{ maxWidth: 720, margin: "0 auto" }}>

            {events.length === 0 && !isThinking && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: "20vh", position: "relative" }}>
                {/* 背景光晕 */}
                <div style={{
                  position: "absolute",
                  top: "18vh",
                  left: "50%",
                  transform: "translateX(-50%)",
                  width: 320,
                  height: 180,
                  background: "radial-gradient(ellipse at center, rgba(167,139,250,0.06) 0%, transparent 70%)",
                  pointerEvents: "none",
                }} />
                <LogoMark size={48} />
                <div style={{
                  fontSize: 28,
                  color: "var(--text-3)",
                  fontWeight: 300,
                  marginTop: 28,
                  letterSpacing: "0.1em",
                  fontFamily: "'Geist', sans-serif",
                  opacity: 0.6,
                }}>Think it. Build it.</div>
              </div>
            )}

            {events.map((event, i) => (
              <EventRenderer key={`${event.type}-${i}`} event={event} />
            ))}

            {/* 待确认卡片（实时，非 event 中的） */}
            {pendingConfirm && (
              <div className="confirm-card" style={{ marginBottom: 16 }}>
                <div className="confirm-card-title">确认执行</div>
                {pendingConfirm.map((a, i) => (
                  <div key={i} className="confirm-card-item">
                    {a.type === "build" ? "🔨 " : "🧠 "}{a.display}
                  </div>
                ))}
                <textarea
                  className="confirm-card-input"
                  placeholder="补充你的想法（可选）"
                  rows={2}
                />
                <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                  <button className="btn-primary" onClick={handleConfirm}>确认开始</button>
                  <button className="btn-ghost" onClick={handleCancel}>取消</button>
                </div>
              </div>
            )}

            {/* 思考中 */}
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
        <div style={{ padding: "12px 28px 20px", flexShrink: 0 }}>
          <div style={{ maxWidth: 720, margin: "0 auto", position: "relative" }}>
            <textarea
              ref={inputRef}
              className="main-input"
              placeholder={isBuilding ? "构建中... 可以补充想法" : "描述你想做的东西..."}
              onKeyDown={handleKeyDown}
              rows={1}
            />
            <button
              onClick={() => inputRef.current && send(inputRef.current.value)}
              style={{
                position: "absolute",
                right: 12,
                bottom: 12,
                background: "none",
                border: "none",
                color: "var(--accent)",
                cursor: "pointer",
                fontSize: 18,
              }}
            >➤</button>
          </div>
        </div>
      </div>

      {/* ── 画中画（构建中） ── */}
      {isBuilding && !state.buildExpanded && (
        <div className="pip" onClick={() => dispatch({ type: "TOGGLE_BUILD_EXPANDED" })}>
          <div className="pip-dot" />
          <span>构建中... {stream.buildElapsed}s</span>
        </div>
      )}

      {/* ── 设置弹窗 ── */}
      {state.showSettings && (
        <SettingsModal
          open={true}
          onClose={() => dispatch({ type: "TOGGLE_SETTINGS" })}
          model={model}
          onModelChange={m => dispatch({ type: "SET_MODEL", value: m })}
        />
      )}
    </div>
  );
}
