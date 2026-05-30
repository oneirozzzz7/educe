"use client";

import { motion } from "framer-motion";
import { Sparkles, ChevronRight } from "lucide-react";
import { useState } from "react";

interface Plan {
  id: number;
  title: string;
  desc: string;
  est: string;
}

export function PlanProposal({ plans, onSelect, originalRequest }: {
  plans: Plan[];
  onSelect: (planId: number, userNote: string) => void;
  originalRequest: string;
}) {
  const [userNote, setUserNote] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  function handleSelect(planId: number) {
    setSelected(planId);
    onSelect(planId, userNote);
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl p-4" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={16} style={{ color: "var(--brand)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
          这是一个复杂项目，建议先选择方案
        </span>
      </div>

      <div className="grid gap-2">
        {plans.map((plan) => (
          <button key={plan.id} onClick={() => handleSelect(plan.id)}
            disabled={selected !== null}
            className="text-left p-3 rounded-xl transition-all border"
            style={{
              background: selected === plan.id ? "var(--brand-subtle)" : "var(--bg)",
              borderColor: selected === plan.id ? "var(--brand)" : "var(--border-light)",
              opacity: selected !== null && selected !== plan.id ? 0.5 : 1,
            }}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
                {plan.title}
              </span>
              {plan.est && (
                <span className="text-[11px] px-2 py-0.5 rounded-full"
                  style={{ background: "var(--bg-sunken)", color: "var(--text-3)" }}>
                  {plan.est}
                </span>
              )}
            </div>
            <p className="text-[12px] mt-1" style={{ color: "var(--text-2)" }}>
              {plan.desc}
            </p>
            {selected === plan.id && (
              <div className="flex items-center gap-1 mt-2 text-[11px]" style={{ color: "var(--brand)" }}>
                <ChevronRight size={12} /> 正在构建...
              </div>
            )}
          </button>
        ))}
      </div>

      {selected === null && (
        <div className="mt-3">
          <input type="text" value={userNote} onChange={e => setUserNote(e.target.value)}
            placeholder="补充你的想法（可选）"
            className="w-full text-[12px] px-3 py-2 rounded-lg outline-none"
            style={{ background: "var(--bg-sunken)", border: "1px solid var(--border-light)", color: "var(--text-2)" }}
            onKeyDown={e => { if (e.key === "Enter" && plans.length > 0) handleSelect(plans[0].id); }} />
        </div>
      )}
    </motion.div>
  );
}
