"use client";

import { useState, useMemo, useEffect } from "react";
import { marked } from "marked";
import { Copy, Check, Eye, EyeOff } from "lucide-react";

marked.setOptions({
  breaks: true,
  gfm: true,
});

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

  const renderedHtml = useMemo(() => {
    try {
      let t = text;
      t = t.replace(/```filepath:([^\n]+)\n/g, (_, name) => {
        const ext = name.trim().split(".").pop()?.toLowerCase() || "";
        const langMap: Record<string, string> = { html: "html", css: "css", js: "javascript", ts: "typescript", py: "python", json: "json", md: "markdown" };
        return `\`\`\`${langMap[ext] || ext}\n`;
      });
      let html = marked.parse(t) as string;
      html = html.replace(/(✅\s*确定|⚠️?\s*大概率准确|❓\s*不确定|⚠️?\s*需要验证)/g,
        '<span class="df-confidence">$1</span>');
      return html;
      return html;
    } catch {
      return `<pre style="white-space:pre-wrap">${text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`;
    }
  }, [text]);

  const tocItems = useMemo(() => {
    const headings: { level: number; text: string; id: string }[] = [];
    const regex = /<h([1-3])[^>]*>(.*?)<\/h\1>/gi;
    let match;
    while ((match = regex.exec(renderedHtml)) !== null) {
      const rawText = match[2].replace(/<[^>]*>/g, "");
      headings.push({ level: parseInt(match[1]), text: rawText, id: `heading-${headings.length}` });
    }
    return headings;
  }, [renderedHtml]);

  const htmlWithIds = useMemo(() => {
    if (tocItems.length === 0) return renderedHtml;
    let idx = 0;
    return renderedHtml.replace(/<h([1-3])([^>]*)>/gi, (m, level, attrs) => {
      const id = tocItems[idx]?.id || `h-${idx}`;
      idx++;
      return `<h${level}${attrs} id="${id}">`;
    });
  }, [renderedHtml, tocItems]);

  const showToc = tocItems.length >= 3 && text.length > 800;

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex flex-col gap-1 group relative">
      <div className={`relative rounded-2xl px-4 py-3 ${isLong ? "max-h-[600px] overflow-y-auto" : ""}`}
        id="msg-content"
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-light)" }}>

        {/* TOC */}
        {showToc && (
          <div className="mb-3 pb-2" style={{ borderBottom: "1px solid var(--border-light)" }}>
            <div className="text-[10px] font-medium uppercase tracking-wider mb-1" style={{ color: "var(--text-4)" }}>目录</div>
            {tocItems.map((item, i) => (
              <a key={i} href={`#${item.id}`} onClick={e => {
                  e.preventDefault();
                  document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className="block text-[12px] py-0.5 hover:underline truncate"
                style={{ paddingLeft: `${(item.level - 1) * 12}px`, color: "var(--brand)" }}>
                {item.text}
              </a>
            ))}
          </div>
        )}

        <div className="df-markdown text-[14px] leading-relaxed" style={{ color: "var(--text-2)" }}
          dangerouslySetInnerHTML={{ __html: htmlWithIds }} />

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

        <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={handleCopy}
            className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
            style={{ background: "var(--bg-sunken)", color: copied ? "var(--success)" : "var(--text-3)" }}
            title="复制全文">
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2 px-1">
        <span className="text-[10px]" style={{ color: "var(--text-4)" }}>{fmtTime(timestamp)}</span>
        <span className="text-[10px]" style={{ color: "var(--text-4)" }}>· AI生成，仅供参考</span>
      </div>
    </div>
  );
}
