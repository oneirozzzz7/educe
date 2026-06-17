"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Eye, EyeOff } from "lucide-react";
import { API_HOST } from "@/lib/ws";

const PROVIDER_PRESETS: Record<string, { base_url: string; models: string[] }> = {
  "DeepSeek V4": { base_url: "http://api.example.com/v1", models: ["DeepSeek-V4-Flash"] },
  "Qwen 3.5": { base_url: "", models: ["Qwen3.5-397B-A17B"] },
  "Kimi K2": { base_url: "http://api.example.com/v1", models: ["Kimi-K2"] },
  "GLM 5": { base_url: "http://api.example.com/v1", models: ["GLM-5.1", "GLM-5"] },
  "DeepSeek": { base_url: "https://api.deepseek.com/v1", models: ["deepseek-chat", "DeepSeek-V4-Flash"] },
  "OpenAI": { base_url: "https://api.openai.com/v1", models: ["gpt-4o", "gpt-4.1", "gpt-4o-mini", "o3-mini"] },
  "Claude": { base_url: "https://api.anthropic.com/v1", models: ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"] },
  "Kimi": { base_url: "https://api.moonshot.cn/v1", models: ["moonshot-v1-8k", "moonshot-v1-32k"] },
  "通义千问": { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen-plus", "qwen-max"] },
  "智谱 GLM": { base_url: "https://open.bigmodel.cn/api/paas/v4", models: ["glm-4-flash", "GLM-5.1"] },
  "Gemini": { base_url: "https://generativelanguage.googleapis.com/v1beta/openai", models: ["gemini-2.5-flash", "gemini-2.5-pro"] },
  "自定义": { base_url: "", models: [] },
};

export function SettingsModal({ open, onClose, model, onModelChange }: {
  open: boolean; onClose: () => void; model: string; onModelChange: (m: string) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState(model);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [evolution, setEvolution] = useState(true);
  const [showKey, setShowKey] = useState(false);
  const [provider, setProvider] = useState("");
  const [saving, setSaving] = useState(false);
  const [hasKey, setHasKey] = useState(false);

  useEffect(() => {
    if (open) {
      setSelected(model);
      setApiKey("");
      setShowKey(false);
      fetch(`http://${API_HOST}/api/models`).then(r => r.json()).then(d => setModels(d.models || [])).catch(() => {});
      fetch(`http://${API_HOST}/api/status`).then(r => r.json()).then(d => {
        if (d.evolution !== undefined) setEvolution(d.evolution);
        if (d.base_url) setBaseUrl(d.base_url);
        setHasKey(d.has_api_key || false);
        for (const [name, preset] of Object.entries(PROVIDER_PRESETS)) {
          if (d.base_url && preset.base_url && d.base_url.includes(new URL(preset.base_url).hostname)) {
            setProvider(name); break;
          }
        }
      }).catch(() => {});
    }
  }, [open, model]);

  function selectProvider(name: string) {
    setProvider(name);
    const preset = PROVIDER_PRESETS[name];
    if (preset && preset.base_url) {
      setBaseUrl(preset.base_url);
      if (preset.models.length > 0) {
        setModels(prev => [...new Set([...preset.models, ...prev])].sort());
        setSelected(preset.models[0]);
      }
    }
  }

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(10,10,12,0.82)", backdropFilter: "blur(8px)" }}
        onClick={onClose}>
        <motion.div initial={{ scale: 0.97, opacity: 0, y: 12 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.97, opacity: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="w-[440px] max-h-[90vh] overflow-y-auto rounded-2xl p-6"
          style={{ background: "var(--surface-1)", border: "1px solid var(--border-1)", boxShadow: "0 24px 80px rgba(0,0,0,0.6)" }}
          onClick={e => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-5">
            <h3 className="font-semibold text-[15px]" style={{ color: "var(--text-0)" }}>设置</h3>
            <button onClick={onClose} className="transition-colors hover:text-[var(--text-1)]" style={{ color: "var(--text-3)" }}><X size={16} /></button>
          </div>

          {/* Provider */}
          <label className="block text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-3)" }}>服务商</label>
          <div className="flex flex-wrap gap-1.5 mb-4">
            {Object.keys(PROVIDER_PRESETS).map(name => (
              <button key={name} onClick={() => selectProvider(name)}
                className="px-2.5 py-1 text-[12px] rounded-lg transition-all"
                style={{
                  background: provider === name ? "var(--amber)" : "var(--surface-0)",
                  color: provider === name ? "var(--void)" : "var(--text-2)",
                  border: `1px solid ${provider === name ? "var(--amber)" : "var(--border-1)"}`,
                }}>
                {name}
              </button>
            ))}
          </div>

          {/* API Key */}
          <label className="block text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-3)" }}>
            API Key {hasKey && !apiKey && <span className="text-[10px] normal-case" style={{ color: "var(--pass)" }}>(已配置)</span>}
          </label>
          <div className="relative mb-4">
            <input type={showKey ? "text" : "password"} value={apiKey} onChange={e => setApiKey(e.target.value)}
              placeholder={hasKey ? "已配置，留空保持不变" : "sk-..."}
              className="w-full rounded-lg px-3 py-2.5 pr-10 text-sm outline-none font-mono transition-colors focus:border-[var(--amber)]"
              style={{ background: "var(--surface-0)", border: "1px solid var(--border-1)", color: "var(--text-0)" }} />
            <button onClick={() => setShowKey(!showKey)} className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-colors hover:text-[var(--text-1)]" style={{ color: "var(--text-3)" }}>
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>

          {/* Base URL */}
          <label className="block text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-3)" }}>Base URL</label>
          <input type="text" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1"
            className="w-full rounded-lg px-3 py-2.5 text-sm outline-none mb-4 font-mono transition-colors focus:border-[var(--amber)]"
            style={{ background: "var(--surface-0)", border: "1px solid var(--border-1)", color: "var(--text-0)" }} />

          {/* Model */}
          <label className="block text-[10px] font-medium uppercase tracking-wider mb-1.5" style={{ color: "var(--text-3)" }}>模型</label>
          <select value={selected} onChange={e => setSelected(e.target.value)}
            className="w-full rounded-lg px-3 py-2.5 text-sm outline-none mb-4 cursor-pointer"
            style={{ background: "var(--surface-0)", border: "1px solid var(--border-1)", color: "var(--text-0)" }}>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>

          {/* Evolution toggle */}
          <div className="flex items-center justify-between mb-5 pt-3" style={{ borderTop: "1px solid var(--border-0)" }}>
            <div>
              <label className="block text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-3)" }}>自进化</label>
              <span className="text-[12px]" style={{ color: "var(--text-3)" }}>使用过程中自动积累经验</span>
            </div>
            <button onClick={() => setEvolution(!evolution)}
              className="relative w-10 h-[22px] rounded-full transition-colors"
              style={{ background: evolution ? "var(--amber)" : "var(--surface-0)", border: "1px solid var(--border-1)" }}>
              <span className="absolute top-[2px] w-4 h-4 rounded-full transition-transform shadow-sm"
                style={{ background: evolution ? "var(--void)" : "var(--text-3)", left: evolution ? "20px" : "2px" }} />
            </button>
          </div>

          <div className="flex gap-2 justify-end">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg transition-colors hover:bg-[var(--surface-2)]"
              style={{ background: "var(--surface-0)", color: "var(--text-2)", border: "1px solid var(--border-1)" }}>取消</button>
            <button disabled={saving} onClick={async () => {
              setSaving(true);
              try {
                const body: Record<string, unknown> = { model: selected, evolution };
                if (apiKey) body.api_key = apiKey;
                if (baseUrl) body.base_url = baseUrl;
                const r = await fetch(`http://${API_HOST}/api/settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
                const d = await r.json();
                if (d.status === "ok") { onModelChange(d.model); onClose(); }
              } catch { alert("保存失败"); }
              setSaving(false);
            }} className="px-4 py-2 text-sm rounded-lg transition-opacity"
              style={{ background: "var(--amber)", color: "var(--void)", fontWeight: 600, opacity: saving ? 0.6 : 1 }}>
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </motion.div>
      </motion.div>
      )}
    </AnimatePresence>
  );
}
