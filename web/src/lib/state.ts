/**
 * Educe 前端状态管理 — 基于统一事件流
 *
 * 核心理念：所有状态来自后端 events 数组，前端按序渲染。
 * 实时交互通过 WebSocket 增量追加 event。
 */

// ═══ 事件类型 ═══

export interface AppEvent {
  type: string;
  ts: number;
  [key: string]: any;
}

// ═══ 确认操作 ═══

export interface PendingAction {
  type: string;
  params: string;
  display: string;
  name?: string;
}

// ═══ 应用状态 ═══

export interface AppState {
  // 连接
  connected: boolean;
  model: string;

  // session
  sessionId: string;
  phase: "idle" | "thinking" | "building" | "complete";

  // 统一事件流（所有交互记录）
  events: AppEvent[];

  // 实时流
  stream: {
    thinking: boolean;
    thinkingElapsed: number;
    code: string;
    html: string | null;
    fileName: string;
    fileSize: number;
    buildElapsed: number;
    runOutput: string;
  };

  // 待确认操作
  pendingConfirm: PendingAction[] | null;

  // 产物
  codeFiles: string[];
  buildingFiles: string[];  // 构建中临时文件列表（只在 building 阶段有效）
  currentVersion: number;
  versions: { version: number; files: string[]; timestamp: number }[];
  outputDir: string;

  // UI
  sidebarOpen: boolean;
  knowledgeOpen: boolean;
  showSettings: boolean;
  buildExpanded: boolean;
  previewFile: string | null;
}

// ═══ 初始状态 ═══

export const INITIAL_STATE: AppState = {
  connected: false,
  model: "",
  sessionId: "",
  phase: "idle",
  events: [],
  stream: {
    thinking: false,
    thinkingElapsed: 0,
    code: "",
    html: null,
    fileName: "",
    fileSize: 0,
    buildElapsed: 0,
    runOutput: "",
  },
  pendingConfirm: null,
  codeFiles: [],
  buildingFiles: [],
  currentVersion: 0,
  versions: [],
  outputDir: "",
  sidebarOpen: false,
  knowledgeOpen: false,
  showSettings: false,
  buildExpanded: false,
  previewFile: null,
};

// ═══ Actions ═══

export type Action =
  // 连接
  | { type: "SET_CONNECTED"; value: boolean }
  | { type: "SET_MODEL"; value: string }
  | { type: "SET_SESSION_ID"; value: string }

  // 事件流
  | { type: "APPEND_EVENT"; event: AppEvent }
  | { type: "SYNC_STATE"; payload: Record<string, any> }
  | { type: "RESET"; sessionId: string }

  // 实时流
  | { type: "THINKING_START" }
  | { type: "BUILD_START" }
  | { type: "STREAM_CHUNK"; content: string }
  | { type: "STREAM_CODE_UPDATE"; code: string }
  | { type: "STREAM_HTML"; html: string }
  | { type: "STREAM_RUN_OUTPUT"; output: string }
  | { type: "FILE_WRITTEN"; fileName: string; size: number }
  | { type: "VERSION_SAVED"; version: number }
  | { type: "IDLE" }
  | { type: "TICK_THINKING" }
  | { type: "TICK_BUILD" }

  // 确认机制
  | { type: "ACTION_CONFIRM_REQUEST"; actions: PendingAction[] }
  | { type: "ACTION_CONFIRMED" }
  | { type: "ACTION_CANCELLED" }

  // UI
  | { type: "TOGGLE_SIDEBAR" }
  | { type: "TOGGLE_KNOWLEDGE" }
  | { type: "TOGGLE_SETTINGS" }
  | { type: "TOGGLE_BUILD_EXPANDED" }
  | { type: "OPEN_PREVIEW"; file: string }
  | { type: "CLOSE_PREVIEW" }
  ;

