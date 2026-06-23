"use client";

import { cn } from "@/lib/utils";

interface WorkbenchShellProps {
  sidebarOpen: boolean;
  debugOpen: boolean;
  sidebar: React.ReactNode;
  commandRail: React.ReactNode;
  canvas: React.ReactNode;
  debugPanel?: React.ReactNode;
}

/**
 * WorkbenchShell - CSS Grid layout container with 4 zones:
 * - Left sidebar (48px collapsed / 240px expanded)
 * - Center command-rail (flex, min 360px)
 * - Right artifact-canvas (flex, min 400px)
 * - Bottom debug-panel (collapsible, 0 or 240px)
 */
export function WorkbenchShell({
  sidebarOpen,
  debugOpen,
  sidebar,
  commandRail,
  canvas,
  debugPanel,
}: WorkbenchShellProps) {
  const sidebarWidth = sidebarOpen ? "240px" : "48px";
  const debugHeight = debugOpen ? "240px" : "0px";

  return (
    <div
      className="w-screen h-screen overflow-hidden"
      style={{
        display: "grid",
        gridTemplateColumns: `${sidebarWidth} minmax(360px, 1fr) minmax(400px, 1fr)`,
        gridTemplateRows: `1fr ${debugHeight}`,
        gridTemplateAreas: `
          "sidebar rail canvas"
          "sidebar debug debug"
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

      {/* Command Rail */}
      <main
        style={{
          gridArea: "rail",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--border-0)",
        }}
      >
        {commandRail}
      </main>

      {/* Artifact Canvas */}
      <section
        style={{
          gridArea: "canvas",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {canvas}
      </section>

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
