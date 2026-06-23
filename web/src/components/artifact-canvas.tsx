"use client";

import { useState, useEffect } from "react";
import { marked } from "marked";
import { LogoMark } from "@/components/logo";
import { DecisionCard } from "@/components/decision-card";
import { ProposeCard, ReflexBubble } from "@/components/evolution-card";
import { API_HOST } from "@/lib/ws";
import type { AppState } from "@/lib/state";

// ═══ Helpers ═══

function stripActionPrefix(code: string): string {
  return code.replace(/^```action:\w+\n(?:[\w_]+:.*\n)*---\n/gm, "").replace(/```\s*$/g, "").trim();
}

// ═══ Code Preview Panel ═══

function CodePreviewPanel({ fileUrl, runOutput, cachedCode, sessionId }: {
  fileUrl: string; runOutput: string; cachedCode: string; sessionId: string;
}) {
  const [code, setCode] = useState("");
  const [output, setOutput] = useState(runOutput);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (cachedCode) { setCode(stripActionPrefix(cachedCode)); return; }
    fetch(fileUrl).then(r => r.text()).then(setCode).catch(() => setCode("// Load failed"));
  }, [fileUrl, cachedCode]);

  useEffect(() => { if (runOutput) setOutput(runOutput); }, [runOutput]);

  async function handleRun() {
    setRunning(true);
    try {
      const res = await fetch(`http://${API_HOST}/api/run/${sessionId}`, { method: "POST" });
      const data = await res.json();
      setOutput(data.output || "(no output)");
    } catch {
      setOutput("Request failed");
    }
    setRunning(false);
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button onClick={handleRun} disabled={running}
          style={{ padding: "5px 12px", borderRadius: 6, border: "1px solid var(--border-1)", background: running ? "var(--surface-2)" : "var(--accent-dim)", color: "var(--accent)", fontSize: 12, cursor: running ? "wait" : "pointer", fontWeight: 500 }}>
          {running ? "Running..." : "Run"}
        </button>
        {output && <span style={{ fontSize: 11, color: "var(--text-3)" }}>Output</span>}
      </div>
      {output && (
        <div style={{ background: "var(--surface-0)", border: "1px solid var(--border-0)", borderRadius: 8, padding: 12 }}>
          <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--pass)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", margin: 0 }}>{output}</pre>
        </div>
      )}
      <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--text-1)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>{code || "Loading..."}</pre>
    </div>
  );
}

// ═══ Zero State ═══

function ZeroState() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, opacity: 0.6 }}>
      <LogoMark size={48} />
      <span style={{ fontSize: 14, color: "var(--text-3)", fontWeight: 400 }}>What would you like to build?</span>
    </div>
  );
}

// ═══ Building View ═══

function BuildingView({ code, elapsed }: { code: string; elapsed: number }) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <div style={{ height: 36, display: "flex", alignItems: "center", padding: "0 16px", borderBottom: "1px solid var(--border-0)", fontSize: 12, color: "var(--accent)", gap: 8, flexShrink: 0 }}>
        <div style={{ width: 14, height: 14, border: "2px solid var(--accent)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        <span>Building... {elapsed}s</span>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {code ? (
          <pre style={{ fontSize: 12, lineHeight: 1.5, color: "var(--text-1)", fontFamily: "'Geist Mono', monospace", whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>{stripActionPrefix(code)}</pre>
        ) : (
          <div style={{ color: "var(--text-3)", fontSize: 13 }}>Waiting for code generation...</div>
        )}
      </div>
    </div>
  );
}

// ═══ File Preview ═══

function FilePreview({ file, sessionId, code, runOutput }: {
  file: string; sessionId: string; code: string; runOutput: string;
}) {
  const previewUrl = `http://${API_HOST}/preview/${sessionId.slice(0, 16)}/${file}`;
  const isHtml = /\.(html?|svg)$/i.test(file);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ height: 36, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", borderBottom: "1px solid var(--border-0)", fontSize: 12, color: "var(--text-1)", flexShrink: 0 }}>
        <span style={{ fontWeight: 500 }}>{file}</span>
        <a href={previewUrl} target="_blank" rel="noopener"
          style={{ fontSize: 11, color: "var(--accent)", textDecoration: "none", padding: "3px 8px", borderRadius: 5, background: "rgba(167,139,250,0.08)" }}>
          Open in tab
        </a>
      </div>
      {/* Content */}
      {isHtml ? (
        <iframe
          src={previewUrl}
          style={{ flex: 1, border: "none", width: "100%", margin: 0 }}
          sandbox="allow-scripts allow-same-origin"
        />
      ) : (
        <CodePreviewPanel fileUrl={previewUrl} runOutput={runOutput} cachedCode={code} sessionId={sessionId} />
      )}
    </div>
  );
}

// ═══ Markdown Reply View ═══

function MarkdownReply({ content }: { content: string }) {
  return (
    <div style={{ flex: 1, overflow: "auto", padding: 24 }}>
      <div
        className="md"
        style={{ fontSize: 14, color: "var(--text-1)", lineHeight: 1.7, maxWidth: 640 }}
        dangerouslySetInnerHTML={{ __html: marked.parse(content || "") as string }}
      />
    </div>
  );
}

// ═══ Main Canvas ═══

interface ArtifactCanvasProps {
  state: AppState;
  onDecisionSubmit: (choices: { question: string; choice: string }[]) => void;
  onCalibrate: (action: "confirm" | "dismiss" | "snooze", eventId: string) => void;
}

/**
 * ArtifactCanvas - Right panel showing ONE thing at a time by priority:
 * 1. pendingDecisions -> DecisionCard
 * 2. pendingPropose -> ProposeCard
 * 3. phase=building -> BuildingView (streaming code)
 * 4. codeFiles -> FilePreview
 * 5. Last long ai_reply -> MarkdownReply
 * 6. Otherwise -> ZeroState
 */
export function ArtifactCanvas({ state, onDecisionSubmit, onCalibrate }: ArtifactCanvasProps) {
  const { pendingDecisions, pendingPropose, phase, codeFiles, events, stream, sessionId, reflexBubble } = state;

  // Priority 1: Pending decisions
  if (pendingDecisions) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: 24, justifyContent: "center" }}>
        <DecisionCard decisions={pendingDecisions} onSubmit={onDecisionSubmit} />
      </div>
    );
  }

  // Priority 2: Pending propose
  if (pendingPropose) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: 24, justifyContent: "center" }}>
        <ProposeCard
          eventId={pendingPropose.eventId}
          phrase={pendingPropose.phrase}
          cause={pendingPropose.cause}
          confidence={pendingPropose.confidence}
          organ={pendingPropose.organ}
          onCalibrate={onCalibrate}
        />
        {reflexBubble && (
          <div style={{ marginTop: 12 }}>
            <ReflexBubble phrase={reflexBubble.phrase} />
          </div>
        )}
      </div>
    );
  }

  // Priority 3: Building
  if (phase === "building") {
    return <BuildingView code={stream.code} elapsed={stream.buildElapsed} />;
  }

  // Priority 4: Code files (preview)
  if (codeFiles.length > 0) {
    const file = state.previewFile || codeFiles[0];
    return <FilePreview file={file} sessionId={sessionId} code={stream.code} runOutput={stream.runOutput} />;
  }

  // Priority 5: Last long ai_reply
  const lastReply = [...events].reverse().find(e => e.type === "ai_reply" && e.content && e.content.length > 100);
  if (lastReply) {
    return <MarkdownReply content={lastReply.content} />;
  }

  // Priority 6: Zero state
  return <ZeroState />;
}
