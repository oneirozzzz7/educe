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
  content: "processing" | "done";
}

export interface ErrorMessage {
  type: "error";
  content: string;
}

export type ServerMessage = AgentMessage | StatusMessage | ErrorMessage;

export interface DeepForgeWS {
  send: (message: string) => void;
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
    ws = new WebSocket(url);
    ws.onopen = () => connectHandlers.forEach((h) => h());
    ws.onclose = () => {
      disconnectHandlers.forEach((h) => h());
      reconnectTimer = setTimeout(connect, 3000);
    };
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data) as ServerMessage;
      messageHandlers.forEach((h) => h(data));
    };
  }

  connect();

  return {
    send: (message: string) => ws?.send(JSON.stringify({ message })),
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
