"use client";

import { useEffect, useState } from "react";
import { API_HOST } from "@/lib/ws";

interface ConvergenceData {
  curve: number[];
  claims: { id: string; text: string; status: string }[];
  convergence: number;
  revisions: number;
}

export function ConvergencePanel({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<ConvergenceData | null>(null);

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

  const { curve, claims, convergence } = data;
  const W = 200, H = 60, PAD = 4;
  const n = curve.length;
  const xStep = (W - PAD * 2) / Math.max(n - 1, 1);

  const points = curve.map((v, i) => ({
    x: PAD + i * xStep,
    y: PAD + (1 - v) * (H - PAD * 2),
  }));
  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  const verified = claims.filter(c => c.status === "verified").length;
  const open = claims.filter(c => c.status === "open").length;
  const total = claims.length;

  const color = convergence >= 0.9 ? "var(--accent)" : convergence >= 0.7 ? "#f0a030" : "#e04040";

  return (
    <div style={{
      padding: "8px 12px",
      borderRadius: 8,
      background: "var(--surface-1)",
      border: "1px solid var(--border-1)",
      fontSize: 11,
      display: "flex",
      alignItems: "center",
      gap: 12,
    }}>
      <svg width={W} height={H} style={{ flexShrink: 0 }}>
        <rect x={0} y={0} width={W} height={H} rx={4} fill="var(--surface-2)" />
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD}
          stroke="var(--border-1)" strokeWidth={0.5} />
        <path d={pathD} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
        {points.length > 0 && (
          <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y}
            r={2.5} fill={color} />
        )}
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ fontWeight: 600, color }}>
          {(convergence * 100).toFixed(0)}%
        </span>
        <span style={{ color: "var(--text-3)" }}>
          {verified}/{total} verified
          {open > 0 && <span style={{ color: "#e04040" }}> · {open} open</span>}
        </span>
      </div>
    </div>
  );
}
