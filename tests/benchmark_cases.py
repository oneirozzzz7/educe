"""
Educe Benchmark v2 — 完整 30 case 定义（6领域 × 5）

每 case 含：指令、验收函数、fixture需求、是否需要judge。
验收分层：L1 纯程序化 / L2 半自动 / L3 needs_judge
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from educe.core.benchmark_runner import BenchmarkCase, CaseResult


# ═══════════════════════════════════════
#  通用验收工具
# ═══════════════════════════════════════

def _normalize(s: str) -> str:
    """去除所有空白/分隔符用于数值匹配"""
    return re.sub(r'[\s  ,.\-]', '', s)


def _get_reply_text(result: CaseResult) -> str:
    """从 events + trace 拼接完整回复文本"""
    parts = []
    for evt in result.events:
        if evt.get("name") == "model_output":
            parts.append(evt.get("data", {}).get("reply_preview", ""))
        if evt.get("summary", "").startswith("model_output"):
            parts.append(evt.get("summary", ""))
    # Also try reading trace for full LLM output
    import pathlib
    ws = pathlib.Path(result.workspace) if result.workspace else None
    if ws:
        log_dir = ws.parent / "logs"
        for trace_file in log_dir.rglob("trace.jsonl"):
            try:
                for line in trace_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    if t.get("kind") == "llm_output":
                        payload = str(t.get("payload", ""))
                        parts.append(payload)
            except Exception:
                pass
    return "\n".join(parts)


def _has_action(result: CaseResult, action_type: str) -> bool:
    for evt in result.events:
        if evt.get("type") == "tool_call":
            if evt.get("data", {}).get("action_type") == action_type:
                return True
    return False


def _has_any_action(result: CaseResult, types: set[str]) -> bool:
    for evt in result.events:
        if evt.get("type") == "tool_call":
            if evt.get("data", {}).get("action_type", "") in types:
                return True
    return False


def _file_exists(workspace: Path, pattern: str) -> list[Path]:
    """在 workspace 中查找匹配的文件"""
    return list(workspace.rglob(pattern))


def _file_contains(workspace: Path, filename: str, keyword: str) -> bool:
    for f in workspace.rglob(filename):
        if f.is_file():
            try:
                content = f.read_text(errors="ignore")
                if keyword in content:
                    return True
            except Exception:
                pass
    return False


# ═══════════════════════════════════════
#  CODE 领域（需要 click fixture）
# ═══════════════════════════════════════

CLICK_FIXTURE = "/tmp/educe_p0_click"


def code01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """CODE-01: 新增 version_print_option 或类似装饰器"""
    if _has_action(result, "edit_file"):
        decorators = ws / "src" / "click" / "decorators.py"
        if decorators.exists():
            content = decorators.read_text(errors="ignore")
            if "version_print" in content or "version_short" in content:
                return True, 1.0, "新装饰器已添加到 decorators.py"
        # 也可能加在别的文件
        for f in ws.rglob("*.py"):
            c = f.read_text(errors="ignore")
            if "version_print" in c or "version_short" in c or "version_only" in c:
                return True, 0.8, f"新装饰器在 {f.name}"
    return False, 0.0, "未找到新版本打印装饰器"


def code02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """CODE-02: BaseCommand 有 docstring"""
    core_py = ws / "src" / "click" / "core.py"
    if core_py.exists():
        content = core_py.read_text(errors="ignore")
        # 找 class BaseCommand 后面是否有 docstring
        match = re.search(r'class BaseCommand.*?:\s*\n\s*"""(.+?)"""', content, re.DOTALL)
        if match:
            return True, 1.0, f"docstring: {match.group(1)[:50]}"
    return False, 0.0, "BaseCommand 仍无 docstring"


def code03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """CODE-03: Command 类有 aliases 支持"""
    core_py = ws / "src" / "click" / "core.py"
    if core_py.exists():
        content = core_py.read_text(errors="ignore")
        if "aliases" in content and ("self.aliases" in content or "alias" in content):
            return True, 1.0, "aliases 属性已添加"
    return False, 0.0, "未找到 aliases 实现"


def code04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """CODE-04: 函数拆分（至少 edit_file 了）"""
    if _has_action(result, "edit_file"):
        return True, 0.7, "执行了文件编辑（需 judge 确认质量）"
    return False, 0.0, "未执行任何修改"


def code05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """CODE-05: 应该 clarify 而非直接动手"""
    # 检测是否触发了 clarify
    for evt in result.events:
        if evt.get("name") == "clarify_pause":
            return True, 1.0, "正确触发了 clarify"
    # 没 clarify 但也没动手 = 部分分
    if not _has_action(result, "edit_file"):
        reply = _get_reply_text(result)
        if "?" in reply or "？" in reply or "具体" in reply or "哪" in reply:
            return True, 0.7, "回复中有提问（非正式 clarify）"
    # 直接动手 = 0 分
    if _has_action(result, "edit_file"):
        return False, 0.0, "直接修改了代码，应该先 clarify"
    return False, 0.3, "未 clarify 也未动手"


# ═══════════════════════════════════════
#  FIN 领域
# ═══════════════════════════════════════

def fin01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """FIN-01: 月供计算 ≈ 13473"""
    reply = _get_reply_text(result)
    normalized = _normalize(reply)
    # 等额本息: 300万30年3.5% → 月供 13464~13482
    for target in range(13460, 13490):
        if str(target) in normalized:
            return True, 1.0, f"月供 {target} 正确"
    if "1347" in normalized:
        return True, 0.8, "月供约 13470 范围内"
    return False, 0.0, "未找到正确月供金额"


def fin02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """FIN-02: 生成了月度汇总文件"""
    csv_files = _file_exists(ws, "*.csv")
    if csv_files:
        return True, 1.0, f"生成了 CSV: {[f.name for f in csv_files]}"
    if _has_action(result, "write_file"):
        return True, 0.6, "写了文件但不是 CSV"
    return False, 0.0, "未生成汇总文件"


def fin03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """FIN-03: 应主动 clarify 风险偏好/期限"""
    for evt in result.events:
        if evt.get("name") == "clarify_pause":
            return True, 1.0, "正确 clarify 了"
    reply = _get_reply_text(result)
    if "风险" in reply and ("?" in reply or "？" in reply):
        return True, 0.7, "回复中问了风险相关问题"
    return False, 0.3, "未主动 clarify"


def fin04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """FIN-04: 输出了对比表"""
    reply = _get_reply_text(result)
    if "|" in reply or "增长" in reply:
        return True, 0.7, "有表格结构（需 judge 确认质量）"
    return False, 0.0, "未输出对比信息"


def fin05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """FIN-05: 生成了 HTML 文件"""
    html_files = _file_exists(ws, "*.html")
    if html_files:
        content = html_files[0].read_text(errors="ignore")
        if "canvas" in content or "chart" in content or "svg" in content:
            return True, 1.0, "HTML 含图表元素"
        return True, 0.7, "生成了 HTML 但可能无交互"
    return False, 0.0, "未生成 HTML"


# ═══════════════════════════════════════
#  TECH 领域
# ═══════════════════════════════════════

def tech01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """TECH-01: 执行了系统命令查看内存/磁盘"""
    if _has_action(result, "shell"):
        return True, 1.0, "执行了 shell 命令"
    if _has_any_action(result, {"read_dir", "shell"}):
        return True, 0.5, "做了某种系统查询"
    return False, 0.0, "未执行系统命令"


def tech02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """TECH-02: grep 提取 ERROR 并计数"""
    if _has_action(result, "shell"):
        reply = _get_reply_text(result)
        if "ERROR" in reply or "error" in reply or re.search(r'\d+\s*(条|个|行)', reply):
            return True, 1.0, "grep + 计数完成"
        return True, 0.6, "执行了命令但未确认计数"
    return False, 0.0, "未执行 grep"


def tech03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """TECH-03: 分析了依赖文件"""
    if _has_any_action(result, {"read_file", "shell", "read_dir"}):
        reply = _get_reply_text(result)
        if "版本" in reply or "version" in reply or "升级" in reply or "outdated" in reply:
            return True, 1.0, "分析了依赖并给出建议"
        return True, 0.5, "读了文件但分析不完整"
    return False, 0.0, "未分析依赖"


def tech04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """TECH-04: memorize 了 Docker 要点"""
    for evt in result.events:
        if evt.get("type") == "tool_call":
            at = evt.get("data", {}).get("action_type", "")
            if at == "memorize":
                return True, 1.0, "memorize 成功"
    reply = _get_reply_text(result)
    if "Docker" in reply and len(reply) > 100:
        return True, 0.5, "给了提纲但未 memorize"
    return False, 0.0, "未完成"


def tech05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """TECH-05: 创建了 REST API 文件"""
    py_files = _file_exists(ws, "*.py")
    if py_files:
        for f in py_files:
            content = f.read_text(errors="ignore")
            if ("flask" in content.lower() or "fastapi" in content.lower() or
                "get" in content.lower() and "post" in content.lower()):
                return True, 1.0, f"REST API 代码: {f.name}"
        return True, 0.5, "写了 Python 文件但可能不是 API"
    return False, 0.0, "未创建代码文件"


# ═══════════════════════════════════════
#  EDU 领域
# ═══════════════════════════════════════

def edu01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """EDU-01: 通俗解释函数"""
    reply = _get_reply_text(result)
    if len(reply) > 50 and ("函数" in reply or "function" in reply.lower()):
        return True, 0.8, "有回复（需 judge 确认通俗度）"
    return False, 0.0, "回复不完整"


def edu02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """EDU-02: 5道方程题 + 答案"""
    reply = _get_reply_text(result)
    # 检查是否有多个方程
    eq_count = len(re.findall(r'[=＝]', reply))
    if eq_count >= 5:
        return True, 1.0, f"找到 {eq_count} 个等式"
    if eq_count >= 3:
        return True, 0.6, f"只有 {eq_count} 个等式"
    return False, 0.0, f"等式不足 ({eq_count})"


def edu03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """EDU-03: memorize 了课程重点"""
    for evt in result.events:
        if evt.get("type") == "tool_call":
            at = evt.get("data", {}).get("action_type", "")
            if at == "memorize":
                return True, 1.0, "memorize 成功"
    reply = _get_reply_text(result)
    if "光合" in reply and len(reply) > 100:
        return True, 0.4, "给了内容但未 memorize"
    return False, 0.0, "未完成"


def edu04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """EDU-04: 应 clarify 时间安排"""
    for evt in result.events:
        if evt.get("name") == "clarify_pause":
            return True, 1.0, "正确 clarify 了"
    reply = _get_reply_text(result)
    if "时间" in reply and ("?" in reply or "？" in reply):
        return True, 0.7, "问了时间但非正式 clarify"
    if "第一周" in reply or "Week 1" in reply:
        return True, 0.5, "直接给了计划未 clarify"
    return False, 0.0, "未完成"


def edu05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """EDU-05: 交互式九九乘法表 HTML"""
    html_files = _file_exists(ws, "*.html")
    if html_files:
        content = html_files[0].read_text(errors="ignore")
        if "click" in content or "onclick" in content or "addEventListener" in content:
            if "乘法" in content or "table" in content.lower():
                return True, 1.0, "交互式乘法表 HTML"
            return True, 0.7, "HTML 有交互但主题不确定"
        return True, 0.4, "HTML 无交互"
    return False, 0.0, "未生成 HTML"


# ═══════════════════════════════════════
#  LIFE 领域
# ═══════════════════════════════════════

def life01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """LIFE-01: 创建了清单文件"""
    if _has_action(result, "write_file"):
        files = _file_exists(ws, "*")
        if files:
            return True, 1.0, f"创建了文件: {[f.name for f in files[:3]]}"
    reply = _get_reply_text(result)
    if "待办" in reply or "清单" in reply:
        return True, 0.4, "回复了但未存文件"
    return False, 0.0, "未完成"


def life02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """LIFE-02: 油钱计算"""
    reply = _get_reply_text(result)
    normalized = _normalize(reply)
    # 北京→上海 ~1200km, 8L/100km = 96L, 油价~7.5 → ~720元
    # 合理范围 600-900
    for n in range(600, 901, 10):
        if str(n) in normalized:
            return True, 1.0, f"计算结果 {n} 元在合理范围"
    if "油" in reply and re.search(r'\d{3,4}', reply):
        return True, 0.6, "有计算但精度不确定"
    return False, 0.0, "未计算"


def life03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """LIFE-03: 搬家清单（分阶段）"""
    reply = _get_reply_text(result)
    if ("搬家" in reply or "准备" in reply) and len(reply) > 100:
        if re.search(r'(前|后|当天|一周|三天)', reply):
            return True, 1.0, "有时间线分阶段"
        return True, 0.6, "有清单但无时间线"
    return False, 0.0, "未完成"


def life04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """LIFE-04: 英文请假邮件"""
    reply = _get_reply_text(result)
    if re.search(r'(Dear|Subject|leave|absence)', reply, re.IGNORECASE):
        if "sorry" not in reply.lower() or "apologize" not in reply.lower():
            return True, 1.0, "英文邮件，语气适当"
        return True, 0.7, "英文邮件但可能过于卑微"
    return False, 0.0, "未生成英文邮件"


def life05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """LIFE-05: 待办网页 CRUD + localStorage"""
    html_files = _file_exists(ws, "*.html")
    if html_files:
        content = html_files[0].read_text(errors="ignore")
        has_crud = ("add" in content.lower() or "delete" in content.lower())
        has_storage = "localStorage" in content
        if has_crud and has_storage:
            return True, 1.0, "CRUD + localStorage 完整"
        if has_crud:
            return True, 0.6, "有 CRUD 但无持久化"
        return True, 0.3, "生成了 HTML 但功能不全"
    return False, 0.0, "未生成 HTML"


# ═══════════════════════════════════════
#  SCI 领域
# ═══════════════════════════════════════

def sci01_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """SCI-01: 画正弦图 + 保存 png"""
    if _has_action(result, "shell"):
        png_files = _file_exists(ws, "*.png")
        if png_files:
            return True, 1.0, f"生成了 PNG: {png_files[0].name}"
    py_files = _file_exists(ws, "*.py")
    if py_files:
        for f in py_files:
            content = f.read_text(errors="ignore")
            if "sin" in content and ("savefig" in content or "plt" in content):
                return True, 0.7, "代码正确但可能未执行"
    return False, 0.0, "未完成"


def sci02_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """SCI-02: 数据集统计"""
    reply = _get_reply_text(result)
    if re.search(r'(\d+)\s*(行|列|row|col)', reply):
        return True, 1.0, "输出了行列统计"
    if _has_action(result, "shell"):
        return True, 0.5, "执行了命令但输出不确定"
    return False, 0.0, "未完成"


def sci03_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """SCI-03: t 检验"""
    reply = _get_reply_text(result)
    if re.search(r'[tp]\s*[=≈<>]', reply) or "显著" in reply or "significant" in reply.lower():
        return True, 1.0, "给出了 t/p 值和结论"
    if _has_action(result, "shell"):
        return True, 0.5, "执行了计算但结论不明确"
    return False, 0.0, "未完成"


def sci04_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """SCI-04: 拉丁方设计"""
    reply = _get_reply_text(result)
    if "拉丁方" in reply or "Latin" in reply:
        if re.search(r'[A-H1-8].*[A-H1-8].*[A-H1-8]', reply):
            return True, 1.0, "给出了具体分组方案"
        return True, 0.6, "提到了拉丁方但方案不完整"
    return False, 0.0, "未完成"


def sci05_check(result: CaseResult, ws: Path) -> tuple[bool, float, str]:
    """SCI-05: 箱线图 HTML"""
    html_files = _file_exists(ws, "*.html")
    if html_files:
        content = html_files[0].read_text(errors="ignore")
        if "box" in content.lower() or "whisker" in content.lower() or "canvas" in content:
            return True, 1.0, "箱线图 HTML"
        return True, 0.5, "生成了 HTML 但可能无箱线图"
    return False, 0.0, "未生成 HTML"


# ═══════════════════════════════════════
#  完整 Case 列表
# ═══════════════════════════════════════

ALL_CASES: list[BenchmarkCase] = [
    # === CODE ===
    BenchmarkCase("CODE-01", "L1", "CODE",
                  "我本地有个 click 项目。click 有个 @click.version_option 装饰器，但它打印版本号时带了 \"version\" 前缀文字。我想要一个简洁版的，只输出纯数字版本号，不带任何前缀。帮我加一个类似的装饰器。",
                  [code01_check], fixture_dir=CLICK_FIXTURE),
    BenchmarkCase("CODE-02", "L1", "CODE",
                  "这个项目的 core.py 里 BaseCommand 类没 docstring，补一个",
                  [code02_check], fixture_dir=CLICK_FIXTURE),
    BenchmarkCase("CODE-03", "L2", "CODE",
                  "帮我给 Command 类加个 aliases 支持，一个命令可以用多个名字调用",
                  [code03_check], fixture_dir=CLICK_FIXTURE),
    BenchmarkCase("CODE-04", "L2", "CODE",
                  "这个项目里有个函数特别长看着头疼，帮我拆一下",
                  [code04_check], fixture_dir=CLICK_FIXTURE, needs_judge=True),
    BenchmarkCase("CODE-05", "L3", "CODE",
                  "这个项目的错误处理太分散了，能整理统一一点吗？",
                  [code05_check], fixture_dir=CLICK_FIXTURE, needs_judge=True),

    # === FIN ===
    BenchmarkCase("FIN-01", "L1", "FIN",
                  "帮我算下这笔房贷：300万，30年，利率3.5%，等额本息，月供多少",
                  [fin01_check]),
    BenchmarkCase("FIN-02", "L1", "FIN",
                  "把这个 CSV 里的交易记录按月汇总支出，存成新文件",
                  [fin02_check]),
    BenchmarkCase("FIN-03", "L2", "FIN",
                  "我有10万，想做个简单的资产配置，风险中等，给个方案",
                  [fin03_check], needs_judge=True),
    BenchmarkCase("FIN-04", "L2", "FIN",
                  "对比这三家公司近三年的营收增长，做个表",
                  [fin04_check], needs_judge=True),
    BenchmarkCase("FIN-05", "L3", "FIN",
                  "做一个可交互的复利计算器网页，能调本金/利率/年限看曲线",
                  [fin05_check]),

    # === TECH ===
    BenchmarkCase("TECH-01", "L1", "TECH",
                  "查下这台机器的内存和磁盘占用",
                  [tech01_check]),
    BenchmarkCase("TECH-02", "L1", "TECH",
                  "帮我把这个 log 里所有 ERROR 行提取出来计数",
                  [tech02_check]),
    BenchmarkCase("TECH-03", "L2", "TECH",
                  "帮我把这个项目的依赖列一下，看有没有过时的",
                  [tech03_check]),
    BenchmarkCase("TECH-04", "L2", "TECH",
                  "我想给团队介绍一下 Docker，做个要点提纲，记下来",
                  [tech04_check]),
    BenchmarkCase("TECH-05", "L3", "TECH",
                  "搭一个最小的 REST API demo，有 GET/POST 两个接口，能跑起来",
                  [tech05_check]),

    # === EDU ===
    BenchmarkCase("EDU-01", "L1", "EDU",
                  "用初中生能懂的话解释什么是函数",
                  [edu01_check], needs_judge=True),
    BenchmarkCase("EDU-02", "L1", "EDU",
                  "给我出5道二元一次方程练习题，带答案",
                  [edu02_check]),
    BenchmarkCase("EDU-03", "L2", "EDU",
                  "帮我备一节关于光合作用的课，记一下重点和板书安排",
                  [edu03_check]),
    BenchmarkCase("EDU-04", "L2", "EDU",
                  "我想学 Python，但完全零基础，给个4周计划",
                  [edu04_check]),
    BenchmarkCase("EDU-05", "L3", "EDU",
                  "做个交互式九九乘法表网页，点击格子高亮整行整列",
                  [edu05_check]),

    # === LIFE ===
    BenchmarkCase("LIFE-01", "L1", "LIFE",
                  "帮我把这周的待办整理成清单存起来：周一交报告，周三开会，周五团建",
                  [life01_check]),
    BenchmarkCase("LIFE-02", "L1", "LIFE",
                  "算下北京到上海开车大概多少油钱，油耗8升百公里",
                  [life02_check]),
    BenchmarkCase("LIFE-03", "L2", "LIFE",
                  "我下周要搬家，帮我列个准备清单，别漏东西",
                  [life03_check]),
    BenchmarkCase("LIFE-04", "L2", "LIFE",
                  "帮我写封英文邮件，跟导师请两天假，理由是家里有事，语气正式但不卑微",
                  [life04_check]),
    BenchmarkCase("LIFE-05", "L3", "LIFE",
                  "做一个精美的个人待办网页，支持添加/完成/删除，数据本地存",
                  [life05_check]),

    # === SCI ===
    BenchmarkCase("SCI-01", "L1", "SCI",
                  "写一段 Python 代码画正弦函数图像，保存成图片",
                  [sci01_check]),
    BenchmarkCase("SCI-02", "L1", "SCI",
                  "这个 CSV 数据集有多少行、多少列、各列的类型分布",
                  [sci02_check]),
    BenchmarkCase("SCI-03", "L2", "SCI",
                  "帮我对这组实验数据做个 t 检验，看两组有没有显著差异",
                  [sci03_check]),
    BenchmarkCase("SCI-04", "L2", "SCI",
                  "用拉丁方设计一个8人品鉴实验的分组方案",
                  [sci04_check]),
    BenchmarkCase("SCI-05", "L3", "SCI",
                  "做个数据可视化面板，展示三组实验数据的箱线图对比",
                  [sci05_check]),
]
