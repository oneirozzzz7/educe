export type AgentId =
  | "project_manager"
  | "product_manager"
  | "architect"
  | "engineer"
  | "reviewer"
  | "crowd_user"
  | "memory_keeper";

export interface AgentMessage {
  type: "agent_message";
  sender: AgentId;
  summary: string;
  content: string;
  msg_type: string;
  timestamp: number;
  has_files: boolean;
}

export interface StatusMessage {
  type: "status";
  content: "thinking" | "idle" | "pipeline_start" | "processing" | "done" | "chat_done";
}

export interface ChunkMessage {
  type: "chunk";
  sender: string;
  content: string;
}

export interface ErrorMessage {
  type: "error";
  content: string;
}

export type ServerMessage = AgentMessage | StatusMessage | ChunkMessage | ErrorMessage;

export interface DeepForgeWS {
  send: (message: string, fileIds?: string[]) => void;
  readonly readyState: number;
  close: () => void;
  onMessage: (handler: (msg: ServerMessage) => void) => void;
  onConnect: (handler: () => void) => void;
  onDisconnect: (handler: () => void) => void;
}

export const API_HOST = typeof window !== "undefined"
  ? (window as any).__DEEPFORGE_API_HOST || "localhost:7860"
  : "localhost:7860";

export function createWS(sessionId: string): DeepForgeWS {
  const proto = typeof window !== "undefined" && location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${API_HOST}/ws/${sessionId}`;

  let ws: WebSocket | null = null;
  let messageHandlers: ((msg: ServerMessage) => void)[] = [];
  let connectHandlers: (() => void)[] = [];
  let disconnectHandlers: (() => void)[] = [];
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    console.log("[DeepForge] Connecting to", url);
    ws = new WebSocket(url);
    ws.onopen = () => { console.log("[DeepForge] Connected"); connectHandlers.forEach((h) => h()) };
    ws.onclose = (e) => {
      console.log("[DeepForge] Disconnected", e.code, e.reason);
      disconnectHandlers.forEach((h) => h());
      reconnectTimer = setTimeout(connect, 3000);
    };
    ws.onerror = (e) => { console.error("[DeepForge] WebSocket error", e) };
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data) as ServerMessage;
      console.log("[DeepForge] Received", data.type, (data as any).sender || "");
      messageHandlers.forEach((h) => h(data));
    };
  }

  connect();

  return {
    send: (message: string, fileIds?: string[]) => ws?.send(JSON.stringify({ message, file_ids: fileIds || [] })),
    get readyState() { return ws?.readyState ?? 3; },
    close: () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    },
    onMessage: (handler) => messageHandlers.push(handler),
    onConnect: (handler) => connectHandlers.push(handler),
    onDisconnect: (handler) => disconnectHandlers.push(handler),
  };
}

export const AGENTS: { id: AgentId; name: string; icon: string }[] = [
  { id: "project_manager", name: "项目经理", icon: "🎯" },
  { id: "product_manager", name: "产品经理", icon: "📋" },
  { id: "architect", name: "架构师", icon: "🏗" },
  { id: "engineer", name: "工程师", icon: "💻" },
  { id: "reviewer", name: "审查", icon: "🔍" },
  { id: "crowd_user", name: "内测", icon: "👥" },
  { id: "memory_keeper", name: "沉淀", icon: "🧠" },
];