// ═══ Reducer ═══

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {

    // ── 连接 ──
    case "SET_CONNECTED":
      return { ...state, connected: action.value };
    case "SET_MODEL":
      return { ...state, model: action.value };
    case "SET_SESSION_ID":
      return { ...state, sessionId: action.value };

    // ── 事件流 ──
    case "APPEND_EVENT":
      return {
        ...state,
        events: [...state.events, action.event],
      };

    case "SYNC_STATE": {
      const p = action.payload;
      // 首次加载（events为空）时用 state_sync 的 events 初始化；后续不覆盖
      const syncedEvents = (state.events.length === 0 && p.events?.length > 0)
        ? p.events : state.events;
      return {
        ...state,
        events: syncedEvents,
        phase: mapPhase(p.phase) || state.phase,
        codeFiles: p.code_files || state.codeFiles,
        outputDir: p.output_dir || state.outputDir,
        currentVersion: p.current_version ?? state.currentVersion,
        versions: p.versions || state.versions,
        buildingFiles: [],
      };
    }

    case "RESET":
      return {
        ...INITIAL_STATE,
        connected: state.connected,
        model: state.model,
        sessionId: action.sessionId,
      };

    // ── 实时流 ──
    case "THINKING_START":
      return {
        ...state,
        phase: state.phase === "idle" ? "thinking" : state.phase,
        stream: { ...state.stream, thinking: true, thinkingElapsed: 0 },
      };

    case "BUILD_START":
      return {
        ...state,
        phase: "building",
        stream: { ...INITIAL_STATE.stream, buildElapsed: 0 },
        pendingConfirm: null,
        buildExpanded: true,
        buildingFiles: [],
      };

    case "STREAM_CHUNK":
      if (state.phase === "building") {
        return { ...state, stream: { ...state.stream, code: state.stream.code + action.content } };
      }
      // 文字回复 → 追加为 ai_reply event
      const lastEvent = state.events[state.events.length - 1];
      if (lastEvent?.type === "ai_reply_streaming") {
        const updated = [...state.events];
        updated[updated.length - 1] = { ...lastEvent, content: lastEvent.content + action.content };
        return { ...state, events: updated, stream: { ...state.stream, thinking: false } };
      }
      return {
        ...state,
        events: [...state.events, { type: "ai_reply_streaming", ts: Date.now() / 1000, content: action.content }],
        stream: { ...state.stream, thinking: false },
      };

    case "STREAM_CODE_UPDATE":
      return { ...state, stream: { ...state.stream, code: action.code } };

    case "STREAM_HTML":
      return { ...state, stream: { ...state.stream, html: action.html } };

    case "STREAM_RUN_OUTPUT":
      return { ...state, stream: { ...state.stream, runOutput: state.stream.runOutput + action.output + "\n" } };

    case "FILE_WRITTEN":
      return {
        ...state,
        stream: { ...state.stream, fileName: action.fileName, fileSize: action.size },
        buildingFiles: state.buildingFiles.includes(action.fileName)
          ? state.buildingFiles
          : [...state.buildingFiles, action.fileName],
      };

    case "VERSION_SAVED":
      return { ...state, currentVersion: action.version };

    case "IDLE":
      // 将 streaming reply 转为正式 ai_reply
      const finalEvents = state.events.map(e =>
        e.type === "ai_reply_streaming" ? { ...e, type: "ai_reply" } : e
      );
      return {
        ...state,
        events: finalEvents,
        phase: state.phase === "building" ? "complete" : "idle",
        stream: { ...state.stream, thinking: false },
        buildingFiles: [],
      };

    case "TICK_THINKING":
      return { ...state, stream: { ...state.stream, thinkingElapsed: state.stream.thinkingElapsed + 1 } };

    case "TICK_BUILD":
      return { ...state, stream: { ...state.stream, buildElapsed: state.stream.buildElapsed + 1 } };

    // ── 确认机制 ──
    case "ACTION_CONFIRM_REQUEST":
      return {
        ...state,
        pendingConfirm: action.actions,
        stream: { ...state.stream, thinking: false },
      };

    case "ACTION_CONFIRMED": {
      // 追加确认事件到 events（保留在历史中）
      const confirmEvent: AppEvent = {
        type: "user_confirm",
        ts: Date.now() / 1000,
        decision: "confirm",
      };
      return {
        ...state,
        events: [...state.events, confirmEvent],
        pendingConfirm: null,
        stream: { ...state.stream, thinking: true },
      };
    }

    case "ACTION_CANCELLED": {
      const cancelEvent: AppEvent = {
        type: "user_confirm",
        ts: Date.now() / 1000,
        decision: "cancel",
      };
      return {
        ...state,
        events: [...state.events, cancelEvent],
        pendingConfirm: null,
      };
    }

    // ── UI ──
    case "TOGGLE_SIDEBAR":
      return { ...state, sidebarOpen: !state.sidebarOpen };
    case "TOGGLE_KNOWLEDGE":
      return { ...state, knowledgeOpen: !state.knowledgeOpen };
    case "TOGGLE_SETTINGS":
      return { ...state, showSettings: !state.showSettings };
    case "TOGGLE_BUILD_EXPANDED":
      return { ...state, buildExpanded: !state.buildExpanded };
    case "OPEN_PREVIEW":
      return { ...state, buildExpanded: true, previewFile: action.file };
    case "CLOSE_PREVIEW":
      return { ...state, buildExpanded: false, previewFile: null };

    default:
      return state;
  }
}

// ═══ 工具函数 ═══

function mapPhase(backendPhase: string | undefined): AppState["phase"] | null {
  if (!backendPhase) return null;
  const map: Record<string, AppState["phase"]> = {
    idle: "idle", building: "building", complete: "complete", thinking: "thinking",
  };
  return map[backendPhase] || null;
}

export function hasArtifact(state: AppState): boolean {
  return state.phase === "building" || state.codeFiles.length > 0 || state.stream.code.length > 0 || state.stream.html !== null;
}

export function isActive(state: AppState): boolean {
  return state.phase !== "idle" || state.events.length > 0;
}
