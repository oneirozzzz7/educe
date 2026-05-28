"use client";

import { useState, useEffect } from "react";
import { Clock, Moon, Sun, PanelLeftClose, PanelLeft, Plus } from "lucide-react";
import { useTheme } from "./theme-provider";
import { Logo, LogoMark } from "./logo";
import { API_HOST } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface TaskItem { id: string; request: string; project_type: string; created_at: number }

export function Sidebar({ collapsed, onCollapse, onTaskSelect, onNewTask }: {
  collapsed: boolean; onCollapse: () => void; onTaskSelect?: (task: TaskItem) => void; onNewTask?: () => void;
}) {
  const { theme, toggle } = useTheme();
  const [tasks, setTasks] = useState<TaskItem[]>([]);

  useEffect(() => {
    fetch(`http://${API_HOST}/api/tasks`).then(r => r.json()).then(d => setTasks(d.tasks || [])).catch(() => {});
  }, []);

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
        <button onClick={onNewTask} className="w-full h-8 rounded-lg border flex items-center justify-center gap-1.5 text-xs font-medium hover:bg-[var(--brand-subtle)] transition-colors" style={{ borderColor: "var(--border)", color: "var(--text-2)" }}>
          <Plus size={13} /> 新任务
        </button>
      </div>

      {/* 最近任务 */}
      <div className="flex-1 overflow-y-auto px-2">
        <div className="px-2 py-1.5 text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-3)" }}>
          最近任务
        </div>
        {tasks.length === 0 ? (
          <div className="px-2 py-4 text-xs text-center" style={{ color: "var(--text-3)" }}>暂无任务</div>
        ) : (
          tasks.slice(0, 10).map(t => (
            <button key={t.id} onClick={() => onTaskSelect?.(t)}
              className="w-full text-left px-2.5 py-2 rounded-lg text-[12px] truncate hover:bg-[var(--brand-subtle)] transition-colors mb-0.5" style={{ color: "var(--text-2)" }}>
              {t.request || "未命名任务"}
            </button>
          ))
        )}
      </div>

      {/* 底部 */}
      <div className="px-3 py-2 border-t flex items-center gap-1" style={{ borderColor: "var(--border)" }}>
        <button onClick={toggle} className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors" style={{ color: "var(--text-3)" }}>
          {theme === "light" ? <Moon size={14} /> : <Sun size={14} />}
        </button>
        <div className="flex-1" />
        <span className="text-[10px]" style={{ color: "var(--text-4)" }}>v1.1</span>
      </div>
    </div>
  );
}
