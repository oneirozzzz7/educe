"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import type { Locale } from "./types";

const dict = {
  "empty.title": { en: "What will you make?", zh: "想做点什么？" },
  "empty.sub": { en: "A game, a tool, an idea — anything.", zh: "一个游戏、一个工具、一个想法——都行。" },
  "empty.placeholder": { en: "Describe what you want to build...", zh: "描述你想做的东西..." },
  "sidebar.new": { en: "New brief", zh: "新任务" },
  "sidebar.recent": { en: "Recent", zh: "最近" },
  "brief.label": { en: "BRIEF", zh: "任务" },
  "process.analyzing": { en: "Analyzing", zh: "分析需求" },
  "process.structuring": { en: "Structuring", zh: "搭建结构" },
  "process.detailing": { en: "Detailing", zh: "填充细节" },
  "process.testing": { en: "Testing", zh: "测试修复" },
  "process.done": { en: "Done", zh: "完成" },
  "process.header": { en: "DRAWING OUT", zh: "引出中" },
  "process.activity": { en: "Activity", zh: "详细过程" },
  "decision.title": { en: "A few decisions", zh: "先确认一下" },
  "decision.sub": { en: "Quick choices for a better result.", zh: "几个选择，结果会更好。" },
  "decision.confirm": { en: "Confirm", zh: "确认开始" },
  "decision.skip": { en: "Skip", zh: "跳过，直接做" },
  "complete.passed": { en: "All checks passed", zh: "全部验证通过" },
  "complete.rounds": { en: "rounds", zh: "轮" },
  "action.copy": { en: "Copy", zh: "复制" },
  "action.download": { en: "Download", zh: "下载" },
  "action.open": { en: "Open in new tab", zh: "新窗口打开" },
  "action.files": { en: "Files", zh: "文件" },
  "action.refresh": { en: "Refresh", zh: "刷新" },
  "followup.placeholder": { en: "Add a feature, fix something, ask a question...", zh: "加功能、改bug、问问题..." },
  "thinking": { en: "Thinking", zh: "思考中" },
  "building": { en: "Building", zh: "构建中" },
  "starter.pomodoro": { en: "Pomodoro timer", zh: "番茄钟" },
  "starter.json": { en: "JSON formatter", zh: "JSON 工具" },
  "starter.game": { en: "Retro game", zh: "复古游戏" },
  "starter.dashboard": { en: "Data dashboard", zh: "数据看板" },
  "starter.editor": { en: "Markdown editor", zh: "编辑器" },
  "files.title": { en: "Files", zh: "文件" },
  "files.duration": { en: "Duration", zh: "耗时" },
  "files.rounds": { en: "Rounds", zh: "轮次" },
  "files.size": { en: "Size", zh: "大小" },
  "files.checks": { en: "Checks", zh: "检查" },
  "tagline": { en: "draw out", zh: "引而出之" },
  "time.now": { en: "now", zh: "进行中" },
  "time.just": { en: "just now", zh: "刚刚" },
} as const;

export type DictKey = keyof typeof dict;

interface LocaleCtx {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: DictKey) => string;
}

const LocaleContext = createContext<LocaleCtx>({
  locale: "zh",
  setLocale: () => {},
  t: (key) => dict[key]?.zh ?? key,
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    if (typeof window === "undefined") return "zh";
    return (localStorage.getItem("educe-lang") as Locale) || "zh";
  });

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    localStorage.setItem("educe-lang", l);
  }, []);

  const t = useCallback((key: DictKey): string => {
    const entry = dict[key];
    if (!entry) return key;
    return entry[locale];
  }, [locale]);

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  return useContext(LocaleContext);
}
