"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { API_HOST } from "@/lib/ws";

interface OrganStatus {
  id: string;
  family: string;
  state: string;
  confidence: number;
  observe_count: number;
  confirm_count: number;
  hint: string | null;
}

const STATE_COLORS: Record<string, string> = {
  idle: "var(--text-3)",
  observing: "#22d3ee",
  proposed: "#f59e0b",
  revert_proposed: "#f59e0b",
  crystallized: "#22c55e",
  dismissed: "var(--text-3)",
};

const STATE_LABELS: Record<string, string> = {
  idle: "未激活",
  observing: "观察中",
  proposed: "待确认",
  revert_proposed: "建议撤销",
  crystallized: "已生效",
  dismissed: "已忽略",
};

export function EvolutionBar() {
  const [organs, setOrgans] = useState<OrganStatus[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const load = () => {
      fetch(`http://${API_HOST}/api/evolution/status`)
        .then(r => r.json())
        .then(d => setOrgans(d.organs || []))
        .catch(() => {});
    };
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const activeOrgans = organs.filter(o => o.state !== "idle" && o.state !== "dismissed");
  const avgConfidence = activeOrgans.length > 0
    ? activeOrgans.reduce((s, o) => s + o.confidence, 0) / activeOrgans.length
    : 0;
  const crystallized = organs.filter(o => o.state === "crystallized").length;

  if (organs.length === 0) return null;

  async function handleRevert(organId: string) {
    const res = await fetch(`http://${API_HOST}/api/evolution/revert/${organId}`, { method: "POST" });
    if (res.ok) {
      setOrgans(prev => prev.map(o => o.id === organId ? { ...o, state: "idle", confidence: 0 } : o));
    }
  }

  return (
    <div className="mb-2">
      {/* 常驻摘要条 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-left transition-colors"
        style={{ background: expanded ? "var(--bg-code)" : "transparent" }}
      >
        <span style={{ color: "#22d3ee", fontSize: 12 }}>⚡</span>
        <span className="text-[11px] flex-1" style={{ color: "var(--text-2)" }}>
          {crystallized > 0
            ? `${crystallized} 个偏好已生效`
            : activeOrgans.length > 0
              ? `进化中 · ${activeOrgans.length} 个观察`
              : "进化待机"}
        </span>
        {activeOrgans.length > 0 && (
          <div className="flex items-center gap-1.5">
            <div className="h-1 w-12 rounded-full" style={{ background: "var(--border-light)" }}>
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${avgConfidence * 100}%`, background: "#22d3ee" }}
              />
            </div>
            <span className="text-[10px]" style={{ color: "var(--text-3)" }}>
              {Math.round(avgConfidence * 100)}%
            </span>
          </div>
        )}
        <span className="text-[10px]" style={{ color: "var(--text-3)" }}>
          {expanded ? "▴" : "▾"}
        </span>
      </button>

      {/* 展开详情 */}
      {expanded && (
        <div className="mt-1 rounded-xl p-3" style={{ background: "var(--bg-code)", border: "1px solid var(--border-light)" }}>
          {organs.map(organ => {
            const color = STATE_COLORS[organ.state] || "var(--text-3)";
            const label = STATE_LABELS[organ.state] || organ.state;
            return (
              <div key={organ.id} className="flex items-center gap-2 py-1.5">
                <span className="text-[11px] w-16" style={{ color: "var(--text-2)" }}>
                  {organ.family === "verbosity" ? "回答详略" : organ.family}
                </span>
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{ background: `${color}15`, color }}
                >
                  {label}
                </span>
                <div className="flex-1 h-1 rounded-full" style={{ background: "var(--border-light)" }}>
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${organ.confidence * 100}%`, background: color }}
                  />
                </div>
                <span className="text-[10px] w-8 text-right" style={{ color: "var(--text-3)" }}>
                  {Math.round(organ.confidence * 100)}%
                </span>
                {organ.hint && (
                  <span className="text-[10px] truncate max-w-[120px]" style={{ color: "var(--text-3)" }}>
                    {organ.hint}
                  </span>
                )}
                {(organ.state === "crystallized" || organ.state === "proposed") && (
                  <button
                    onClick={() => handleRevert(organ.id)}
                    className="text-[10px] px-1.5 py-0.5 rounded hover:opacity-80"
                    style={{ color: "#ef4444", background: "rgba(239,68,68,0.08)" }}
                  >
                    撤销
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
