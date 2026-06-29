"use client";

import { useEffect, useState } from "react";
import { API_HOST } from "@/lib/ws";
import { useLocale } from "@/lib/i18n";

interface ConvergenceData {
  curve: number[];
  claims: { id: string; text: string; status: string }[];
  convergence: number;
  revisions: number;
  has_edits?: boolean;
}

export function ConvergencePanel({ sessionId }: { sessionId: string }) {
  const { t } = useLocale();
  const [data, setData] = useState<ConvergenceData | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    const poll = async () => {
      try {
        const res = await fetch(`http://${API_HOST}/api/convergence/${sessionId}`);
        const json = await res.json();
        if (json.curve?.length > 0) setData(json);
      } catch {}
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [sessionId]);

  if (!data || data.curve.length < 2) return null;

  const { curve, convergence, claims, has_edits } = data;
  const verified = claims.filter(c => c.status === "verified").length;
  const open = claims.filter(c => c.status === "open").length;
  const total = claims.length;

  const isStalled = curve.length >= 5 && convergence < 1.0 &&
    Math.max(...curve.slice(-5)) - Math.min(...curve.slice(-5)) < 0.02;

  const dotColor = isStalled ? "#e04040" : has_edits ? "#16a34a" : convergence >= 1.0 ? "#eab308" : "#e04040";
  const statusText = isStalled ? t("convergence.stalled") : has_edits ? t("convergence.edited") : convergence >= 1.0 ? t("convergence.exploring_done") : convergence >= 0.8 ? t("convergence.exploring") : t("convergence.in_progress");

  return (
    <div style={{ borderTop: "1px solid var(--border-1, #2a2a2a)", marginBottom: 4 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          width: "100%", height: 28, padding: "0 12px",
          background: "none", border: "none", cursor: "pointer",
          fontSize: 11, color: "var(--text-3, #a0a0a0)", textAlign: "left",
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
        <span style={{ color: dotColor, fontWeight: 500 }}>
          {(convergence * 100).toFixed(0)}%
        </span>
        <span>{statusText}</span>
        <span style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums", color: "var(--text-3)" }}>
          {isStalled ? t("convergence.retry_hint") : `${verified}/${total}`}
          {!isStalled && open > 0 && ` · ${open} ${t("convergence.pending")}`}
        </span>
        <span style={{ fontSize: 10, transition: "transform 0.15s", transform: expanded ? "rotate(180deg)" : "none" }}>▾</span>
      </button>

      {expanded && (
        <div style={{ padding: "6px 12px 10px", borderTop: "1px solid var(--border-1, #2a2a2a)" }}>
          <MiniChart curve={curve} color={dotColor} />
          {claims.filter(c => c.status === "open").length > 0 && (
            <div style={{ marginTop: 6, fontSize: 10, color: "#e04040" }}>
              {claims.filter(c => c.status === "open").map(c => (
                <div key={c.id}>⚠ {c.text}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MiniChart({ curve, color }: { curve: number[]; color: string }) {
  const W = 180, H = 32, PAD = 2;
  const n = curve.length;
  const xStep = (W - PAD * 2) / Math.max(n - 1, 1);
  const points = curve.map((v, i) => ({
    x: PAD + i * xStep,
    y: PAD + (1 - v) * (H - PAD * 2),
  }));
  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  return (
    <svg width={W} height={H}>
      <path d={pathD} fill="none" stroke={color} strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round" opacity={0.7} />
      {points.length > 0 && (
        <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r={2} fill={color} />
      )}
    </svg>
  );
}
