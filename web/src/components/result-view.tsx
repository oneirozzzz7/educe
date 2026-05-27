"use client";

import { useState, useMemo } from "react";
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
  html: string;
  code: string;
  onSend: (text: string) => void;
  onNew: () => void;
}

export function ResultView({ task, steps, elapsed, html, code, onSend, onNew }: Props) {
  const [tab, setTab] = useState<"preview" | "code">("preview");
  const [showSteps, setShowSteps] = useState(false);
  const [input, setInput] = useState("");

  const blobUrl = useMemo(() => {
    if (!html) return "";
    return URL.createObjectURL(new Blob([html], { type: "text/html" }));
  }, [html]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 完成摘要条 */}
      <div
        onClick={() => setShowSteps(!showSteps)}
        className="px-5 py-2 flex items-center gap-2 bg-green-500/8 border-b border-green-500/15 cursor-pointer hover:bg-green-500/12 transition-colors"
      >
        <span className="text-xs text-green-400">✓ 完成</span>
        <span className="text-xs text-neutral-400 truncate flex-1">{task}</span>
        <span className="text-[10px] font-mono text-neutral-500">{elapsed}s</span>
        <span className="text-[10px] text-neutral-600">{showSteps ? "▲" : "▼"}</span>
      </div>

      {/* 可折叠步骤 */}
      {showSteps && (
        <div className="border-b border-border px-5 py-1 bg-surface max-h-48 overflow-y-auto">
          {steps.filter((s) => s.status === "done").map((s) => {
            const agent = AGENTS.find((a) => a.id === s.id);
            return (
              <div key={s.id} className="flex items-center gap-2 py-1.5 text-xs">
                <span className="text-green-400">✓</span>
                <span className="text-neutral-400 w-14">{agent?.name}</span>
                <span className="text-neutral-500 flex-1 truncate">{s.summary}</span>
                <span className="text-neutral-600 font-mono text-[10px]">{s.time}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* 预览区 */}
      {html ? (
        <>
          <div className="px-4 py-1.5 flex items-center gap-2 bg-surface border-b border-border">
            <div className="flex gap-1.5">
              <i className="w-2.5 h-2.5 rounded-full bg-red-500 block" />
              <i className="w-2.5 h-2.5 rounded-full bg-amber-500 block" />
              <i className="w-2.5 h-2.5 rounded-full bg-green-500 block" />
            </div>
            <div className="flex-1" />
            <div className="flex gap-px">
              <button
                onClick={() => setTab("preview")}
                className={`px-3 py-1 rounded text-[10px] transition-colors ${tab === "preview" ? "bg-surface-2 text-white" : "text-neutral-500 hover:text-white"}`}
              >
                预览
              </button>
              <button
                onClick={() => setTab("code")}
                className={`px-3 py-1 rounded text-[10px] transition-colors ${tab === "code" ? "bg-surface-2 text-white" : "text-neutral-500 hover:text-white"}`}
              >
                代码
              </button>
            </div>
            <button
              onClick={() => window.open(blobUrl, "_blank")}
              className="text-[10px] text-accent hover:underline"
            >
              ↗ 新窗口
            </button>
          </div>
          <div className="flex-1 relative">
            {tab === "preview" ? (
              <iframe src={blobUrl} className="w-full h-full border-none bg-white" />
            ) : (
              <pre className="absolute inset-0 overflow-auto p-4 font-mono text-[11px] text-neutral-400 whitespace-pre-wrap break-all bg-bg">
                {code}
              </pre>
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-neutral-600 text-sm">
          没有可预览的产出物
        </div>
      )}

      {/* 底部输入 */}
      <div className="border-t border-border px-5 py-2.5 bg-surface flex gap-2 items-end">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(input); setInput(""); }
          }}
          placeholder="修改需求继续迭代..."
          rows={1}
          className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-xs text-white resize-none outline-none min-h-[34px] max-h-[60px] focus:border-accent"
        />
        <button onClick={onNew} className="px-3 py-1.5 text-[10px] border border-border rounded text-neutral-500 hover:border-accent hover:text-accent transition-colors">
          新任务
        </button>
      </div>
    </div>
  );
}
