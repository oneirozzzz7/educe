"use client";

import { useState } from "react";
import { AGENTS, type AgentId } from "@/lib/ws";

interface StepState {
  id: AgentId;
  status: "wait" | "active" | "done";
  summary: string;
  time: string;
}

interface Props {
  task: string;
  steps: StepState[];
  elapsed: number;
  onSend: (text: string) => void;
}

export function WorkView({ task, steps, elapsed, onSend }: Props) {
  const [input, setInput] = useState("");

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 任务头 */}
      <div className="px-5 py-3 flex items-center gap-2 border-b border-border bg-surface">
        <span className="flex-1 text-sm font-medium truncate">{task}</span>
        <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 font-medium">进行中</span>
        <span className="text-xs font-mono text-amber-400">{elapsed}s</span>
      </div>

      {/* 进度条 */}
      <div className="px-5 py-2 flex gap-1">
        {steps.map((s) => (
          <div
            key={s.id}
            className={`flex-1 h-0.5 rounded-full transition-colors duration-300 ${
              s.status === "done" ? "bg-green-500" : s.status === "active" ? "bg-amber-400 animate-pulse" : "bg-neutral-800"
            }`}
          />
        ))}
      </div>

      {/* 步骤列表 */}
      <div className="flex-1 overflow-y-auto px-5 py-2">
        {steps.map((s) => {
          const agent = AGENTS.find((a) => a.id === s.id);
          return (
            <div
              key={s.id}
              className={`flex items-center gap-3 py-2.5 px-3 mb-1 rounded-lg transition-all ${
                s.status === "active" ? "bg-amber-500/8" : ""
              }`}
            >
              <div
                className={`w-7 h-7 rounded-md flex items-center justify-center text-sm shrink-0 border transition-all ${
                  s.status === "done"
                    ? "bg-green-500/10 border-green-500/30 text-green-400"
                    : s.status === "active"
                    ? "bg-amber-500/10 border-amber-500/30 text-amber-400 animate-pulse"
                    : "bg-neutral-800/50 border-neutral-700/30 opacity-25"
                }`}
              >
                {s.status === "done" ? "✓" : agent?.icon}
              </div>
              <span className={`text-xs font-medium w-16 shrink-0 ${s.status === "wait" ? "text-neutral-600" : "text-neutral-300"}`}>
                {agent?.name}
              </span>
              <span className={`text-xs flex-1 truncate ${
                s.status === "active" ? "text-amber-400" : s.status === "done" ? "text-neutral-400" : "text-neutral-700"
              }`}>
                {s.status === "wait" ? "—" : s.status === "active" ? "进行中..." : s.summary}
              </span>
              <span className="text-[10px] font-mono text-neutral-600 shrink-0">{s.time}</span>
            </div>
          );
        })}
      </div>

      {/* 底部输入 */}
      <div className="border-t border-border px-5 py-2.5 bg-surface">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(input); setInput(""); }
            }}
            placeholder="追加需求或修改..."
            rows={1}
            className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-xs text-white resize-none outline-none min-h-[34px] max-h-[60px] focus:border-accent"
          />
          <button
            onClick={() => { onSend(input); setInput(""); }}
            className="w-7 h-7 rounded-full bg-accent flex items-center justify-center shrink-0"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
