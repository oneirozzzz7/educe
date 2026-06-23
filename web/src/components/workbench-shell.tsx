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
 * WorkbenchShell - CSS Grid layout container with 2 zones + optional debug:
 * - Left sidebar (48px collapsed / 240px expanded)
 * - Center content (flex, full remaining width)
 * - Bottom debug-panel (collapsible, 0 or 240px)
 */
export function WorkbenchShell({
  sidebarOpen,
  debugOpen,
  sidebar,
  commandRail,
  debugPanel,
}: WorkbenchShellProps) {
  const sidebarWidth = sidebarOpen ? "240px" : "48px";
  const debugHeight = debugOpen ? "240px" : "0px";

  return (
    <div
      className="w-screen h-screen overflow-hidden"
      style={{
        display: "grid",
        gridTemplateColumns: `${sidebarWidth} 1fr`,
        gridTemplateRows: `1fr ${debugHeight}`,
        gridTemplateAreas: `
          "sidebar main"
          "sidebar debug"
        `,
        background: "var(--bg)",
        transition: "grid-template-columns 0.2s ease, grid-template-rows 0.2s ease",
      }}
    >
      {/* Sidebar */}
      <aside
        style={{
          gridArea: "sidebar",
          background: "var(--surface-1)",
          borderRight: "1px solid var(--border-0)",
          overflow: "hidden",
          transition: "width 0.2s ease",
        }}
      >
        {sidebar}
      </aside>

      {/* Main Content */}
      <main
        style={{
          gridArea: "main",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {commandRail}
      </main>

      {/* Debug Panel (collapsible) */}
      {debugOpen && debugPanel && (
        <section
          style={{
            gridArea: "debug",
            background: "var(--surface-1)",
            borderTop: "1px solid var(--border-0)",
            overflow: "hidden",
          }}
        >
          {debugPanel}
        </section>
      )}
    </div>
  );
}
