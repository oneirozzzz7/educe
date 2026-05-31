"use client";

import { Settings, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "./theme-provider";

export function TopBar({ model, connected, onOpenSettings }: {
  model: string; connected: boolean; onOpenSettings: () => void;
}) {
  const { theme, toggle } = useTheme();
  return (
    <header className="h-11 px-4 flex items-center border-b shrink-0" style={{ borderColor: "var(--border)", background: "var(--bg-elevated)" }}>
      <div className="flex-1" />
      <div className="flex items-center gap-2">
        <div className={cn("flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border")}
          style={{ borderColor: "var(--border)", color: "var(--text-2)", background: "var(--bg-sunken)" }}>
          <span className={cn("w-1.5 h-1.5 rounded-full", connected ? "bg-emerald-500" : "bg-red-500")} />
          {model || "..."}
        </div>
        <button onClick={toggle}
          className="w-7 h-7 rounded-lg border flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--text-3)" }}
          title={theme === "light" ? "切换暗色" : "切换亮色"}>
          {theme === "light" ? <Moon size={13} /> : <Sun size={13} />}
        </button>
        <button onClick={onOpenSettings}
          className="w-7 h-7 rounded-lg border flex items-center justify-center hover:bg-[var(--brand-subtle)] transition-colors"
          style={{ borderColor: "var(--border)", color: "var(--text-3)" }}>
          <Settings size={13} />
        </button>
      </div>
    </header>
  );
}
