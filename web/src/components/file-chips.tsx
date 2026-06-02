"use client";

import { X, FileText, FileCode, Image as ImageIcon, Table, File, AlertCircle } from "lucide-react";
import { useState } from "react";

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  is_image: boolean;
  error?: string;
  preview_url?: string;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function getFileCategory(name: string, isImage: boolean): "image" | "code" | "document" | "data" | "unknown" {
  if (isImage) return "image";
  const ext = name.split(".").pop()?.toLowerCase() || "";
  if (["py", "js", "ts", "tsx", "jsx", "html", "css", "json", "go", "java", "c", "cpp", "rs", "rb", "sh", "sql", "swift"].includes(ext)) return "code";
  if (["pdf", "docx", "doc", "txt", "md", "rtf"].includes(ext)) return "document";
  if (["xlsx", "xls", "csv", "yaml", "yml", "xml"].includes(ext)) return "data";
  return "unknown";
}

function getIcon(category: string) {
  switch (category) {
    case "code": return <FileCode size={14} />;
    case "document": return <FileText size={14} />;
    case "data": return <Table size={14} />;
    case "image": return <ImageIcon size={14} />;
    default: return <File size={14} />;
  }
}

export function FileChips({ files, onRemove, supportsVision = true }: {
  files: UploadedFile[];
  onRemove: (id: string) => void;
  supportsVision?: boolean;
}) {
  if (files.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 px-1 pb-2">
      {files.map(f => {
        const category = getFileCategory(f.name, f.is_image);
        const showWarning = category === "image" && !supportsVision;

        if (f.error) {
          return (
            <div key={f.id} className="flex items-center gap-2 px-3 py-2 rounded-[10px] text-[12px]"
              style={{ background: "var(--fail-dim)", color: "var(--fail)", border: "1px solid rgba(212,100,92,0.3)" }}>
              <AlertCircle size={13} />
              <span className="truncate max-w-[140px]">{f.name}</span>
              <span className="text-[10px] opacity-60">{f.error}</span>
              <button onClick={() => onRemove(f.id)} className="shrink-0 opacity-50 hover:opacity-100 transition-opacity">
                <X size={12} />
              </button>
            </div>
          );
        }

        // Image with thumbnail preview
        if (category === "image" && f.preview_url) {
          return (
            <div key={f.id} className="relative group/chip">
              <div className="w-[48px] h-[48px] rounded-[10px] overflow-hidden" style={{ border: "1px solid var(--border-1)" }}>
                <img src={f.preview_url} alt={f.name} className="w-full h-full object-cover" />
              </div>
              {showWarning && (
                <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: "var(--fail)", color: "#fff", fontSize: 9 }}>!</div>
              )}
              <button onClick={() => onRemove(f.id)}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover/chip:opacity-100 transition-opacity"
                style={{ background: "var(--surface-3)", color: "var(--text-2)", border: "1px solid var(--border-1)" }}>
                <X size={9} />
              </button>
            </div>
          );
        }

        // Image without preview (fallback)
        if (category === "image") {
          return (
            <div key={f.id} className="relative group/chip">
              <div className="w-[48px] h-[48px] rounded-[10px] flex items-center justify-center" style={{ background: "var(--surface-2)", border: "1px solid var(--border-1)", color: "var(--amber)" }}>
                <ImageIcon size={18} />
              </div>
              {showWarning && (
                <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: "var(--fail)", color: "#fff", fontSize: 9 }}>!</div>
              )}
              <button onClick={() => onRemove(f.id)}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover/chip:opacity-100 transition-opacity"
                style={{ background: "var(--surface-3)", color: "var(--text-2)", border: "1px solid var(--border-1)" }}>
                <X size={9} />
              </button>
            </div>
          );
        }

        // Document / Code / Data / Unknown — standard chip
        return (
          <div key={f.id} className="flex items-center gap-2 px-3 py-2 rounded-[10px] text-[12px] max-w-[220px] group/chip"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border-1)", color: "var(--text-1)" }}>
            <span style={{ color: category === "code" ? "var(--sage)" : category === "document" ? "var(--amber)" : "var(--text-2)" }}>
              {getIcon(category)}
            </span>
            <span className="truncate flex-1" style={{ color: "var(--text-0)" }}>{f.name}</span>
            <span className="text-[10px] shrink-0" style={{ color: "var(--text-3)" }}>{fmtSize(f.size)}</span>
            <button onClick={() => onRemove(f.id)} className="shrink-0 ml-0.5 opacity-40 hover:opacity-100 transition-opacity" style={{ color: "var(--text-2)" }}>
              <X size={12} />
            </button>
          </div>
        );
      })}

      {/* Warning for image files when model doesn't support vision */}
      {files.some(f => f.is_image) && !supportsVision && (
        <div className="w-full text-[11px] px-1 mt-1 flex items-center gap-1.5" style={{ color: "var(--fail)" }}>
          <AlertCircle size={11} />
          当前模型不支持图片理解，图片将被忽略
        </div>
      )}
    </div>
  );
}
