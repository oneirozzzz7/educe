"use client";

import { useReducer, useRef, useEffect, useState } from "react";
import { reducer, INITIAL_STATE, type AppState, type AppEvent, type PendingAction } from "@/lib/state";
import { mapWsMessage } from "@/lib/ws-handler";
import { createWS, API_HOST, type ServerMessage } from "@/lib/ws";
import { WorkbenchShell } from "@/components/workbench-shell";
import { StatusBar } from "@/components/status-bar";
import { ActivityFeed } from "@/components/activity-feed";
import { DebugPanel } from "@/components/debug-panel";
import { Sidebar, type SidebarRef } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { EvolutionStatusPanel } from "@/components/evolution-status";
import { EvolutionBar } from "@/components/evolution-bar";
import { FeedbackButton } from "@/components/feedback-button";
import { FileRefPicker, ReferencedFilesBar } from "@/components/file-ref-picker";
import { ToolStreamCard } from "@/components/tool-stream-card";
import { DecisionCard } from "@/components/decision-card";
import { ProposeCard, ReflexBubble } from "@/components/evolution-card";

// ═══ Main Page ═══

export default function Home() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [showEvolution, setShowEvolution] = useState(false);
  const [referencedFiles, setReferencedFiles] = useState<string[]>([]);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [fileQuery, setFileQuery] = useState("");
  const wsRef = useRef<ReturnType<typeof createWS> | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sidebarRef = useRef<SidebarRef>(null);

  const { events, stream, phase, pendingConfirm, pendingDecisions, connected, model, toolStreams, pendingPropose, reflexBubble } = state;
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
      // Also buffer all raw messages to debug panel
      dispatch({ type: "DEBUG_EVENT", event: { ...msg, ts: Date.now() / 1000 } });
    });

    return () => { ws.close(); };
  }, []);

  useEffect(() => { if (!isThinking) return; const t = setInterval(() => dispatch({ type: "TICK_THINKING" }), 1000); return () => clearInterval(t); }, [isThinking]);
  useEffect(() => { if (!isBuilding) return; const t = setInterval(() => dispatch({ type: "TICK_BUILD" }), 1000); return () => clearInterval(t); }, [isBuilding]);

  // ── Actions ──
  function send(text: string) {
    if (!text.trim()) return;
    dispatch({ type: "APPEND_EVENT", event: { type: "user_input", ts: Date.now() / 1000, content: text.trim() } });
    wsRef.current?.sendRaw({ message: text.trim(), file_ids: [], referenced_files: referencedFiles });
    setReferencedFiles([]);
    setShowFilePicker(false);
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

  function handleSelectSession(task: any) {
    if (task?.id) {
      localStorage.setItem("educe_session_id", task.id);
      window.location.reload();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !showFilePicker) { e.preventDefault(); send(e.currentTarget.value); }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    const atMatch = val.match(/@(\S*)$/);
    if (atMatch) {
      setShowFilePicker(true);
      setFileQuery(atMatch[1]);
    } else {
      setShowFilePicker(false);
    }
  }

  function handleDecisionSubmit(choices: { question: string; choice: string }[]) {
    wsRef.current?.sendRaw({ type: "decision_response", decisions: choices });
    dispatch({ type: "DECISION_SUBMITTED" });
  }

  function handleCalibrate(action: "confirm" | "dismiss" | "snooze", eventId: string) {
    wsRef.current?.sendRaw({ type: "calibrate", action, event_id: eventId });
    dispatch({ type: "DISMISS_PROPOSE" });
  }

  function handleCancelTool(id: string) {
    wsRef.current?.sendRaw({ type: "tool_cancel", id, reason: "user" });
    dispatch({ type: "TOOL_CANCEL", id });
  }

  function handleEventClick(_event: AppEvent, idx: number) {
    dispatch({ type: "EXPAND_EVENT", idx });
  }

  // ── Elapsed time (for status bar) ──
  const elapsed = isThinking ? stream.thinkingElapsed : isBuilding ? stream.buildElapsed : 0;

  // ── Render ──
  return (
    <>
      <WorkbenchShell
        sidebarOpen={state.sidebarOpen}
        debugOpen={state.debugOpen}
        sidebar={
          <Sidebar
            ref={sidebarRef}
            collapsed={!state.sidebarOpen}
            onCollapse={() => dispatch({ type: "TOGGLE_SIDEBAR" })}
            onTaskSelect={handleSelectSession}
            onNewTask={handleNewChat}
            activeSessionId={state.sessionId}
            onOpenSettings={() => dispatch({ type: "TOGGLE_SETTINGS" })}
          />
        }
        commandRail={
          <CommandRail
            state={state}
            events={events}
            toolStreams={toolStreams}
            isThinking={isThinking}
            isBuilding={isBuilding}
            pendingConfirm={pendingConfirm}
            pendingDecisions={pendingDecisions}
            pendingPropose={pendingPropose}
            reflexBubble={reflexBubble}
            elapsed={elapsed}
            connected={connected}
            model={model}
            referencedFiles={referencedFiles}
            showFilePicker={showFilePicker}
            fileQuery={fileQuery}
            inputRef={inputRef}
            onSend={send}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
            onKeyDown={handleKeyDown}
            onInputChange={handleInputChange}
            onCancelTool={handleCancelTool}
            onToggleDebug={() => dispatch({ type: "TOGGLE_DEBUG" })}
            onToggleEvolution={() => setShowEvolution(true)}
            onFileSelect={(path) => {
              setReferencedFiles(prev => prev.includes(path) ? prev : [...prev, path]);
              setShowFilePicker(false);
              if (inputRef.current) {
                inputRef.current.value = inputRef.current.value.replace(/@\S*$/, "");
                inputRef.current.focus();
              }
            }}
            onRemoveFile={(f) => setReferencedFiles(prev => prev.filter(x => x !== f))}
            onCloseFilePicker={() => setShowFilePicker(false)}
            onEventClick={handleEventClick}
            onDecisionSubmit={handleDecisionSubmit}
            onCalibrate={handleCalibrate}
          />
        }
        debugPanel={
          <DebugPanel
            open={state.debugOpen}
            events={state.debugEvents}
            onClose={() => dispatch({ type: "TOGGLE_DEBUG" })}
          />
        }
      />

      {/* Overlays */}
      {state.showSettings && (
        <SettingsModal open={true} onClose={() => dispatch({ type: "TOGGLE_SETTINGS" })} model={model} onModelChange={m => dispatch({ type: "SET_MODEL", value: m })} />
      )}
      <EvolutionStatusPanel open={showEvolution} onClose={() => setShowEvolution(false)} />
      <FeedbackButton sessionId={state.sessionId} />
    </>
  );
}

