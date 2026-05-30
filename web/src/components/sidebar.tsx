"use client";

import { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import { Clock, Moon, Sun, PanelLeftClose, PanelLeft, Plus, Search } from "lucide-react";
import { useTheme } from "./theme-provider";
import { Logo, LogoMark } from "./logo";
import { API_HOST } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface TaskItem { id: string; request?: string; title?: string; project_type?: string; created_at: number; updated_at?: number; turns?: number; response?: string }

export interface SidebarRef { refresh: () => void }

export const Sidebar = forwardRef<SidebarRef, {
  collapsed: boolean; onCollapse: () => void; onTaskSelect?: (task: TaskItem) => void; onNewTask?: () => void;
}>(function Sidebar({ collapsed, onCollapse, onTaskSelect, onNewTask }, ref) {
  const { theme, toggle } = useTheme();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");

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
        onTaskSelect?.({ ...t, response: detail?.response || detail?.engineer_output || "" });
      })
      .catch(() => onTaskSelect?.(t));
  }

  if (collapsed) {
    return (
      <div className="w-12 shrink-0 flex flex-col items-center py-3 gap-3 border-r" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
        <button onClick={onCollapse} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors" style={{ color: "var(--text-2)" }}>
          <PanelLeft size={16} />
        </button>
        <LogoMark size={28} />
      </div>
    );
  }

  return (
    <div className="w-[var(--sidebar-width)] shrink-0 flex flex-col border-r overflow-hidden" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
      {/* 头部 */}
      <div className="h-12 px-4 flex items-center gap-2 border-b" style={{ borderColor: "var(--border)" }}>
        <Logo size={28} />
        <span className="text-[14px] font-bold" style={{ color: "var(--text)" }}>
          Deep<span style={{ color: "var(--brand)" }}>Forge</span>
        </span>
        <div className="flex-1" />
        <button onClick={onCollapse} className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors" style={{ color: "var(--text-3)" }}>
          <PanelLeftClose size={14} />
        </button>
      </div>

      {/* 新建按钮 */}
      <div className="px-3 py-2">
        <button onClick={() => { onNewTask?.(); loadTasks(); }}
          className="w-full h-8 rounded-lg border flex items-center justify-center gap-1.5 text-xs font-medium hover:bg-[var(--brand-subtle)] transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--text-2)" }}>
          <Plus size={13} /> 新任务
        </button>
      </div>

      {/* 最近任务 */}
      <div className="flex-1 overflow-y-auto px-2">
        <div className="px-2 py-1.5">
          <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-3)" }}>
            最近任务
          </span>
        </div>
        {tasks.length > 3 && (
          <div className="px-1 pb-1.5">
            <div className="relative">
              <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2" style={{ color: "var(--text-4)" }} />
              <input type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder="搜索..." className="w-full rounded-md pl-6 pr-2 py-1 text-[11px] outline-none"
                style={{ background: "var(--bg-sunken)", border: "1px solid var(--border)", color: "var(--text-2)" }} />
            </div>
          </div>
        )}
        {tasks.length === 0 ? (
          <div className="px-2 py-6 text-xs text-center" style={{ color: "var(--text-3)" }}>
            {loading ? "加载中..." : "暂无任务"}
          </div>
        ) : (
          tasks.filter(t => {
            const text = t.title || t.request || "";
            return !search || text.toLowerCase().includes(search.toLowerCase());
          }).slice(0, 20).map(t => (
            <button key={t.id} onClick={() => handleTaskClick(t)}
              className="w-full text-left px-2.5 py-2 rounded-lg text-[12px] truncate hover:bg-[var(--brand-subtle)] transition-colors mb-0.5 group"
              style={{ color: "var(--text-2)" }}>
              <span className="truncate block">{t.title || t.request || "未命名对话"}</span>
              <span className="text-[10px] block mt-0.5 flex items-center gap-1" style={{ color: "var(--text-4)" }}>
                {new Date((t.updated_at || t.created_at) * 1000).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                {t.turns && t.turns > 1 && <span className="ml-1 px-1 rounded" style={{ background: "var(--brand-subtle)" }}>{t.turns}轮</span>}
              </span>
            </button>
          ))
        )}
      </div>

      {/* 底部 */}
      <div className="px-3 py-2 border-t flex items-center gap-1" style={{ borderColor: "var(--border)" }}>
        <button onClick={toggle} className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors" style={{ color: "var(--text-3)" }}
          title={theme === "light" ? "切换暗色" : "切换亮色"}>
          {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
        </button>
        <div className="flex-1" />
        <span className="text-[10px]" style={{ color: "var(--text-4)" }}>v1.5</span>
      </div>
    </div>
  );
});
