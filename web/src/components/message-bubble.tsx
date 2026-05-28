"use client";

import { useState, useMemo, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { Copy, Check, Eye, EyeOff } from "lucide-react";

function hasHtmlContent(text: string): boolean {
  return /<!DOCTYPE|<html[\s>]/i.test(text) || /```(?:filepath:[^\n]+\.html|html)\n[\s\S]*?<\/html>/i.test(text);
}

function extractEmbeddedHtml(text: string): string | null {
  const m1 = text.match(/```filepath:[^\n]+\.html\n([\s\S]*?<\/html>)/i);
  if (m1) return m1[1];
  const m2 = text.match(/```html\n([\s\S]*?<\/html>)/i);
  if (m2) return m2[1];
  const m3 = text.match(/(<!DOCTYPE[\s\S]*?<\/html>)/i);
  if (m3) return m3[1];
  return null;
}

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <div className="relative group/code my-2 rounded-lg overflow-hidden" style={{ background: "var(--bg-sunken)" }}>
      {language && (
        <div className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider" style={{ color: "var(--text-4)", borderBottom: "1px solid var(--border-light)" }}>
          {language}
        </div>
      )}
      <pre className="px-3 py-2.5 overflow-x-auto text-[12px] leading-relaxed font-mono" style={{ color: "var(--text-2)" }}>
        <code>{children}</code>
      </pre>
      <button onClick={copy}
        className="absolute top-1.5 right-1.5 w-6 h-6 rounded flex items-center justify-center opacity-0 group-hover/code:opacity-100 transition-opacity"
        style={{ background: "var(--bg-elevated)", color: copied ? "var(--success)" : "var(--text-3)" }}>
        {copied ? <Check size={11} /> : <Copy size={11} />}
      </button>
    </div>
  );
}

export function MessageBubble({ text, timestamp, fmtTime }: {
  text: string; timestamp: number; fmtTime: (ts: number) => string;
}) {
  const [copied, setCopied] = useState(false);
  const [showHtmlPreview, setShowHtmlPreview] = useState(false);
  const isLong = text.length > 500;

  const embeddedHtml = useMemo(() => hasHtmlContent(text) ? extractEmbeddedHtml(text) : null, [text]);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!embeddedHtml) { setBlobUrl(null); return; }
    const u = URL.createObjectURL(new Blob([embeddedHtml], { type: "text/html" }));
    setBlobUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [embeddedHtml]);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const cleanText = useMemo(() => {
    let t = text;
    // 清理 ```filepath:xxx 格式——转换为标准 ```html 等
    t = t.replace(/```filepath:([^\n]+)\n/g, (_, name) => {
      const ext = name.trim().split(".").pop()?.toLowerCase() || "";
      const langMap: Record<string, string> = { html: "html", css: "css", js: "javascript", ts: "typescript", py: "python", json: "json", md: "markdown" };
      return `\`\`\`${langMap[ext] || ext}\n`;
    });
    return t;
  }, [text]);

  function safeRender() {
    try {
      return (
        <ReactMarkdown
          components={{
            h1: ({ children }) => <h1 className="text-lg font-semibold mt-4 mb-2 first:mt-0" style={{ color: "var(--text)" }}>{children}</h1>,
            h2: ({ children }) => <h2 className="text-base font-semibold mt-3.5 mb-1.5 first:mt-0" style={{ color: "var(--text)" }}>{children}</h2>,
            h3: ({ children }) => <h3 className="text-[14px] font-semibold mt-3 mb-1 first:mt-0" style={{ color: "var(--text)" }}>{children}</h3>,
            h4: ({ children }) => <h4 className="text-[13px] font-semibold mt-2.5 mb-1 first:mt-0" style={{ color: "var(--text)" }}>{children}</h4>,
            p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
            ul: ({ children }) => <ul className="mb-2 pl-5 list-disc space-y-0.5">{children}</ul>,
            ol: ({ children }) => <ol className="mb-2 pl-5 list-decimal space-y-0.5">{children}</ol>,
            li: ({ children }) => <li className="text-[14px] leading-relaxed">{children}</li>,
            strong: ({ children }) => <strong className="font-semibold" style={{ color: "var(--text)" }}>{children}</strong>,
            em: ({ children }) => <em className="italic">{children}</em>,
            blockquote: ({ children }) => (
              <blockquote className="pl-3 my-2 italic" style={{ borderLeft: "3px solid var(--brand)", color: "var(--text-3)" }}>{children}</blockquote>
            ),
            hr: () => <hr className="my-4" style={{ borderColor: "var(--border-light)" }} />,
            code: ({ className, children }) => {
              const lang = className?.replace("language-", "") || "";
              const content = String(children).replace(/\n$/, "");
              const isMultiLine = content.includes("\n");
              if (className?.includes("language-") || isMultiLine) {
                return <CodeBlock language={lang}>{content}</CodeBlock>;
              }
              return (
                <code className="px-1.5 py-0.5 rounded text-[13px] font-mono"
                  style={{ background: "var(--bg-sunken)", color: "var(--brand)" }}>
                  {children}
                </code>
              );
            },
            pre: ({ children }) => <>{children}</>,
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 transition-colors hover:opacity-80" style={{ color: "var(--brand)" }}>{children}</a>
            ),
            table: ({ children }) => (
              <div className="overflow-x-auto my-3 rounded-lg" style={{ border: "1px solid var(--border-light)" }}>
                <table className="w-full text-[13px] border-collapse">{children}</table>
              </div>
            ),
            thead: ({ children }) => <thead style={{ background: "var(--bg-sunken)" }}>{children}</thead>,
            th: ({ children }) => (
              <th className="px-3 py-2 text-left font-medium text-[12px]" style={{ borderBottom: "1px solid var(--border)", color: "var(--text)" }}>{children}</th>
            ),
            td: ({ children }) => (
              <td className="px-3 py-2 text-[13px]" style={{ borderBottom: "1px solid var(--border-light)" }}>{children}</td>
            ),
            img: ({ src, alt }) => (
              <span className="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded" style={{ background: "var(--bg-sunken)", color: "var(--text-3)" }}>
                📎 {alt || "image"}
              </span>
            ),
          }}
        >
          {cleanText}
        </ReactMarkdown>
      );
    } catch {
      return <div className="whitespace-pre-wrap text-[14px] leading-relaxed">{text}</div>;
    }
  }

  return (
    <div className="flex flex-col gap-1 group relative">
      <div className={`relative rounded-2xl px-4 py-3 ${isLong ? "max-h-[600px] overflow-y-auto" : ""}`}
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-light)" }}>
        <div className="text-[14px] leading-relaxed" style={{ color: "var(--text-2)" }}>
          {safeRender()}
        </div>

        {/* HTML预览区 */}
        {embeddedHtml && blobUrl && (
          <div className="mt-3 rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
            <div className="px-3 py-1.5 flex items-center gap-2" style={{ background: "var(--bg-sunken)" }}>
              <button onClick={() => setShowHtmlPreview(!showHtmlPreview)}
                className="text-[11px] font-medium flex items-center gap-1"
                style={{ color: "var(--brand)" }}>
                {showHtmlPreview ? <EyeOff size={11} /> : <Eye size={11} />}
                {showHtmlPreview ? "收起预览" : "查看预览"}
              </button>
              <a href={blobUrl} target="_blank" rel="noopener" className="text-[11px] ml-auto" style={{ color: "var(--text-3)" }}>
                新窗口打开 ↗
              </a>
            </div>
            {showHtmlPreview && (
              <iframe src={blobUrl} className="w-full h-[350px] bg-white" tabIndex={0} />
            )}
          </div>
        )}

        {/* 操作栏 */}
        <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={handleCopy}
            className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
            style={{ background: "var(--bg-sunken)", color: copied ? "var(--success)" : "var(--text-3)" }}
            title="复制全文">
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
        </div>
      </div>
      <span className="text-[10px] px-1" style={{ color: "var(--text-4)" }}>{fmtTime(timestamp)}</span>
    </div>
  );
}
