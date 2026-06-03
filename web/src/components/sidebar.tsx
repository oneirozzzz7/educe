"use client";

import { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import { PanelLeftClose, PanelLeft, Search, Settings } from "lucide-react";
import { LogoMark } from "./logo";
import { API_HOST } from "@/lib/ws";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface TaskItem { id: string; request?: string; title?: string; project_type?: string; created_at: number; updated_at?: number; turns?: number; response?: string }

function formatRelativeTime(ts: number, locale: string): string {
  const now = Date.now() / 1000;
  const diff = now - ts;
  if (diff < 60) return locale === "zh" ? "刚刚" : "just now";
  if (diff < 3600) return locale === "zh" ? `${Math.floor(diff / 60)}分钟前` : `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return locale === "zh" ? `${Math.floor(diff / 3600)}小时前` : `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return locale === "zh" ? `${Math.floor(diff / 86400)}天前` : `${Math.floor(diff / 86400)}d ago`;
  return new Date(ts * 1000).toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric" });
}

export interface SidebarRef { refresh: () => void }

export const Sidebar = forwardRef<SidebarRef, {
  collapsed: boolean; onCollapse: () => void; onTaskSelect?: (task: TaskItem) => void; onNewTask?: () => void;
  activeSessionId?: string; onOpenSettings?: () => void;
}>(function Sidebar({ collapsed, onCollapse, onTaskSelect, onNewTask, activeSessionId, onOpenSettings }, ref) {
  const { locale, setLocale, t } = useLocale();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const loadTasks = useCallback(() => {
    setLoading(true);
    fetch(`http://${API_HOST}/api/tasks?limit=20&offset=0`)
      .then(r => r.json())
      .then(d => { setTasks(d.tasks || []); setTotal(d.total || 0); setHasMore((d.tasks?.length || 0) < (d.total || 0)); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const loadMore = useCallback(() => {
    if (loading) return;
    setLoading(true);
    fetch(`http://${API_HOST}/api/tasks?limit=20&offset=${tasks.length}`)
      .then(r => r.json())
      .then(d => { const more = d.tasks || []; setTasks(prev => [...prev, ...more]); setHasMore(tasks.length + more.length < (d.total || 0)); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tasks.length, loading]);

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

  /* ─── Collapsed ─── */
  if (collapsed) {
    return (
      <div className="w-[48px] shrink-0 flex flex-col items-center pt-4 pb-3 gap-2" style={{ borderRight: "1px solid var(--border-0)", background: "var(--surface-0)" }}>
        <button onClick={onCollapse} className="w-8 h-8 rounded-lg flex items-center justify-center transition-all hover:bg-[var(--surface-2)]" style={{ color: "var(--text-2)" }}>
          <PanelLeft size={15} />
        </button>
        <div className="mt-1" style={{ fontFamily: "'Instrument Serif', Georgia, serif", fontSize: 22, color: "var(--amber)", lineHeight: 1 }}>E</div>
        <div className="flex-1" />
        <button onClick={onOpenSettings} className="w-7 h-7 rounded-md flex items-center justify-center transition-all hover:bg-[var(--surface-2)]" style={{ color: "var(--text-3)" }}>
          <Settings size={13} />
        </button>
      </div>
    );
  }

  /* ─── Expanded ─── */
  return (
    <div className="shrink-0 flex flex-col overflow-hidden" style={{ width: "var(--sidebar-width)", borderRight: "1px solid var(--border-0)", background: "var(--surface-0)" }}>

      {/* ─── Brand ─── */}
      <div className="flex items-center px-5 pt-5 pb-6">
        <LogoMark size={24} />
        <div className="flex-1" />
        <button onClick={onCollapse} className="w-6 h-6 rounded-md flex items-center justify-center transition-all hover:bg-[var(--surface-2)]" style={{ color: "var(--text-3)" }}>
          <PanelLeftClose size={13} />
        </button>
      </div>

      {/* ─── New Brief ─── */}
      <div className="px-3 pb-5">
        <button onClick={() => { onNewTask?.(); loadTasks(); }}
          className="sidebar-new-btn w-full py-[9px] px-3 rounded-[10px] flex items-center gap-[9px] text-[13px]"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border-1)", color: "var(--text-1)" }}>
          <span className="w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-[12px] font-semibold" style={{ background: "var(--amber-dim)", color: "var(--amber)" }}>+</span>
          {t("sidebar.new")}
        </button>
      </div>

      {/* ─── Section label ─── */}
      <div className="px-5 mb-2">
        <span className="text-[9px] font-medium uppercase tracking-[1.2px]" style={{ color: "var(--text-3)" }}>
          {t("sidebar.recent")}
        </span>
      </div>

      {/* ─── Search (if many tasks) ─── */}
      {tasks.length > 8 && (
        <div className="px-3 pb-2">
          <div className="relative">
            <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--text-3)" }} />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder={locale === "zh" ? "搜索..." : "Search..."}
              className="w-full rounded-[8px] pl-7 pr-2 py-[6px] text-[12px] outline-none transition-all focus:border-[var(--amber)]"
              style={{ background: "var(--surface-1)", border: "1px solid var(--border-0)", color: "var(--text-1)" }} />
          </div>
        </div>
      )}

      {/* ─── Task list ─── */}
      <div className="flex-1 overflow-y-auto px-2" onScroll={e => {
        const el = e.currentTarget;
        if (el.scrollHeight - el.scrollTop - el.clientHeight < 80 && hasMore && !loading) loadMore();
      }}>
        {tasks.length === 0 ? (
          <div className="px-3 py-10 text-[12px] text-center" style={{ color: "var(--text-3)" }}>
            {loading ? "..." : (locale === "zh" ? "暂无任务" : "No tasks yet")}
          </div>
        ) : (
          tasks.filter(t => {
            const text = t.title || t.request || "";
            return !search || text.toLowerCase().includes(search.toLowerCase());
          }).map(task => {
            const isActive = activeSessionId && task.id === activeSessionId;
            return (
              <button key={task.id} onClick={() => handleTaskClick(task)}
                className={cn(
                  "w-full text-left px-3 py-[9px] rounded-[7px] text-[13px] transition-all mb-[2px] flex flex-col gap-[3px]",
                  !isActive && "hover:bg-[var(--surface-1)]"
                )}
                style={{
                  color: isActive ? "var(--text-0)" : "var(--text-2)",
                  background: isActive ? "var(--amber-glow)" : "transparent",
                  borderLeft: isActive ? "2px solid var(--amber)" : "2px solid transparent",
                  paddingLeft: isActive ? "10px" : "12px",
                }}>
                <span className="truncate block leading-[1.4]">{task.title || task.request || (locale === "zh" ? "未命名" : "Untitled")}</span>
                <span className="text-[10px] flex items-center gap-1.5" style={{ color: "var(--text-3)" }}>
                  {formatRelativeTime(task.updated_at || task.created_at, locale)}
                  {(task as any).type === "code" && (
                    <span className="px-1 rounded text-[9px]" style={{ background: "var(--amber-dim)", color: "var(--amber)" }}>
                      code
                    </span>
                  )}
                  {task.turns && task.turns > 1 && (
                    <span className="px-1 rounded text-[9px]" style={{ background: "var(--surface-3)", color: "var(--text-3)" }}>
                      {task.turns}{locale === "zh" ? "轮" : "r"}
                    </span>
                  )}
                </span>
              </button>
            );
          })
        )}
        {loading && tasks.length > 0 && (
          <div className="py-3 text-center text-[11px]" style={{ color: "var(--text-3)" }}>...</div>
        )}
      </div>

      {/* ─── Bottom ─── */}
      <div className="px-3 py-3 flex items-center gap-2" style={{ borderTop: "1px solid var(--border-0)" }}>
        {/* Language toggle */}
        <div className="flex rounded-[7px] p-[2px]" style={{ background: "var(--surface-2)", border: "1px solid var(--border-0)" }}>
          <button onClick={() => setLocale("zh")}
            className={cn("px-[7px] py-[3px] rounded-[5px] text-[10px] font-semibold transition-all")}
            style={{ background: locale === "zh" ? "var(--surface-3)" : "transparent", color: locale === "zh" ? "var(--text-0)" : "var(--text-3)" }}>
            ZH
          </button>
          <button onClick={() => setLocale("en")}
            className={cn("px-[7px] py-[3px] rounded-[5px] text-[10px] font-semibold transition-all")}
            style={{ background: locale === "en" ? "var(--surface-3)" : "transparent", color: locale === "en" ? "var(--text-0)" : "var(--text-3)" }}>
            EN
          </button>
        </div>

        <div className="flex-1" />

        {/* Settings + connection */}
        <button onClick={onOpenSettings}
          className="flex items-center gap-[6px] px-2 py-[5px] rounded-[6px] transition-all hover:bg-[var(--surface-2)]"
          style={{ color: "var(--text-3)", border: "none", background: "none", cursor: "pointer", fontFamily: "inherit" }}>
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: "var(--pass)", boxShadow: "0 0 6px var(--pass-dim)" }} />
          <Settings size={12} />
        </button>
      </div>
    </div>
  );
});
