/**
 * Educe Frontend State — 单一状态机
 *
 * 核心原则：后端是 authority，前端只是渲染视图。
 * 所有状态转换通过 dispatch(action) 完成，不存在散落的 setState 调用。
 */

// ═══════════════════════════════════════
// Types
// ═══════════════════════════════════════

export interface TranscriptEntry {
  event: string;
  phase?: string;
  role?: string;
  content?: string;
  elapsed?: number;
  step?: number;
  total_steps?: number;
  step_plan?: string[];
}

export interface Turn {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  type?: string; // "text" | "code"
}

export interface VersionSnapshot {
  version: number;
  files: string[];
  timestamp: number;
}

export interface Decision {
  question: string;
  options: string[];
}

export interface Plan {
  id: number;
  title: string;
  desc: string;
  est: string;
}

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  is_image: boolean;
  error?: string;
  preview_url?: string;
}

// ═══════════════════════════════════════
// State Structure
// ═══════════════════════════════════════

export type Phase = "idle" | "thinking" | "building" | "complete";

export interface SessionState {
  id: string;
  phase: Phase;
  userRequest: string;
  codeFiles: string[];
  outputDir: string;
  currentVersion: number;
  versions: VersionSnapshot[];
  transcript: TranscriptEntry[];
  turns: Turn[];
  planSummary: string;
  stepPlan: string[];
  complexity: string;
  expertName: string;
}

export interface StreamState {
  code: string;
  html: string | null;
  thinking: boolean;
  thinkingElapsed: number;
  buildElapsed: number;
  fileName: string;
  fileSize: number;
}

export interface PendingState {
  decisions: Decision[] | null;
  plans: Plan[] | null;
  planRequest: string;
  clarifyQuestion: string;
}

export interface UIState {
  rightPanel: "code" | "preview";
  splitPercent: number;
  artifactExpanded: boolean;
  sidebarCollapsed: boolean;
  showSettings: boolean;
  connected: boolean;
  model: string;
}

export interface UploadState {
  files: UploadedFile[];
  uploading: boolean;
}

export interface AppState {
  session: SessionState;
  stream: StreamState;
  pending: PendingState;
  ui: UIState;
  upload: UploadState;
}

// ═══════════════════════════════════════
// Initial State
// ═══════════════════════════════════════

export const EMPTY_SESSION: SessionState = {
  id: "",
  phase: "idle",
  userRequest: "",
  codeFiles: [],
  outputDir: "",
  currentVersion: 0,
  versions: [],
  transcript: [],
  turns: [],
  planSummary: "",
  stepPlan: [],
  complexity: "",
  expertName: "",
};

export const EMPTY_STREAM: StreamState = {
  code: "",
  html: null,
  thinking: false,
  thinkingElapsed: 0,
  buildElapsed: 0,
  fileName: "",
  fileSize: 0,
};

export const EMPTY_PENDING: PendingState = {
  decisions: null,
  plans: null,
  planRequest: "",
  clarifyQuestion: "",
};

export const INITIAL_UI: UIState = {
  rightPanel: "code",
  splitPercent: 55,
  artifactExpanded: false,
  sidebarCollapsed: false,
  showSettings: false,
  connected: false,
  model: "",
};

export const INITIAL_STATE: AppState = {
  session: EMPTY_SESSION,
  stream: EMPTY_STREAM,
  pending: EMPTY_PENDING,
  ui: INITIAL_UI,
  upload: { files: [], uploading: false },
};

// ═══════════════════════════════════════
// Actions
// ═══════════════════════════════════════

export type Action =
  // Backend state sync
  | { type: "STATE_SYNC"; payload: Record<string, any> }
  | { type: "SWITCH_SESSION"; payload: Record<string, any> }
  // Status transitions
  | { type: "THINKING_START"; expertName?: string }
  | { type: "BUILD_START" }
  | { type: "BUILD_COMPLETE" }
  | { type: "IDLE" }
  // Streaming
  | { type: "STREAM_CHUNK"; content: string; sender: string }
  | { type: "STREAM_CODE_UPDATE"; code: string }
  | { type: "STREAM_HTML"; html: string }
  // Transcript
  | { type: "TRANSCRIPT_ENTRY"; entry: TranscriptEntry }
  // Interaction
  | { type: "DECISION_REQUEST"; decisions: Decision[] }
  | { type: "PLAN_PROPOSAL"; plans: Plan[]; request: string }
  | { type: "CLARIFY"; question: string }
  | { type: "DECISION_SUBMITTED" }
  | { type: "PLAN_SELECTED" }
  // User actions
  | { type: "USER_SEND"; text: string }
  | { type: "RESET"; sessionId: string }
  // Tool events
  | { type: "FILE_WRITTEN"; fileName: string; size: number }
  | { type: "VERSION_SAVED"; version: number }
  // Timers
  | { type: "TICK_THINKING" }
  | { type: "TICK_ELAPSED" }
  // UI
  | { type: "SET_UI"; key: keyof UIState; value: any }
  | { type: "SET_UPLOAD"; files?: UploadedFile[]; uploading?: boolean }
  // Agent message (text reply arrives)
  | { type: "AGENT_MESSAGE"; content: string; sender: string; hasFiles: boolean }
  // Error
  | { type: "ERROR"; message: string };

