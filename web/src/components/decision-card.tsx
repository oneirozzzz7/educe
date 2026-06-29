"use client";

import { motion } from "framer-motion";
import { HelpCircle, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useLocale } from "@/lib/i18n";

interface Decision {
  question: string;
  options: string[];
}

export function DecisionCard({ decisions, onSubmit }: {
  decisions: Decision[];
  onSubmit: (choices: { question: string; choice: string }[]) => void;
}) {
  const { t } = useLocale();
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);
  const [userNote, setUserNote] = useState("");

  const allSelected = Object.keys(selections).length === decisions.length;

  function handleSubmit() {
    const choices = decisions.map((d, i) => ({
      question: d.question,
      choice: d.options[selections[i] ?? 0] + (userNote ? ` (${userNote})` : ""),
    }));
    setSubmitted(true);
    onSubmit(choices);
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl p-4" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
      <div className="flex items-center gap-2 mb-3">
        <HelpCircle size={16} style={{ color: "var(--brand)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
          {t("decision.hint")}
        </span>
      </div>

      <div className="space-y-3">
        {decisions.map((decision, di) => (
          <div key={di}>
            <div className="text-[13px] font-medium mb-1.5" style={{ color: "var(--text-2)" }}>
              {decision.question}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {decision.options.map((option, oi) => (
                <button key={oi}
                  disabled={submitted}
                  onClick={() => setSelections(prev => ({ ...prev, [di]: oi }))}
                  className="text-[12px] px-3 py-1.5 rounded-lg border transition-all"
                  style={{
                    background: selections[di] === oi ? "var(--brand-subtle)" : "var(--bg)",
                    borderColor: selections[di] === oi ? "var(--brand)" : "var(--border-light)",
                    color: selections[di] === oi ? "var(--brand)" : "var(--text-2)",
                    opacity: submitted ? 0.6 : 1,
                  }}>
                  {option}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {!submitted && (
        <div className="mt-3 space-y-2">
          <input type="text" value={userNote} onChange={e => setUserNote(e.target.value)}
            placeholder={t("decision.note_placeholder")}
            className="w-full text-[12px] px-3 py-2 rounded-lg outline-none transition-colors focus:border-[var(--brand)]"
            style={{ background: "var(--bg)", border: "1px solid var(--border-light)", color: "var(--text-2)" }}
            onKeyDown={e => { if (e.key === "Enter" && allSelected) handleSubmit(); }} />
          <div className="flex items-center gap-2">
          <button onClick={handleSubmit}
            disabled={!allSelected}
            className="text-[13px] px-4 py-1.5 rounded-lg font-medium transition-all flex items-center gap-1"
            style={{
              background: allSelected ? "var(--brand)" : "var(--bg-sunken)",
              color: allSelected ? "white" : "var(--text-4)",
              opacity: allSelected ? 1 : 0.6,
            }}>
            {t("decision.confirm")} <ChevronRight size={14} />
          </button>
          <button onClick={() => { setSubmitted(true); onSubmit([]); }}
            className="text-[12px] px-3 py-1.5 rounded-lg transition-colors hover:bg-[var(--brand-subtle)]"
            style={{ color: "var(--text-3)" }}>
            {t("decision.skip")}
          </button>
          </div>
        </div>
      )}

      {submitted && (
        <div className="mt-2 flex items-center gap-1 text-[11px]" style={{ color: "var(--brand)" }}>
          <ChevronRight size={12} /> {t("decision.building")}
        </div>
      )}
    </motion.div>
  );
}
