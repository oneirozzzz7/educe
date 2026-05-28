"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { API_HOST } from "@/lib/ws";

export function SettingsModal({ open, onClose, model, onModelChange }: {
  open: boolean; onClose: () => void; model: string; onModelChange: (m: string) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState(model);
  const [evolution, setEvolution] = useState(true);

  useEffect(() => {
    if (open) {
      setSelected(model);
      fetch(`http://${API_HOST}/api/models`).then(r => r.json()).then(d => setModels(d.models || [])).catch(() => {});
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => {
        if (d.evolution !== undefined) setEvolution(d.evolution);
      }).catch(() => {});
    }
  }, [open, model]);

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.2)", backdropFilter: "blur(4px)" }}
        onClick={onClose}>
        <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
          className="w-[400px] rounded-2xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", boxShadow: "var(--shadow-md)" }}
          onClick={e => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-5">
            <h3 className="font-semibold text-[15px]" style={{ color: "var(--text)" }}>设置</h3>
            <button onClick={onClose} style={{ color: "var(--text-3)" }}><X size={16} /></button>
          </div>

          {/* 模型选择 */}
          <label className="block text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-3)" }}>模型</label>
          <select value={selected} onChange={e => setSelected(e.target.value)}
            className="w-full rounded-lg px-3 py-2.5 text-sm outline-none mb-5 cursor-pointer"
            style={{ background: "var(--bg-sunken)", border: "1px solid var(--border)", color: "var(--text)" }}>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>

          {/* 自进化开关 */}
          <div className="flex items-center justify-between mb-5">
            <div>
              <label className="block text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-3)" }}>自进化</label>
              <span className="text-[12px]" style={{ color: "var(--text-4)" }}>使用过程中自动积累经验</span>
            </div>
            <button onClick={() => setEvolution(!evolution)}
              className="relative w-10 h-[22px] rounded-full transition-colors"
              style={{ background: evolution ? "var(--brand)" : "var(--bg-sunken)", border: "1px solid var(--border)" }}>
              <span className="absolute top-[2px] w-4 h-4 rounded-full transition-transform shadow-sm"
                style={{ background: "white", left: evolution ? "20px" : "2px" }} />
            </button>
          </div>

          <div className="flex gap-2 justify-end">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg" style={{ background: "var(--bg-sunken)", color: "var(--text-2)" }}>取消</button>
            <button onClick={async () => {
              try {
                const r = await fetch(`http://${API_HOST}/api/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: selected, evolution }) });
                const d = await r.json();
                if (d.status === "ok") { onModelChange(d.model); onClose(); }
              } catch { alert("保存失败") }
            }} className="px-4 py-2 text-sm text-white rounded-lg" style={{ background: "var(--brand)" }}>保存</button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