// ═══════════════════════════════════════
// Reducer
// ═══════════════════════════════════════

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    // ── Backend state sync ──
    case "STATE_SYNC": {
      const synced = mapBackendSnapshot(action.payload, state.session);
      // Don't overwrite turns if local has more (we're ahead during streaming)
      if (state.session.turns.length >= synced.turns.length) {
        synced.turns = state.session.turns;
      }
      // Don't overwrite transcript if local has more
      if (state.session.transcript.length >= synced.transcript.length) {
        synced.transcript = state.session.transcript;
      }
      return { ...state, session: synced };
    }

    case "SWITCH_SESSION":
      return {
        ...state,
        session: mapBackendSnapshot(action.payload, EMPTY_SESSION),
        stream: EMPTY_STREAM,
        pending: EMPTY_PENDING,
      };

    // ── Status transitions ──
    case "THINKING_START":
      return {
        ...state,
        stream: { ...state.stream, thinking: true, thinkingElapsed: 0 },
        session: {
          ...state.session,
          phase: state.session.phase === "idle" ? "thinking" : state.session.phase,
          expertName: action.expertName || state.session.expertName,
        },
      };

    case "BUILD_START":
      return {
        ...state,
        stream: { ...EMPTY_STREAM, buildElapsed: 0 },
        pending: EMPTY_PENDING,
        session: { ...state.session, phase: "building" },
      };

    case "BUILD_COMPLETE":
      return {
        ...state,
        stream: { ...state.stream, thinking: false },
        session: { ...state.session, phase: "complete" },
      };

    case "IDLE":
      if (state.session.phase === "building" || state.session.phase === "thinking") {
        return {
          ...state,
          stream: { ...state.stream, thinking: false },
          session: { ...state.session, phase: "complete" },
        };
      }
      return { ...state, stream: { ...state.stream, thinking: false } };

    // ── Streaming ──
    case "STREAM_CHUNK":
      if (state.session.phase === "building") {
        return { ...state, stream: { ...state.stream, code: state.stream.code + action.content } };
      }
      // Text reply chunk — append to last assistant turn or create new one
      const lastTurn = state.session.turns[state.session.turns.length - 1];
      if (lastTurn?.role === "assistant") {
        const updatedTurns = [...state.session.turns];
        updatedTurns[updatedTurns.length - 1] = { ...lastTurn, content: lastTurn.content + action.content };
        return { ...state, session: { ...state.session, turns: updatedTurns } };
      }
      return {
        ...state,
        session: {
          ...state.session,
          turns: [...state.session.turns, { role: "assistant", content: action.content, timestamp: Date.now() }],
        },
      };

    case "STREAM_CODE_UPDATE":
      return { ...state, stream: { ...state.stream, code: action.code } };

    case "STREAM_HTML":
      return { ...state, stream: { ...state.stream, html: action.html } };

    // ── Transcript ──
    case "TRANSCRIPT_ENTRY":
      return {
        ...state,
        session: { ...state.session, transcript: [...state.session.transcript, action.entry] },
      };

    // ── Interaction ──
    case "DECISION_REQUEST":
      return {
        ...state,
        stream: { ...state.stream, thinking: false },
        pending: { ...state.pending, decisions: action.decisions },
      };

    case "PLAN_PROPOSAL":
      return {
        ...state,
        stream: { ...state.stream, thinking: false },
        pending: { ...state.pending, plans: action.plans, planRequest: action.request },
      };

    case "CLARIFY":
      return {
        ...state,
        stream: { ...state.stream, thinking: false },
        pending: { ...state.pending, clarifyQuestion: action.question },
      };

    case "DECISION_SUBMITTED":
      return { ...state, pending: { ...state.pending, decisions: null }, stream: { ...state.stream, thinking: true } };

    case "PLAN_SELECTED":
      return { ...state, pending: { ...state.pending, plans: null }, stream: { ...state.stream, thinking: true } };

    // ── User actions ──
    case "USER_SEND":
      return {
        ...state,
        session: {
          ...state.session,
          phase: state.session.phase === "idle" ? "thinking" : state.session.phase,
          turns: [...state.session.turns, { role: "user", content: action.text, timestamp: Date.now() }],
          userRequest: state.session.userRequest || action.text,
        },
        stream: { ...state.stream, thinking: true, thinkingElapsed: 0 },
        pending: EMPTY_PENDING,
      };

    case "RESET":
      return {
        ...INITIAL_STATE,
        session: { ...EMPTY_SESSION, id: action.sessionId },
        ui: state.ui, // preserve UI preferences
      };

    // ── Tool events ──
    case "FILE_WRITTEN":
      return { ...state, stream: { ...state.stream, fileName: action.fileName, fileSize: action.size } };

    case "VERSION_SAVED":
      return { ...state, session: { ...state.session, currentVersion: action.version } };

    // ── Timers ──
    case "TICK_THINKING":
      return { ...state, stream: { ...state.stream, thinkingElapsed: state.stream.thinkingElapsed + 1 } };

    case "TICK_ELAPSED":
      return { ...state, stream: { ...state.stream, buildElapsed: state.stream.buildElapsed + 1 } };

    // ── UI ──
    case "SET_UI":
      return { ...state, ui: { ...state.ui, [action.key]: action.value } };

    case "SET_UPLOAD":
      return {
        ...state,
        upload: {
          files: action.files ?? state.upload.files,
          uploading: action.uploading ?? state.upload.uploading,
        },
      };

    // ── Agent message ──
    case "AGENT_MESSAGE":
      return {
        ...state,
        stream: { ...state.stream, thinking: false },
        session: {
          ...state.session,
          turns: [...state.session.turns, { role: "assistant", content: action.content, timestamp: Date.now(), type: action.hasFiles ? "code" : "text" }],
        },
      };

    // ── Error ──
    case "ERROR":
      return { ...state, session: { ...state.session, phase: "idle" }, stream: { ...state.stream, thinking: false } };

    default:
      return state;
  }
}

