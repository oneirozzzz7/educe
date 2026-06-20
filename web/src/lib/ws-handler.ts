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

  // ── tool_start/tool_chunk/tool_end（流式工具事件）──
  if (type === "tool_start") {
    return { type: "TOOL_START", id: msg.id, tool: msg.tool, meta: msg.meta || {} };
  }
  if (type === "tool_chunk") {
    return { type: "TOOL_CHUNK", id: msg.id, stream: msg.stream, data: msg.data };
  }
  if (type === "tool_end") {
    return { type: "TOOL_END", id: msg.id, result: msg.result || {} };
  }
  if (type === "tool_cancel") {
    return { type: "TOOL_CANCEL", id: msg.id };
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

    if (evt.event === "action_detail") {
      const event: AppEvent = {
        type: "action_detail",
        ts: Date.now() / 1000,
        action_type: evt.action_type,
        label: evt.label,
        command: evt.command,
        output_preview: evt.output_preview,
        success: evt.success,
        elapsed_ms: evt.elapsed_ms,
        retried: evt.retried,
      };
      return { type: "APPEND_EVENT", event };
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

    if (evt.event === "run_result") {
      const event: AppEvent = {
        type: "transcript",
        ts: Date.now() / 1000,
        content: evt.success ? `验证通过` : `验证失败: ${evt.output?.slice(0, 100) || ""}`,
        elapsed: 0,
      };
      return [
        { type: "APPEND_EVENT", event },
        ...(evt.output ? [{ type: "STREAM_RUN_OUTPUT" as const, output: evt.output }] : []),
      ];
    }

    if (evt.event === "build_complete") {
      const event: AppEvent = {
        type: "build_complete",
        ts: Date.now() / 1000,
        files: evt.files || [],
        success: evt.success ?? true,
      };
      return [
        { type: "APPEND_EVENT", event },
        { type: "IDLE" },
      ];
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
