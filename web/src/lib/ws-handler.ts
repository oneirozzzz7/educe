/**
 * WebSocket 消息 → Action 映射
 *
 * 纯函数：接收 WS 消息，返回 Action（或 null 表示忽略）。
 */
import type { Action, AppEvent, PendingAction } from "./state";

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

  // ── chunk（实时文字/代码流）──
  if (type === "chunk") {
    return { type: "STREAM_CHUNK", content: msg.content || "" };
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

    // 非代码的 result/system 消息 → 追加为事件
    if (msg.msg_type === "result" || msg.msg_type === "system") {
      const event: AppEvent = { type: "ai_reply", ts: Date.now() / 1000, content };
      return { type: "APPEND_EVENT", event };
    }
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
      const event: AppEvent = {
        type: "transcript",
        ts: Date.now() / 1000,
        phase: evt.phase,
        role: evt.role,
        content: evt.content,
        elapsed: evt.elapsed,
      };
      return { type: "APPEND_EVENT", event };
    }

    if (evt.event === "write_file_result" && evt.file) {
      return { type: "FILE_WRITTEN", fileName: evt.file, size: evt.size || 0 };
    }

    if (evt.event === "step_plan" && evt.steps) {
      const event: AppEvent = {
        type: "transcript",
        ts: Date.now() / 1000,
        content: `步骤计划: ${evt.total || evt.steps.length}步`,
        step_plan: evt.steps,
      };
      return { type: "APPEND_EVENT", event };
    }

    return null;
  }

  // ── action_confirm_request ──
  if (type === "action_confirm_request") {
    return { type: "ACTION_CONFIRM_REQUEST", actions: msg.actions || [] };
  }

  // ── build_progress ──
  if (type === "build_progress") {
    const event: AppEvent = {
      type: "build_progress",
      ts: Date.now() / 1000,
      step: msg.step || "",
    };
    return { type: "APPEND_EVENT", event };
  }

  // ── state_sync ──
  if (type === "state_sync") {
    return { type: "SYNC_STATE", payload: msg };
  }

  // ── error ──
  if (type === "error") {
    const event: AppEvent = { type: "error", ts: Date.now() / 1000, content: msg.content };
    return { type: "APPEND_EVENT", event };
  }

  return null;
}
