"use client";

import { useState, useEffect, useCallback } from "react";
import { Clock, Moon, Sun, PanelLeftClose, PanelLeft, Plus, RefreshCw } from "lucide-react";
import { useTheme } from "./theme-provider";
import { Logo, LogoMark } from "./logo";
import { API_HOST } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface TaskItem { id: string; request: string; project_type: string; created_at: number; response?: string }

export function Sidebar({ collapsed, onCollapse, onTaskSelect, onNewTask }: {
  collapsed: boolean; onCollapse: () => void; onTaskSelect?: (task: TaskItem) => void; onNewTask?: () => void;
}) {
  const { theme, toggle } = useTheme();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadTasks = useCallback(() => {
    setLoading(true);
    fetch(`http://${API_HOST}/api/tasks`)
      .then(r => r.json())
      .then(d => setTasks(d.tasks || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

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
        <div className="px-2 py-1.5 flex items-center">
          <span className="text-[10px] font-medium uppercase tracking-wider flex-1" style={{ color: "var(--text-3)" }}>
            最近任务
          </span>
          <button onClick={loadTasks} className={cn("w-5 h-5 rounded flex items-center justify-center transition-colors", loading && "animate-spin")}
            style={{ color: "var(--text-4)" }} title="刷新">
            <RefreshCw size={10} />
          </button>
        </div>
        {tasks.length === 0 ? (
          <div className="px-2 py-6 text-xs text-center" style={{ color: "var(--text-3)" }}>
            {loading ? "加载中..." : "暂无任务"}
          </div>
        ) : (
          tasks.slice(0, 20).map(t => (
            <button key={t.id} onClick={() => handleTaskClick(t)}
              className="w-full text-left px-2.5 py-2 rounded-lg text-[12px] truncate hover:bg-[var(--brand-subtle)] transition-colors mb-0.5 group"
              style={{ color: "var(--text-2)" }}>
              <span className="truncate block">{t.request || "未命名任务"}</span>
              <span className="text-[10px] block mt-0.5" style={{ color: "var(--text-4)" }}>
                {new Date(t.created_at * 1000).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
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
}
