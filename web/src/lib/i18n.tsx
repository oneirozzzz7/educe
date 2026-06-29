"use client";

import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import type { Locale } from "./types";

const dict = {
  "empty.title": { en: "What will you make?", zh: "想做点什么？" },
  "empty.sub": { en: "A game, a tool, an idea — anything.", zh: "一个游戏、一个工具、一个想法——都行。" },
  "empty.placeholder": { en: "Describe what you want to build...", zh: "描述你想做的东西..." },
  "sidebar.new": { en: "New brief", zh: "新任务" },
  "sidebar.recent": { en: "Recent", zh: "最近" },
  "sidebar.search": { en: "Search...", zh: "搜索..." },
  "sidebar.empty": { en: "No tasks yet", zh: "暂无任务" },
  "sidebar.untitled": { en: "Untitled", zh: "未命名" },
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
  "decision.confirm": { en: "Confirm & build", zh: "确认并开始构建" },
  "decision.skip": { en: "Skip, just do it", zh: "跳过，直接做" },
  "decision.hint": { en: "Let me confirm a few key points for a better result", zh: "帮我确认几个关键点，这样能做出更好的结果" },
  "decision.note_placeholder": { en: "Add your thoughts (optional)", zh: "补充你的想法（可选）" },
  "decision.building": { en: "Building...", zh: "正在构建..." },
  "complete.passed": { en: "All checks passed", zh: "全部验证通过" },
  "complete.rounds": { en: "rounds", zh: "轮" },
  "action.copy": { en: "Copy", zh: "复制" },
  "action.copied": { en: "Copied", zh: "已复制" },
  "action.download": { en: "Download", zh: "下载" },
  "action.open": { en: "Open in new tab", zh: "新窗口打开" },
  "action.files": { en: "Files", zh: "文件" },
  "action.refresh": { en: "Refresh", zh: "刷新" },
  "action.preview": { en: "Preview", zh: "预览" },
  "action.hide_preview": { en: "Hide preview", zh: "收起预览" },
  "action.code": { en: "Code", zh: "代码" },
  "action.hide_code": { en: "Hide code", zh: "收起代码" },
  "action.expand": { en: "Expand", zh: "展开全文" },
  "action.collapse": { en: "Collapse", zh: "收起" },
  "action.copy_all": { en: "Copy all", zh: "复制全文" },
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
  "files.toc": { en: "Table of contents", zh: "目录" },
  "tagline": { en: "draw out", zh: "引而出之" },
  "time.now": { en: "now", zh: "进行中" },
  "time.just": { en: "just now", zh: "刚刚" },
  "time.mins_ago": { en: "m ago", zh: "分钟前" },
  "time.hours_ago": { en: "h ago", zh: "小时前" },
  "time.days_ago": { en: "d ago", zh: "天前" },
  "convo.placeholder": { en: "Ask a follow-up...", zh: "继续追问..." },
  "error.disconnected": { en: "Not connected", zh: "未连接" },
  "log.write": { en: "Write", zh: "写入" },
  "log.run": { en: "Run", zh: "运行" },
  "log.passed": { en: "Passed", zh: "通过" },
  "log.done": { en: "Done", zh: "完成" },
  "log.read": { en: "Read", zh: "已读取" },
  "log.executing": { en: "Executing...", zh: "执行中..." },
  "settings": { en: "Settings", zh: "设置" },
  "settings.provider": { en: "Provider", zh: "服务商" },
  "settings.model": { en: "Model", zh: "模型" },
  "settings.configured": { en: "(configured)", zh: "(已配置)" },
  "settings.configured_keep": { en: "Configured, leave empty to keep", zh: "已配置，留空保持不变" },
  "settings.evolution": { en: "Self-evolution", zh: "自进化" },
  "settings.evolution_desc": { en: "Accumulate experience during use", zh: "使用过程中自动积累经验" },
  "settings.cancel": { en: "Cancel", zh: "取消" },
  "settings.save": { en: "Save", zh: "保存" },
  "settings.saving": { en: "Saving...", zh: "保存中..." },
  "settings.save_failed": { en: "Save failed", zh: "保存失败" },
  "settings.custom": { en: "Custom", zh: "自定义" },
  "convergence.stalled": { en: "Stuck", zh: "遇到困难" },
  "convergence.edited": { en: "Modified", zh: "已修改" },
  "convergence.exploring_done": { en: "Exploration done", zh: "探索完成" },
  "convergence.exploring": { en: "Exploring", zh: "探索中" },
  "convergence.in_progress": { en: "In progress", zh: "进行中" },
  "convergence.retry_hint": { en: "Might need a different approach", zh: "可能需要换个思路" },
  "convergence.pending": { en: "pending", zh: "待解决" },
  "tool.modify": { en: "Modify", zh: "修改" },
  "tool.write": { en: "Write", zh: "写入" },
  "tool.background": { en: "Background", zh: "后台" },
  "tool.stop": { en: "Stop", zh: "停止" },
  "evolution.idle": { en: "Inactive", zh: "未激活" },
  "evolution.observing": { en: "Observing", zh: "观察中" },
  "evolution.proposed": { en: "Proposed", zh: "待确认" },
  "evolution.revert_proposed": { en: "Revert proposed", zh: "建议撤销" },
  "evolution.crystallized": { en: "Active", zh: "已生效" },
  "evolution.dismissed": { en: "Dismissed", zh: "已忽略" },
  "evolution.title": { en: "Evolution Status", zh: "进化状态" },
  "evolution.loading": { en: "Loading...", zh: "加载中..." },
  "evolution.empty": { en: "No evolution records yet. The system will start learning after observing your patterns.", zh: "暂无进化记录。系统会在观察到你的使用模式后自动开始学习。" },
  "evolution.verbosity": { en: "Response length", zh: "回答详略" },
  "evolution.preferences_active": { en: "preferences active", zh: "个偏好已生效" },
  "evolution.evolving": { en: "Evolving", zh: "进化中" },
  "evolution.observations": { en: "observations", zh: "个观察" },
  "evolution.standby": { en: "Evolution standby", zh: "进化待机" },
  "evolution.revert": { en: "Revert", zh: "撤销" },
  "evolution.revert_pref": { en: "Revert this preference", zh: "撤销此偏好" },
  "evolution.observed_n": { en: "Observed", zh: "观察" },
  "evolution.confirmed_n": { en: "Confirmed", zh: "确认" },
  "evolution.times": { en: "times", zh: "次" },
  "evolution.current_injection": { en: "Current injection:", zh: "当前注入：" },
  "feedback.title": { en: "Feedback", zh: "反馈" },
  "feedback.issue_title": { en: "Report an issue", zh: "反馈问题" },
  "feedback.placeholder": { en: "What went wrong? Or any suggestions?", zh: "遇到什么问题？或者有什么建议？" },
  "feedback.send": { en: "Send", zh: "发送" },
  "feedback.thanks": { en: "Received, thanks!", zh: "已收到，感谢反馈" },
  "work.generating": { en: "Generating...", zh: "生成中..." },
  "work.processing": { en: "Processing...", zh: "处理中..." },
  "work.done_steps": { en: "Done", zh: "完成" },
  "work.steps": { en: "steps", zh: "步" },
  "work.live_generating": { en: "Live generating...", zh: "实时生成中..." },
  "work.confirmed": { en: "Confirmed", zh: "已确认执行" },
  "work.skipped": { en: "Skipped", zh: "已跳过" },
  "work.project": { en: "Current project:", zh: "当前项目：" },
  "file.no_image_support": { en: "Current model does not support image understanding, images will be ignored", zh: "当前模型不支持图片理解，图片将被忽略" },
  "plan.complex_hint": { en: "This is a complex project, choose an approach first", zh: "这是一个复杂项目，建议先选择方案" },
  "activity.no_preview": { en: "(Cannot load preview)", zh: "(无法加载预览)" },
  "label.builder": { en: "Builder", zh: "构建" },
  "label.tester": { en: "Tester", zh: "测试" },
  "label.planner": { en: "Planner", zh: "规划" },
  "label.project_manager": { en: "PM", zh: "项目管理" },
  "label.product_manager": { en: "Product", zh: "产品" },
  "label.architect": { en: "Architect", zh: "架构" },
  "label.engineer": { en: "Engineer", zh: "工程" },
  "label.reviewer": { en: "Reviewer", zh: "审查" },
  "label.crowd_user": { en: "Beta", zh: "内测" },
  "label.memory_keeper": { en: "Memory", zh: "沉淀" },
  "label.assistant": { en: "Assistant", zh: "助手" },
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
  const [locale, setLocaleState] = useState<Locale>("zh");

  useEffect(() => {
    const saved = localStorage.getItem("educe-lang") as Locale;
    if (saved && saved !== locale) setLocaleState(saved);
  }, []);

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
