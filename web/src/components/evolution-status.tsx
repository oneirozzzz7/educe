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
  last_updated: number;
}

const STATE_LABELS: Record<string, { label: string; color: string }> = {
  idle: { label: "未激活", color: "var(--text-3)" },
  observing: { label: "观察中", color: "#22d3ee" },
  proposed: { label: "已提议", color: "#f59e0b" },
  revert_proposed: { label: "建议撤销", color: "#f59e0b" },
  crystallized: { label: "已固化", color: "#22c55e" },
  dismissed: { label: "已忽略", color: "var(--text-3)" },
};

export function EvolutionStatusPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [organs, setOrgans] = useState<OrganStatus[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetch(`http://${API_HOST}/api/evolution/status`)
      .then(r => r.json())
      .then(d => setOrgans(d.organs || []))
      .catch(() => setOrgans([]))
      .finally(() => setLoading(false));
  }, [open]);

  async function handleRevert(organId: string) {
    const res = await fetch(`http://${API_HOST}/api/evolution/revert/${organId}`, { method: "POST" });
    if (res.ok) {
      setOrgans(prev => prev.map(o => o.id === organId ? { ...o, state: "idle", confidence: 0 } : o));
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl p-6 max-w-lg w-full mx-4"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[15px] font-semibold" style={{ color: "var(--text)" }}>
            进化状态
          </h2>
          <button onClick={onClose} className="text-[13px]" style={{ color: "var(--text-3)" }}>✕</button>
        </div>

        {loading && <p className="text-[13px]" style={{ color: "var(--text-3)" }}>加载中...</p>}

        {!loading && organs.length === 0 && (
          <p className="text-[13px]" style={{ color: "var(--text-3)" }}>
            暂无进化记录。系统会在观察到你的使用模式后自动开始学习。
          </p>
        )}

        {organs.map(organ => {
          const stateInfo = STATE_LABELS[organ.state] || { label: organ.state, color: "var(--text-3)" };
          return (
            <div
              key={organ.id}
              className="rounded-xl p-4 mb-3"
              style={{ background: "var(--bg-code)", border: "1px solid var(--border-light)" }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium" style={{ color: "var(--text)" }}>
                    {organ.family === "verbosity" ? "回答详略" : organ.family}
                  </span>
                  <span
                    className="text-[11px] px-2 py-0.5 rounded-full"
                    style={{ background: `${stateInfo.color}20`, color: stateInfo.color }}
                  >
                    {stateInfo.label}
                  </span>
                </div>
                <span className="text-[11px]" style={{ color: "var(--text-3)" }}>
                  {Math.round(organ.confidence * 100)}%
                </span>
              </div>

              {/* Confidence bar */}
              <div className="h-1.5 rounded-full mb-2" style={{ background: "var(--border-light)" }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${organ.confidence * 100}%`, background: stateInfo.color }}
                />
              </div>

              {/* Hint preview */}
              {organ.hint && (
                <p className="text-[11px] mb-2" style={{ color: "var(--text-2)" }}>
                  当前注入：{organ.hint}
                </p>
              )}

              {/* Stats */}
              <div className="flex items-center gap-3 text-[11px]" style={{ color: "var(--text-3)" }}>
                <span>观察 {organ.observe_count} 次</span>
                <span>确认 {organ.confirm_count} 次</span>
              </div>

              {/* Revert button */}
              {(organ.state === "crystallized" || organ.state === "proposed" || organ.state === "revert_proposed") && (
                <button
                  onClick={() => handleRevert(organ.id)}
                  className="mt-3 px-3 py-1.5 rounded-lg text-[12px] transition-opacity hover:opacity-80"
                  style={{ background: "rgba(239,68,68,0.1)", color: "#ef4444" }}
                >
                  撤销此偏好
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
