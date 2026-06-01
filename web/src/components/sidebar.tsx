"use client";

import { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import { PanelLeftClose, PanelLeft, Plus, Search } from "lucide-react";
import { LogoMark } from "./logo";
import { API_HOST } from "@/lib/ws";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface TaskItem { id: string; request?: string; title?: string; project_type?: string; created_at: number; updated_at?: number; turns?: number; response?: string }

export interface SidebarRef { refresh: () => void }

export const Sidebar = forwardRef<SidebarRef, {
  collapsed: boolean; onCollapse: () => void; onTaskSelect?: (task: TaskItem) => void; onNewTask?: () => void;
  activeSessionId?: string;
}>(function Sidebar({ collapsed, onCollapse, onTaskSelect, onNewTask, activeSessionId }, ref) {
  const { locale, setLocale, t } = useLocale();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [showCount, setShowCount] = useState(20);

  const loadTasks = useCallback(() => {
    setLoading(true);
    fetch(`http://${API_HOST}/api/tasks`)
      .then(r => r.json())
      .then(d => setTasks(d.tasks || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useImperativeHandle(ref, () => ({ refresh: loadTasks }));

  useEffect(() => { loadTasks(); }, [loadTasks]);

  function handleTaskClick(t: TaskItem) {
    fetch(`http://${API_HOST}/api/tasks/${t.id}`)
      .then(r => r.json())
      .then(detail => {
        if (detail?.turns && Array.isArray(detail.turns)) {
          onTaskSelect?.({ ...t, turns: detail.turns } as any);
        } else {
          onTaskSelect?.({ ...t, response: detail?.response || detail?.engineer_output || "" });
        }
      })
      .catch(() => onTaskSelect?.(t));
  }

  if (collapsed) {
    return (
      <div className="w-12 shrink-0 flex flex-col items-center py-3 gap-3" style={{ borderRight: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
        <button onClick={onCollapse} className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-[var(--amber-glow)]" style={{ color: "var(--text-2)" }}>
          <PanelLeft size={16} />
        </button>
        <span style={{ fontFamily: "'Instrument Serif', Georgia, serif", fontSize: 20, color: "var(--amber)" }}>E</span>
      </div>
    );
  }

  return (
    <div className="shrink-0 flex flex-col overflow-hidden" style={{ width: "var(--sidebar-width)", borderRight: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
      {/* Brand */}
      <div className="px-5 pt-5 pb-5 flex items-baseline">
        <LogoMark size={24} />
        <span className="ml-2.5 text-[9px] font-medium uppercase tracking-[0.1em]" style={{ color: "var(--text-3)" }}>
          {t("tagline")}
        </span>
        <div className="flex-1" />
        <button onClick={onCollapse} className="w-6 h-6 rounded-md flex items-center justify-center transition-colors hover:bg-[var(--amber-glow)]" style={{ color: "var(--text-3)" }}>
          <PanelLeftClose size={13} />
        </button>
      </div>

      {/* New brief button */}
      <div className="px-3 pb-4">
        <button onClick={() => { onNewTask?.(); loadTasks(); }}
          className="w-full py-2 px-3 rounded-[10px] flex items-center gap-2 text-[13px] transition-all hover:border-[var(--amber)] hover:text-[var(--text-0)]"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border-1)", color: "var(--text-1)" }}>
          <span className="w-[17px] h-[17px] rounded-[5px] flex items-center justify-center text-[12px] font-semibold" style={{ background: "var(--amber-dim)", color: "var(--amber)" }}>+</span>
          {t("sidebar.new")}
        </button>
      </div>

      {/* Section label */}
      <div className="px-5 mb-1.5">
        <span className="text-[9px] font-medium uppercase tracking-[1px]" style={{ color: "var(--text-3)" }}>
          {t("sidebar.recent")}
        </span>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto px-1.5">
        {tasks.length > 3 && (
          <div className="px-1 pb-1.5">
            <div className="relative">
              <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--text-3)" }} />
              <input type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder={locale === "zh" ? "搜索..." : "Search..."}
                className="w-full rounded-md pl-7 pr-2 py-1.5 text-[12px] outline-none transition-colors focus:border-[var(--amber)]"
                style={{ background: "var(--surface-1)", border: "1px solid var(--border-1)", color: "var(--text-1)" }} />
            </div>
          </div>
        )}
        {tasks.length === 0 ? (
          <div className="px-3 py-8 text-xs text-center" style={{ color: "var(--text-3)" }}>
            {loading ? "..." : (locale === "zh" ? "暂无任务" : "No tasks yet")}
          </div>
        ) : (
          tasks.filter(t => {
            const text = t.title || t.request || "";
            return !search || text.toLowerCase().includes(search.toLowerCase());
          }).slice(0, showCount).map(t => {
            const isActive = activeSessionId && t.id === activeSessionId;
            return (
            <button key={t.id} onClick={() => handleTaskClick(t)}
              className={cn("w-full text-left px-3 py-2 rounded-[6px] text-[13px] truncate transition-all mb-[1px] flex flex-col gap-[3px]",
                isActive ? "" : "hover:bg-[var(--surface-1)] hover:text-[var(--text-1)]")}
              style={{
                color: isActive ? "var(--text-0)" : "var(--text-2)",
                background: isActive ? "var(--amber-glow)" : "transparent",
                borderLeft: isActive ? "2px solid var(--amber)" : "2px solid transparent",
                paddingLeft: isActive ? "10px" : "12px",
              }}>
              <span className="truncate block">{t.title || t.request || (locale === "zh" ? "未命名" : "Untitled")}</span>
              <span className="text-[10px] flex items-center gap-1" style={{ color: "var(--text-3)" }}>
                {new Date((t.updated_at || t.created_at) * 1000).toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                {t.turns && t.turns > 1 && <span className="ml-1 px-1 rounded text-[9px]" style={{ background: "var(--amber-dim)", color: "var(--amber)" }}>{t.turns}{locale === "zh" ? "轮" : "r"}</span>}
              </span>
            </button>
          );})
        )}
        {tasks.length > showCount && (
          <button onClick={() => setShowCount(prev => prev + 20)}
            className="w-full py-2 text-[11px] text-center transition-colors rounded-lg hover:bg-[var(--surface-1)]"
            style={{ color: "var(--text-3)" }}>
            {locale === "zh" ? "加载更多" : "Load more"}
          </button>
        )}
      </div>

      {/* Bottom */}
      <div className="px-3 py-2.5 flex items-center gap-2" style={{ borderTop: "1px solid var(--border-0)" }}>
        {/* Language toggle */}
        <div className="flex rounded-[6px] p-[2px] gap-[1px]" style={{ background: "var(--surface-2)" }}>
          <button onClick={() => setLocale("zh")}
            className={cn("px-2 py-1 rounded-[5px] text-[10px] font-semibold transition-all", locale === "zh" ? "text-[var(--text-0)]" : "text-[var(--text-3)]")}
            style={{ background: locale === "zh" ? "var(--surface-3)" : "transparent" }}>
            ZH
          </button>
          <button onClick={() => setLocale("en")}
            className={cn("px-2 py-1 rounded-[5px] text-[10px] font-semibold transition-all", locale === "en" ? "text-[var(--text-0)]" : "text-[var(--text-3)]")}
            style={{ background: locale === "en" ? "var(--surface-3)" : "transparent" }}>
            EN
          </button>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-[11px] px-2" style={{ color: "var(--text-3)" }}>
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: "var(--pass)", boxShadow: "0 0 6px var(--pass-dim)" }}></span>
          <span style={{ fontFamily: "var(--font-mono, monospace)" }}>v1.5</span>
        </div>
      </div>
    </div>
  );
});
