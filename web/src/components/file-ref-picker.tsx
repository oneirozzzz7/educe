"use client";

import { useState, useEffect, useRef } from "react";
import { API_HOST } from "@/lib/ws";

interface FileRefPickerProps {
  onSelect: (path: string) => void;
  onClose: () => void;
  query: string;
}

export function FileRefPicker({ onSelect, onClose, query }: FileRefPickerProps) {
  const [files, setFiles] = useState<string[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`http://${API_HOST}/api/files?q=${encodeURIComponent(query)}&limit=10`)
      .then(r => r.json())
      .then(d => { setFiles(d.files || []); setSelectedIdx(0); })
      .catch(() => setFiles([]));
  }, [query]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, files.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" && files[selectedIdx]) { e.preventDefault(); onSelect(files[selectedIdx]); }
      else if (e.key === "Escape") { onClose(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [files, selectedIdx, onSelect, onClose]);

  if (files.length === 0) return null;

  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 mb-1 w-full max-h-[200px] overflow-auto rounded-xl"
      style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", boxShadow: "var(--shadow)", zIndex: 100 }}
    >
      {files.map((f, i) => (
        <div
          key={f}
          className="px-3 py-1.5 text-[12px] cursor-pointer truncate"
          style={{
            background: i === selectedIdx ? "var(--bg-code)" : "transparent",
            color: "var(--text)",
          }}
          onClick={() => onSelect(f)}
          onMouseEnter={() => setSelectedIdx(i)}
        >
          <span style={{ color: "var(--text-3)" }}>@</span> {f}
        </div>
      ))}
    </div>
  );
}

export function ReferencedFilesBar({ files, onRemove }: { files: string[]; onRemove: (f: string) => void }) {
  if (files.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 px-1 py-1 mb-1 flex-wrap">
      {files.map(f => (
        <span
          key={f}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px]"
          style={{ background: "var(--bg-code)", color: "var(--text-2)", border: "1px solid var(--border-light)" }}
        >
          📎 {f.split("/").pop()}
          <button
            onClick={() => onRemove(f)}
            className="ml-0.5 hover:opacity-60"
            style={{ color: "var(--text-3)", fontSize: 10 }}
          >×</button>
        </span>
      ))}
    </div>
  );
}