// ═══════════════════════════════════════
// Helpers
// ═══════════════════════════════════════

function mapBackendSnapshot(payload: Record<string, any>, fallback: SessionState): SessionState {
  return {
    id: payload.session_id || fallback.id,
    phase: mapPhase(payload.phase) || fallback.phase,
    userRequest: payload.user_request || fallback.userRequest,
    codeFiles: payload.code_files || fallback.codeFiles,
    outputDir: payload.output_dir || fallback.outputDir,
    currentVersion: payload.current_version ?? fallback.currentVersion,
    versions: payload.versions || fallback.versions,
    transcript: payload.transcript || fallback.transcript,
    turns: (payload.turns || fallback.turns).map((t: any) => ({
      role: t.role,
      content: t.content,
      timestamp: t.timestamp ? t.timestamp * 1000 : Date.now(),
      type: t.type,
    })),
    planSummary: payload.plan_summary || fallback.planSummary,
    stepPlan: payload.step_plan || fallback.stepPlan,
    complexity: payload.complexity || fallback.complexity,
    expertName: payload.expert_name || fallback.expertName,
  };
}

function mapPhase(backendPhase: string | undefined): Phase | null {
  if (!backendPhase) return null;
  const map: Record<string, Phase> = { idle: "idle", building: "building", complete: "complete", thinking: "thinking" };
  return map[backendPhase] || null;
}

// ═══════════════════════════════════════
// Selectors (derived state)
// ═══════════════════════════════════════

export function hasArtifact(state: AppState): boolean {
  return state.session.phase === "building" || state.session.codeFiles.length > 0 || state.stream.code.length > 0 || state.stream.html !== null;
}

export function isActive(state: AppState): boolean {
  return state.session.phase !== "idle" || state.session.turns.length > 0;
}

export function hasBuildTranscript(state: AppState): boolean {
  return state.session.transcript.some(
    e => e.phase === "build" || e.phase === "plan" || e.phase === "analyze" || e.content?.includes("BUILD")
  );
}
