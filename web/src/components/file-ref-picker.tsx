"use client";

import { useState, useEffect, useRef } from "react";
import { API_HOST } from "@/lib/ws";

interface FileRefPickerProps {
  onSelect: (path: string) => void;
  onClose: () => void;
  query: string;
}

interface DirEntry {
  name: string;
  is_dir: boolean;
  path: string;
}

export function FileRefPicker({ onSelect, onClose, query }: FileRefPickerProps) {
  const [files, setFiles] = useState<string[]>([]);
  const [dirEntries, setDirEntries] = useState<DirEntry[]>([]);
  const [pathValid, setPathValid] = useState<boolean | null>(null);
  const [isFile, setIsFile] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const isAbsolute = query.startsWith("/") || query.startsWith("~");

  useEffect(() => {
    if (isAbsolute) {
      // Call /api/ls to get directory listing
      const dirPath = query.endsWith("/") ? query : query.substring(0, query.lastIndexOf("/") + 1) || "/";
      const prefix = query.endsWith("/") ? "" : query.substring(query.lastIndexOf("/") + 1);

      fetch(`http://${API_HOST}/api/ls?path=${encodeURIComponent(dirPath)}`)
        .then(r => r.json())
        .then(d => {
          if (d.is_file) {
            // It's a valid file path
            setPathValid(true);
            setIsFile(true);
            setDirEntries([]);
            setFiles([query]);
          } else if (d.exists && d.entries) {
            setPathValid(true);
            setIsFile(false);
            // Filter by prefix
            let entries: DirEntry[] = d.entries;
            if (prefix) {
              entries = entries.filter((e: DirEntry) => e.name.toLowerCase().startsWith(prefix.toLowerCase()));
            }
            setDirEntries(entries.slice(0, 20));
            setFiles(entries.slice(0, 20).map((e: DirEntry) => e.path + (e.is_dir ? "/" : "")));
          } else {
            setPathValid(false);
            setDirEntries([]);
            setFiles([]);
          }
          setSelectedIdx(0);
        })
        .catch(() => { setPathValid(false); setDirEntries([]); setFiles([]); });
      return;
    }
    // Project file search
    fetch(`http://${API_HOST}/api/files?q=${encodeURIComponent(query)}&limit=10`)
      .then(r => r.json())
      .then(d => { setFiles(d.files || []); setDirEntries([]); setSelectedIdx(0); })
      .catch(() => setFiles([]));
  }, [query, isAbsolute]);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.isComposing) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, files.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" && files[selectedIdx]) { e.preventDefault(); onSelect(files[selectedIdx]); }
      else if (e.key === "Tab" && files[selectedIdx]) { e.preventDefault(); onSelect(files[selectedIdx]); }
      else if (e.key === "Escape") { onClose(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [files, selectedIdx, onSelect, onClose]);

  if (files.length === 0 && !isAbsolute) return null;

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.3)",
          zIndex: 9998,
        }}
      />
      <div
        ref={ref}
        style={{
          position: "fixed",
          bottom: 80,
          left: "50%",
          transform: "translateX(-50%)",
          width: "min(560px, 85vw)",
          maxHeight: 280,
          overflow: "auto",
          borderRadius: 10,
          background: "var(--surface-1)",
          border: "1px solid var(--border-1)",
          boxShadow: "0 -4px 20px rgba(0,0,0,0.4)",
          zIndex: 9999,
        }}
      >
        {/* Header */}
        {isAbsolute && (
          <div style={{ padding: "6px 12px", fontSize: 10, borderBottom: "1px solid var(--border-0)", display: "flex", alignItems: "center", gap: 6 }}>
            <span className="w-[6px] h-[6px] rounded-full" style={{ background: pathValid === false ? "var(--fail)" : pathValid === true ? "var(--pass)" : "var(--text-3)" }} />
            <span style={{ color: pathValid === false ? "var(--fail)" : "var(--text-3)" }}>
              {pathValid === false ? "Path not found" : isFile ? "File found — Enter to attach" : "Select a file"}
            </span>
          </div>
        )}

        {/* Entries */}
        {isAbsolute && dirEntries.length > 0 && dirEntries.map((entry, i) => (
          <div
            key={entry.path}
            className="px-3 py-1.5 cursor-pointer truncate flex items-center gap-2"
            style={{
              background: i === selectedIdx ? "var(--surface-2)" : "transparent",
              fontSize: 12,
            }}
            onClick={() => onSelect(entry.path + (entry.is_dir ? "/" : ""))}
            onMouseEnter={() => setSelectedIdx(i)}
          >
            <span style={{ color: entry.is_dir ? "var(--accent)" : "var(--text-2)", fontSize: 11 }}>
              {entry.is_dir ? "📁" : "📄"}
            </span>
            <span style={{ color: entry.is_dir ? "var(--accent)" : "var(--text-1)" }}>
              {entry.name}{entry.is_dir ? "/" : ""}
            </span>
          </div>
        ))}

        {/* File found — show as single option */}
        {isAbsolute && isFile && (
          <div
            className="px-3 py-1.5 cursor-pointer flex items-center gap-2"
            style={{ background: "var(--surface-2)", fontSize: 12 }}
            onClick={() => onSelect(query)}
          >
            <span style={{ color: "var(--pass)" }}>📄</span>
            <span style={{ color: "var(--pass)" }}>{query}</span>
          </div>
        )}

        {/* Empty state for absolute */}
        {isAbsolute && !isFile && dirEntries.length === 0 && pathValid !== false && (
          <div className="px-3 py-2" style={{ fontSize: 11, color: "var(--text-3)" }}>
            Type more to narrow results...
          </div>
        )}

        {/* Project file results (non-absolute) */}
        {!isAbsolute && files.map((f, i) => (
          <div
            key={f}
            className="px-3 py-1.5 text-[12px] cursor-pointer truncate"
            style={{
              background: i === selectedIdx ? "var(--surface-2)" : "transparent",
              color: "var(--text-1)",
            }}
            onClick={() => onSelect(f)}
            onMouseEnter={() => setSelectedIdx(i)}
          >
            <span style={{ color: "var(--text-3)", fontSize: 11 }}>@</span> {f}
          </div>
        ))}
      </div>
    </>
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
          style={{ background: "var(--surface-2)", color: "var(--text-2)", border: "1px solid var(--border-0)" }}
        >
          📎 {f.startsWith("/") ? f.split("/").slice(-2).join("/") : f.split("/").pop()}
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
