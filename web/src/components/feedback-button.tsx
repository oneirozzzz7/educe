"use client";

import { useState } from "react";
import { API_HOST } from "@/lib/ws";

export function FeedbackButton({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);

  async function submit() {
    if (!text.trim()) return;
    try {
      await fetch(`http://${API_HOST}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text.trim(),
          timestamp: new Date().toISOString(),
          user_agent: navigator.userAgent,
        }),
      });
      setSent(true);
      setTimeout(() => { setOpen(false); setSent(false); setText(""); }, 2000);
    } catch {
      setSent(true);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          position: "fixed", bottom: 20, right: 20,
          width: 40, height: 40, borderRadius: "50%",
          background: "var(--surface-2)", border: "1px solid var(--border-1)",
          color: "var(--text-3)", fontSize: 18, cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
          transition: "all 0.15s",
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-1)"; e.currentTarget.style.color = "var(--text-3)"; }}
        title="反馈问题"
      >?</button>
    );
  }

  return (
    <div style={{
      position: "fixed", bottom: 20, right: 20,
      width: 280, padding: 16, borderRadius: 12,
      background: "var(--surface-1)", border: "1px solid var(--border-1)",
      boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-1)" }}>反馈</span>
        <button onClick={() => setOpen(false)} style={{ background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", fontSize: 16 }}>×</button>
      </div>
      {sent ? (
        <div style={{ fontSize: 12, color: "var(--accent)", textAlign: "center", padding: 8 }}>已收到，感谢反馈</div>
      ) : (
        <>
          <textarea
            value={text} onChange={e => setText(e.target.value)}
            placeholder="遇到什么问题？或者有什么建议？"
            style={{
              width: "100%", height: 60, resize: "none", borderRadius: 8,
              border: "1px solid var(--border-1)", padding: 8, fontSize: 12,
              background: "var(--surface-0)", color: "var(--text-1)",
            }}
          />
          <button onClick={submit} style={{
            padding: "6px 12px", borderRadius: 6, border: "none",
            background: "var(--accent)", color: "white", fontSize: 12,
            cursor: "pointer", alignSelf: "flex-end",
          }}>发送</button>
        </>
      )}
    </div>
  );
}
