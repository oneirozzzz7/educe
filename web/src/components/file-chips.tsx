"use client";

import { X, FileText, FileCode, Image, Table, File } from "lucide-react";

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  is_image: boolean;
  error?: string;
}

function getIcon(name: string, isImage: boolean) {
  if (isImage) return <Image size={13} />;
  const ext = name.split(".").pop()?.toLowerCase() || "";
  if (["py", "js", "ts", "tsx", "jsx", "html", "css", "json", "go", "java", "c", "cpp", "rs", "rb"].includes(ext)) return <FileCode size={13} />;
  if (["xlsx", "xls", "csv"].includes(ext)) return <Table size={13} />;
  if (["pdf", "docx", "txt", "md"].includes(ext)) return <FileText size={13} />;
  return <File size={13} />;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export function FileChips({ files, onRemove }: {
  files: UploadedFile[];
  onRemove: (id: string) => void;
}) {
  if (files.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 px-1 pb-2">
      {files.map(f => (
        <div key={f.id} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[12px] max-w-[200px]"
          style={{
            background: f.error ? "var(--error-light)" : "var(--brand-light)",
            color: f.error ? "var(--error)" : "var(--brand)",
            border: `1px solid ${f.error ? "var(--error)" : "transparent"}`,
          }}>
          {getIcon(f.name, f.is_image)}
          <span className="truncate flex-1">{f.name}</span>
          <span className="text-[10px] opacity-60 shrink-0">{fmtSize(f.size)}</span>
          <button onClick={() => onRemove(f.id)} className="shrink-0 ml-0.5 opacity-50 hover:opacity-100 transition-opacity">
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
