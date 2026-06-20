"use client";

import { cn } from "@/lib/utils";

interface ProposeCardProps {
  eventId: string;
  phrase: string;
  cause: string;
  confidence: number;
  organ: { family: string; id: string | null };
  onCalibrate: (action: "confirm" | "dismiss" | "snooze", eventId: string) => void;
}

export function ProposeCard({ eventId, phrase, cause, confidence, organ, onCalibrate }: ProposeCardProps) {
  return (
    <div
      className="rounded-xl overflow-hidden my-3 animate-in slide-in-from-bottom-2"
      style={{
        background: "var(--bg-elevated)",
        border: "1px solid var(--border)",
        borderLeft: "3px solid #22d3ee",
        boxShadow: "var(--shadow)",
      }}
    >
      {/* Header */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[13px]">?</span>
          <span className="text-[13px] font-medium" style={{ color: "var(--text)" }}>
            {phrase}
          </span>
          <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee" }}>
            {Math.round(confidence * 100)}%
          </span>
        </div>
        <p className="text-[12px] ml-5" style={{ color: "var(--text-2)" }}>
          {cause}
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 px-4 pb-3">
        <button
          onClick={() => onCalibrate("confirm", eventId)}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-opacity hover:opacity-80"
          style={{ background: "#22d3ee", color: "#000" }}
        >
          对，就这样
        </button>
        <button
          onClick={() => onCalibrate("snooze", eventId)}
          className="px-3 py-1.5 rounded-lg text-[12px] transition-opacity hover:opacity-80"
          style={{ background: "var(--bg-code)", color: "var(--text-2)" }}
        >
          看情况
        </button>
        <button
          onClick={() => onCalibrate("dismiss", eventId)}
          className="px-3 py-1.5 rounded-lg text-[12px] transition-opacity hover:opacity-80"
          style={{ background: "var(--bg-code)", color: "var(--text-3)" }}
        >
          不用
        </button>
      </div>
    </div>
  );
}

export function ReflexBubble({ phrase }: { phrase: string }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 my-1 rounded-lg"
      style={{
        borderLeft: "2px solid #22d3ee",
        background: "rgba(34,211,238,0.04)",
      }}
    >
      <span style={{ color: "#22d3ee" }}>⚡</span>
      <span className="text-[12px]" style={{ color: "var(--text-2)" }}>
        {phrase}
      </span>
    </div>
  );
}
