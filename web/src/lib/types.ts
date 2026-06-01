export type AppPhase = "idle" | "thinking" | "deciding" | "building" | "complete";
export type BuildMode = "build" | "conversation";
export type Locale = "en" | "zh";

export interface ToolEvent {
  event: string;
  content?: string;
  file?: string;
  size?: number;
  command?: string;
  success?: boolean;
  output?: string;
  files?: string[];
  turns?: number;
}

export interface BuildState {
  html: string | null;
  streamingCode: string;
  toolEvents: ToolEvent[];
  steps: { agent: string; summary: string; done: boolean }[];
  elapsed: number;
  currentAgent: string;
  brief: string;
  files: { name: string; size: number }[];
}

export interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system" | "plan" | "decision";
  text: string;
  steps?: { agent: string; summary: string; done: boolean }[];
  html?: string;
  streamingCode?: string;
  toolEvents?: ToolEvent[];
  timestamp: number;
  files?: UploadedFile[];
  plans?: { id: number; title: string; desc: string; est: string }[];
  decisions?: { question: string; options: string[] }[];
  originalRequest?: string;
}

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  is_image: boolean;
  error?: string;
}

export interface TaskItem {
  id: string;
  request?: string;
  title?: string;
  project_type?: string;
  created_at: number;
  updated_at?: number;
  turns?: any[];
  response?: string;
}
