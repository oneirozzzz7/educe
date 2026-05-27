"use client";

interface Props {
  model: string;
  connected: boolean;
  onNew: () => void;
}

export function TopBar({ model, connected, onNew }: Props) {
  return (
    <header className="h-11 px-4 flex items-center gap-3 border-b border-border shrink-0 bg-surface">
      <span className="text-sm font-bold tracking-tight text-neutral-400">
        DEEP<span className="text-accent">FORGE</span>
      </span>
      <div className="w-px h-4 bg-border-bright" />
      <button
        onClick={onNew}
        className="px-2.5 py-1 text-[10px] font-semibold border border-border-bright text-neutral-400 rounded hover:border-accent hover:text-accent transition-colors"
      >
        + New
      </button>
      <div className="flex-1" />
      <span
        className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-green-500 shadow-[0_0_6px_theme(colors.green.500)]" : "bg-red-500 shadow-[0_0_6px_theme(colors.red.500)]"}`}
      />
      <span className="text-[10px] font-mono text-neutral-500">{model}</span>
      <button
        onClick={() => {
          const el = document.getElementById("settings-modal");
          el?.classList.toggle("hidden");
        }}
        className="w-6 h-6 rounded border border-border text-neutral-500 flex items-center justify-center text-xs hover:border-accent hover:text-accent transition-colors"
      >
        ⚙
      </button>
    </header>
  );
}