// ═══ Command Rail ═══

interface CommandRailProps {
  state: AppState;
  events: AppEvent[];
  toolStreams: Record<string, any>;
  isThinking: boolean;
  isBuilding: boolean;
  pendingConfirm: PendingAction[] | null;
  pendingDecisions: { question: string; options: string[] }[] | null;
  pendingPropose: AppState["pendingPropose"];
  reflexBubble: AppState["reflexBubble"];
  elapsed: number;
  connected: boolean;
  model: string;
  referencedFiles: string[];
  showFilePicker: boolean;
  fileQuery: string;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  onSend: (text: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onCancelTool: (id: string) => void;
  onToggleDebug: () => void;
  onToggleEvolution: () => void;
  onFileSelect: (path: string) => void;
  onRemoveFile: (f: string) => void;
  onCloseFilePicker: () => void;
  onEventClick: (event: AppEvent, idx: number) => void;
  onDecisionSubmit: (choices: { question: string; choice: string }[]) => void;
  onCalibrate: (action: "confirm" | "dismiss" | "snooze", eventId: string) => void;
}

function CommandRail({
  state, events, toolStreams, isThinking, isBuilding, pendingConfirm,
  pendingDecisions, pendingPropose, reflexBubble,
  elapsed, connected, model, referencedFiles, showFilePicker, fileQuery,
  inputRef, onSend, onConfirm, onCancel, onKeyDown, onInputChange,
  onCancelTool, onToggleDebug, onToggleEvolution, onFileSelect, onRemoveFile,
  onCloseFilePicker, onEventClick, onDecisionSubmit, onCalibrate,
}: CommandRailProps) {
  return (
    <>
      {/* Activity Feed */}
      <ActivityFeed
        events={events}
        expandedEventIdx={state.expandedEventIdx}
        onEventClick={onEventClick}
        toolStreams={toolStreams}
        isThinking={isThinking}
        onCancelTool={onCancelTool}
        sessionId={state.sessionId}
        codeFiles={state.codeFiles}
      />

      {/* Pending Decisions (inline, above input) */}
      {pendingDecisions && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid var(--border-0)" }}>
          <DecisionCard decisions={pendingDecisions} onSubmit={onDecisionSubmit} />
        </div>
      )}

      {/* Pending Propose (inline, above input) */}
      {pendingPropose && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid var(--border-0)" }}>
          <ProposeCard
            eventId={pendingPropose.eventId}
            phrase={pendingPropose.phrase}
            cause={pendingPropose.cause}
            confidence={pendingPropose.confidence}
            organ={pendingPropose.organ}
            onCalibrate={onCalibrate}
          />
          {reflexBubble && (
            <div style={{ marginTop: 8 }}>
              <ReflexBubble phrase={reflexBubble.phrase} />
            </div>
          )}
        </div>
      )}

      {/* Pending Confirm Card (inline in feed area) */}
      {pendingConfirm && (
        <div style={{ padding: "8px 12px", borderTop: "1px solid var(--border-0)" }}>
          <div className="confirm-card">
            <div className="confirm-card-title">Confirm Action</div>
            {pendingConfirm.map((a, i) => (
              <div key={i} className="confirm-card-item">
                {a.type === "build" ? "Build: " : "Action: "}{a.display}
              </div>
            ))}
            <textarea className="confirm-card-input" placeholder="Additional notes (optional)" rows={2} />
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button className="btn-primary" onClick={onConfirm}>Confirm</button>
              <button className="btn-ghost" onClick={onCancel}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Status Bar */}
      <StatusBar
        phase={state.phase}
        model={model}
        connected={connected}
        elapsed={elapsed}
        onToggleDebug={onToggleDebug}
      />

      {/* Input Area */}
      <div style={{ padding: "8px 12px 12px", flexShrink: 0, borderTop: "1px solid var(--border-0)" }}>
        <EvolutionBar />
        <ReferencedFilesBar files={referencedFiles} onRemove={onRemoveFile} />
        <div style={{ position: "relative" }}>
          {showFilePicker && (
            <FileRefPicker
              query={fileQuery}
              onSelect={onFileSelect}
              onClose={onCloseFilePicker}
            />
          )}
          <textarea
            ref={inputRef}
            className="main-input"
            placeholder={isBuilding ? "Building... add thoughts" : "Think it. Build it. (@ to reference files)"}
            onKeyDown={onKeyDown}
            onChange={onInputChange}
            rows={1}
          />
          <button
            onClick={() => inputRef.current && onSend(inputRef.current.value)}
            style={{ position: "absolute", right: 12, bottom: 12, background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: 18 }}
          >
            &rsaquo;
          </button>
        </div>
      </div>
    </>
  );
}
