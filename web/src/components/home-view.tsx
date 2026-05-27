"use client";

import { useState, useRef } from "react";

interface Props {
  onSend: (text: string) => void;
}

const TEMPLATES = [
  { icon: "🍅", label: "番茄钟", prompt: "帮我做一个番茄钟，25分钟倒计时" },
  { icon: "🔧", label: "JSON工具", prompt: "做一个JSON格式化工具，语法高亮" },
  { icon: "🎮", label: "小游戏", prompt: "做一个贪吃蛇游戏" },
  { icon: "📝", label: "编辑器", prompt: "做一个Markdown实时预览编辑器" },
  { icon: "🌐", label: "网站", prompt: "做一个个人博客首页" },
];

export function HomeView({ onSend }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  function submit() {
    if (!text.trim()) return;
    onSend(text);
    setText("");
  }

  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center w-full max-w-[540px] px-5">
        <div className="w-12 h-12 mx-auto mb-4 rounded-xl bg-gradient-to-br from-accent to-violet-600 flex items-center justify-center text-xl shadow-lg shadow-accent/20">
          ⚡
        </div>
        <h2 className="text-xl font-semibold tracking-tight mb-1">What will you build?</h2>
        <p className="text-sm text-neutral-500 mb-5">7 AI Agents 协作完成</p>

        <div className="relative mb-4">
          <textarea
            ref={ref}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
            }}
            placeholder="描述你想创建的东西..."
            rows={1}
            className="w-full bg-surface border border-border-bright rounded-xl px-4 py-3 pr-12 text-sm text-white resize-none outline-none min-h-[48px] max-h-[100px] transition-all focus:border-accent focus:shadow-[0_0_0_2px_theme(colors.accent.dim)]"
          />
          <button
            onClick={submit}
            className="absolute right-2 bottom-2 w-8 h-8 rounded-full bg-accent flex items-center justify-center hover:scale-105 transition-transform"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <div className="flex gap-1.5 flex-wrap justify-center">
          {TEMPLATES.map((t) => (
            <button
              key={t.label}
              onClick={() => onSend(t.prompt)}
              className="px-3 py-1.5 bg-surface border border-border rounded-full text-[11px] text-neutral-400 hover:border-accent hover:text-neutral-200 transition-all hover:-translate-y-px"
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
