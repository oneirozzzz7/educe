/**
 * WebSocket 消息 → Action 映射
 *
 * 纯函数：接收 WS 消息，返回 Action（或 null 表示忽略）。
 * 不持有状态，不产生副作用。
 */
import type { Action, TranscriptEntry, Decision } from "./state";

export function mapWsMessage(msg: any): Action | Action[] | null {
  const type = msg.type;

  // ── status ──
  if (type === "status") {
    switch (msg.content) {
      case "thinking":
        return { type: "THINKING_START" };
      case "pipeline_start":
        return { type: "BUILD_START" };
      case "idle":
        return { type: "IDLE" };
      default:
        return null;
    }
  }

  // ── chunk ──
  if (type === "chunk") {
    return { type: "STREAM_CHUNK", content: msg.content || "", sender: msg.sender || "" };
  }

  // ── agent_message ──
  if (type === "agent_message" && msg.msg_type !== "handoff") {
    const content: string = msg.content || "";
    const hasFiles = msg.has_files || false;

    if (hasFiles || content.includes("```filepath:") || (content.includes("<!DOCTYPE") && content.length > 500)) {
      const codeMatch = content.match(/```filepath:([^\n]+)\n([\s\S]*?)```/);
      if (codeMatch) {
        return [
          { type: "FILE_WRITTEN", fileName: codeMatch[1].trim(), size: codeMatch[2].length },
          { type: "STREAM_CODE_UPDATE", code: codeMatch[2] },
        ];
      }
      return { type: "STREAM_CODE_UPDATE", code: content };
    }

    // Text reply — only dispatch if not already streamed via chunks
    // (If chunks already built the turn, agent_message is a duplicate)
    return null;
  }

  // ── tool_event ──
  if (type === "tool_event") {
    const evt = msg;

    if (evt.event === "step_code_content" && evt.code) {
      return { type: "STREAM_CODE_UPDATE", code: evt.code };
    }

    if (evt.event === "version_saved" && evt.version) {
      return { type: "VERSION_SAVED", version: evt.version };
    }

    if (evt.event === "transcript") {
      const entry: TranscriptEntry = {
        event: "transcript",
        phase: evt.phase,
        role: evt.role,
        content: evt.content,
        elapsed: evt.elapsed,
        step: evt.step,
        total_steps: evt.total_steps,
        step_plan: evt.step_plan,
      };
      return { type: "TRANSCRIPT_ENTRY", entry };
    }

    if (evt.event === "write_file_result" && evt.file) {
      return { type: "FILE_WRITTEN", fileName: evt.file, size: evt.size || 0 };
    }

    // Other tool events — transcript entry for visibility
    if (evt.event === "step_start" || evt.event === "step_done" || evt.event === "step_plan") {
      const entry: TranscriptEntry = {
        event: evt.event,
        content: evt.description || evt.event,
        step: evt.step,
        total_steps: evt.total,
        step_plan: evt.steps,
        elapsed: evt.time,
      };
      return { type: "TRANSCRIPT_ENTRY", entry };
    }

    return null; // Ignore other tool events
  }

  // ── decision_request ──
  if (type === "decision_request") {
    return { type: "DECISION_REQUEST", decisions: msg.decisions as Decision[] };
  }

  // ── plan_proposal ──
  if (type === "plan_proposal") {
    return { type: "PLAN_PROPOSAL", plans: msg.plans || [], request: msg.original_request || "" };
  }

  // ── build_progress ──
  if (type === "build_progress") {
    const entry: TranscriptEntry = { event: "transcript", phase: "build", role: "system", content: msg.step || "" };
    return { type: "TRANSCRIPT_ENTRY", entry };
  }

  // ── expert ──
  if (type === "expert") {
    return { type: "THINKING_START", expertName: msg.content };
  }

  // ── state_sync ──
  if (type === "state_sync") {
    return { type: "STATE_SYNC", payload: msg };
  }

  // ── error ──
  if (type === "error") {
    return { type: "ERROR", message: msg.content || "Unknown error" };
  }

  return null;
}
