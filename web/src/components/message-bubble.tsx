"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Copy, Check } from "lucide-react";

export function MessageBubble({ text, timestamp, fmtTime }: {
  text: string; timestamp: number; fmtTime: (ts: number) => string;
}) {
  const [copied, setCopied] = useState(false);
  const isLong = text.length > 300;

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex flex-col gap-1 group relative">
      <div className={`relative rounded-2xl px-4 py-3 ${isLong ? "max-h-[500px] overflow-y-auto" : ""}`}
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-light)" }}>
        <div className="prose-df text-[14px] leading-relaxed" style={{ color: "var(--text-2)" }}>
          <ReactMarkdown
            components={{
              h1: ({ children }) => <h1 className="text-lg font-semibold mt-3 mb-2 first:mt-0" style={{ color: "var(--text)" }}>{children}</h1>,
              h2: ({ children }) => <h2 className="text-base font-semibold mt-3 mb-1.5 first:mt-0" style={{ color: "var(--text)" }}>{children}</h2>,
              h3: ({ children }) => <h3 className="text-sm font-semibold mt-2.5 mb-1 first:mt-0" style={{ color: "var(--text)" }}>{children}</h3>,
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="mb-2 pl-4 list-disc space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="mb-2 pl-4 list-decimal space-y-0.5">{children}</ol>,
              li: ({ children }) => <li className="text-[14px]">{children}</li>,
              strong: ({ children }) => <strong className="font-semibold" style={{ color: "var(--text)" }}>{children}</strong>,
              em: ({ children }) => <em className="italic">{children}</em>,
              blockquote: ({ children }) => (
                <blockquote className="pl-3 my-2 italic" style={{ borderLeft: "3px solid var(--brand)", color: "var(--text-3)" }}>{children}</blockquote>
              ),
              hr: () => <hr className="my-3" style={{ borderColor: "var(--border-light)" }} />,
              code: ({ className, children }) => {
                const isBlock = className?.includes("language-");
                if (isBlock) {
                  return (
                    <pre className="rounded-lg px-3 py-2.5 my-2 overflow-x-auto text-[12px] font-mono"
                      style={{ background: "var(--bg-sunken)", color: "var(--text-2)" }}>
                      <code>{children}</code>
                    </pre>
                  );
                }
                return (
                  <code className="px-1 py-0.5 rounded text-[13px] font-mono"
                    style={{ background: "var(--bg-sunken)", color: "var(--brand)" }}>
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => <>{children}</>,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener" className="underline" style={{ color: "var(--brand)" }}>{children}</a>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto my-2">
                  <table className="w-full text-[13px] border-collapse" style={{ borderColor: "var(--border)" }}>{children}</table>
                </div>
              ),
              th: ({ children }) => (
                <th className="px-2 py-1.5 text-left font-medium text-[12px]" style={{ borderBottom: "1px solid var(--border)", color: "var(--text)" }}>{children}</th>
              ),
              td: ({ children }) => (
                <td className="px-2 py-1.5 text-[13px]" style={{ borderBottom: "1px solid var(--border-light)" }}>{children}</td>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
        {/* 复制按钮 */}
        <button onClick={handleCopy}
          className="absolute top-2.5 right-2.5 w-7 h-7 rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ background: "var(--bg-sunken)", color: copied ? "var(--success)" : "var(--text-3)" }}
          title="复制">
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
      <span className="text-[10px] px-1" style={{ color: "var(--text-4)" }}>{fmtTime(timestamp)}</span>
    </div>
  );
}
