"use client";

import { cn } from "@/lib/utils";

interface WorkbenchShellProps {
  sidebarOpen: boolean;
  debugOpen: boolean;
  sidebar: React.ReactNode;
  commandRail: React.ReactNode;
  debugPanel?: React.ReactNode;
}

/**
 * WorkbenchShell - Layout: sidebar left + main center + debug right drawer
 */
export function WorkbenchShell({
  sidebarOpen,
  debugOpen,
  sidebar,
  commandRail,
  debugPanel,
}: WorkbenchShellProps) {
  const sidebarWidth = sidebarOpen ? "240px" : "48px";

  return (
    <div
      className="w-screen h-screen overflow-hidden flex"
      style={{ background: "var(--bg)" }}
    >
      {/* Sidebar */}
      <aside
        style={{
          width: sidebarWidth,
          background: "var(--surface-1)",
          borderRight: "1px solid var(--border-0)",
          overflow: "hidden",
          transition: "width 0.2s ease",
          flexShrink: 0,
        }}
      >
        {sidebar}
      </aside>

      {/* Main Content */}
      <main
        style={{
          flex: 1,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
        }}
      >
        {commandRail}
      </main>

      {/* Debug Panel — right side drawer */}
      {debugOpen && debugPanel && (
        <section
          style={{
            width: 360,
            background: "var(--surface-1)",
            borderLeft: "1px solid var(--border-0)",
            overflow: "hidden",
            flexShrink: 0,
            animation: "slide-in-right 0.2s ease",
          }}
        >
          {debugPanel}
        </section>
      )}
    </div>
  );
}
