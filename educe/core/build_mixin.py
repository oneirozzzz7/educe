"""
Build Mixin — 从 orchestrator.py 抽取。
"""
from __future__ import annotations

import logging
import uuid

from educe.core.message import Message, MessageType, WorkContext

log = logging.getLogger("educe.orchestrator")


class BuildMixin:
    """Build methods for Orchestrator."""

    async def _run_build(self, user_input: str) -> WorkContext:
        pipeline_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user", content="__PIPELINE_START__")
        self._notify(pipeline_msg)

        # 注入统一知识系统到 context，供 builder 使用
        if self.unified_store:
            self.context.metadata["_unified_store"] = self.unified_store

        # 记录 build 开始事件
        if hasattr(self, 'state'):
            self.state.add_build_start()

        # 知识 recall（在 build 确认后执行，不干扰 _decide 意图判断）
        _sid = self.context.metadata.get("session_id", "")
        client = self._get_client()
        if client and self.unified_store:
            recalled = await self.unified_store.recall(
                user_input,
                lambda msgs: client.chat(
                    messages=msgs,
                    model=self.config.default_model.model,
                    max_tokens=50, temperature=0.0),
            )
            if recalled:
                existing = self.context.metadata.get("domain_knowledge", "")
                self.context.metadata["domain_knowledge"] = (
                    existing + "\n## 相关知识\n" + "\n".join(
                        f"- {e.content.body}" for e in recalled))
                self.context.metadata["_recalled_knowledge_ids"] = [
                    e.id for e in recalled]
                self.context.metadata["_recalled_knowledge_summary"] = "、".join(
                    e.content.body[:30] for e in recalled[:3])
                log_activity(_sid, "knowledge_recall",
                            count=len(recalled),
                            ids=[e.id for e in recalled],
                            previews=[e.preview for e in recalled])
                # transcript 记录（此时 transcript 已存在）
                transcript = self.context.metadata.get("_transcript")
                if transcript:
                    transcript.add("analyze", "system",
                        f"应用已有知识：{self.context.metadata['_recalled_knowledge_summary']}")

        task_id = uuid.uuid4().hex[:8]
        self.observer.start_task(task_id, user_input, self.config.default_model.model)

        # ═══ 0. 检测是否是追问迭代（已有代码，用户要求修改）═══
        has_prev_code = bool(self.context.artifacts.get("code_files"))
        prev_code_context = ""
        if has_prev_code:
            from pathlib import Path
            code_files = self.context.artifacts.get("code_files", [])
            parts = []
            for fp in code_files[:3]:
                p = Path(fp)
                if p.exists():
                    parts.append("```filepath:{}\n{}\n```".format(p.name, p.read_text(encoding="utf-8", errors="ignore")[:8000]))
            if parts:
                prev_code_context = "\n\n".join(parts)

        # ═══ 0b. 评估复杂度（迭代修改视为 simple）═══
        if prev_code_context:
            complexity = "simple"
        elif self.context.metadata.get("_task_complexity"):
            complexity = self.context.metadata["_task_complexity"]
        else:
            complexity = await self._assess_complexity(user_input)
        self.context.metadata["_task_complexity"] = complexity

        # ═══ A. 生成需求清单（修改场景跳过，只对新构建有用）═══
        checklist = []
        if not prev_code_context:
            try:
                from educe.core.checklist_judge import generate_checklist
                from educe.models.router import ModelClient
                client = ModelClient(api_key=self.config.default_model.api_key,
                                    base_url=self.config.default_model.base_url)
                checklist = await generate_checklist(client, self.config.default_model.model, user_input)
            except Exception as e:
                log.debug("checklist generation skipped: %s", e)

        # ═══ B. 把 checklist 注入 builder prompt ═══
        build_input = user_input
        if prev_code_context:
            build_input = (
                f"用户要求修改已有代码：{user_input}\n\n"
                f"【当前代码】\n{prev_code_context}\n\n"
                f"请在现有代码基础上进行修改，输出修改后的完整文件。"
            )
        elif checklist:
            checklist_text = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(checklist))
            build_input = (
                f"{user_input}\n\n"
                f"【核心功能要求（必须全部实现）】\n{checklist_text}\n\n"
                f"请逐项实现以上所有功能，确保每项都能正常工作。"
            )

        # ═══ 注入 seed 到 build 上下文（激发引擎核心链路）═══
        build_seed = ""
        if self.unified_store:
            build_seed = self.unified_store.get_seed_text("build", "general")
        if build_seed:
            self.context.metadata["_build_seed"] = build_seed

        # ═══ 注入 BehaviorManifest（Git for Agent Behavior）═══
        manifest = self._get_behavior_manifest()
        if manifest and manifest.active_units():
            self.context.metadata["_behavior_manifest"] = manifest

        # ═══ 执行构建 ═══
        self._slog("framework", "build_start",
                   summary=f"complexity={complexity}, has_prev={bool(prev_code_context)}",
                   data={"complexity": complexity, "has_prev_code": bool(prev_code_context),
                         "checklist_count": len(checklist)})
        _build_t0 = __import__("time").time()
        await self._run_agent("builder", build_input, "user", timeout=900)

        _build_ms = (__import__("time").time() - _build_t0) * 1000
        has_output = bool(self.context.artifacts.get("code_files"))
        self._slog("framework", "build_end",
                   duration_ms=_build_ms,
                   summary=f"{'success' if has_output else 'no output'}, {_build_ms/1000:.1f}s",
                   data={"has_output": has_output,
                         "files": list(self.context.artifacts.get("code_files", []))[:5]})

        if self.context.metadata.get("_pending_decisions"):
            return self.context

        # ═══ C. Checklist 验收（StepBuilder 已有内置验证，跳过）═══
        if has_output and checklist and complexity != "complex":
            try:
                from educe.core.checklist_judge import verify_checklist
                code_output = self.context.artifacts.get("engineer_output", "")
                if len(code_output) < 100:
                    # Read actual files for verification
                    from pathlib import Path
                    code_files = self.context.artifacts.get("code_files", [])
                    parts = []
                    for fp in code_files[:3]:
                        p = Path(fp)
                        if p.exists():
                            parts.append(p.read_text(encoding="utf-8", errors="ignore")[:5000])
                    code_output = "\n".join(parts)

                covered = await verify_checklist(client, self.config.default_model.model, checklist, code_output)
                coverage = sum(covered) / len(covered) if covered else 1.0

                # ═══ D. 不通过则修复 ═══
                if coverage < 0.8 and covered:
                    missing = [checklist[i] for i, c in enumerate(covered) if not c]
                    if missing:
                        fix_request = (
                            f"当前代码缺少以下功能，请补充实现：\n"
                            + "\n".join(f"- {item}" for item in missing)
                            + "\n\n请在现有代码基础上添加缺失功能。"
                        )
                        # 通知前端正在修复
                        progress_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                                              content="__BUILD_PROGRESS__验收发现缺失功能，修复中...")
                        self._notify(progress_msg)
                        await self._run_agent("builder", fix_request, "system", timeout=300)
            except Exception as e:
                log.warning("build verification failed: %s", e)

        has_output = bool(self.context.artifacts.get("code_files"))
        self.observer.finish_task(success=has_output, project_type=self.context.artifacts.get("project_type", ""),
                                 file_count=len(self.context.artifacts.get("code_files", [])))
        _sid = self.context.metadata.get("session_id", "")
        log_activity(_sid, "build_complete",
                    success=has_output,
                    files=len(self.context.artifacts.get("code_files", [])),
                    complexity=self.context.metadata.get("_task_complexity", "?"))

        # 记录 build 完成事件
        if hasattr(self, 'state'):
            code_files = self.context.artifacts.get("code_files", [])
            self.state.add_build_complete(code_files, success=has_output)
            # 推送 build_complete 给前端
            import json as _json_bc
            from pathlib import Path as _Path_bc
            bc_event = {
                "event": "build_complete",
                "success": has_output,
                "files": [_Path_bc(f).name for f in code_files],
            }
            bc_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                           content="__TOOL_EVENT__" + _json_bc.dumps(bc_event, ensure_ascii=False))
            self._notify(bc_msg)

        # 采集 SessionSignal 到统一知识系统
        if self.unified_store:
            import time as _t
            transcript = self.context.metadata.get("_transcript")
            phases = {}
            if transcript:
                for e in transcript.entries:
                    if e.elapsed and e.phase:
                        phases[e.phase] = phases.get(e.phase, 0) + e.elapsed

            recalled_ids = self.context.metadata.get("_recalled_knowledge_ids", [])

            self.unified_store.record_signal({
                "type": "build",
                "session_id": self.context.metadata.get("session_id", ""),
                "request": {
                    "user_input": user_input[:200],
                    "task_type": "build",
                    "complexity": self.context.metadata.get("_task_complexity", "unknown"),
                },
                "execution": {
                    "duration_seconds": round(sum(phases.values()), 1),
                    "phases": phases,
                    "iterations": self.context.artifacts.get("version", 1),
                    "file_count": len(self.context.artifacts.get("code_files", [])),
                    "model": self.config.default_model.model,
                },
                "signals": {
                    "success": has_output,
                    "user_signal": "pending",
                },
                "seeds_used": {
                    "build_seed_id": "seed_build_general",
                },
                "knowledge_used": recalled_ids,
            })

            # 构建成功后：让模型判断是否有可提炼的经验写入知识系统
            if has_output:
                asyncio.create_task(
                    self._maybe_extract_knowledge(user_input, recalled_ids))

        # Session级保存
        session_id = self.context.metadata.get("session_id", "")
        if session_id:
            # Session store only saves a reference — actual files live on disk
            code_files = self.context.artifacts.get("code_files", [])
            file_names = [f.split("/")[-1] for f in code_files]
            # Persist transcript entries for history replay
            transcript = self.context.metadata.get("_transcript")
            transcript_data = None
            if transcript:
                transcript_data = [
                    {"phase": e.phase, "role": e.role, "content": e.content, "elapsed": e.elapsed}
                    for e in transcript.entries
                ]
            self.session_store.append_turn(
                session_id, user_input, ",".join(file_names),
                turn_type="code",
                domain="tech",
                metadata={"transcript": transcript_data} if transcript_data else None,
            )

        # 给conversation加完成记录（简短摘要，不是完整代码）
        code_files = self.context.artifacts.get("code_files", [])
        if code_files:
            filenames = [f.split("/")[-1] for f in code_files]
            summary = "[已完成代码生成] 文件：{}".format(", ".join(filenames))
        else:
            summary = "[代码任务未能完成]"
        self.conversation.add_assistant(summary, domain="tech")
        if hasattr(self, 'state'):
            self.state.add_ai_reply(summary)
            asyncio.create_task(self._evolve_from_result())

        if not has_output:
            fail_msg = Message(type=MessageType.RESULT, sender="system", receiver="user",
                              content="未能生成可用的产出物，请更具体描述需求。")
            self.context.add_message(fail_msg)
            self._notify(fail_msg)

        self.context.metadata.pop("_skip_analysis", None)
        self.context.metadata.pop("_pending_request", None)
        return self.context

    async def _quick_tool_check(self) -> bool:
        """轻量级工具检查——秒级验证，不调LLM"""
        from educe.core.tools import RunHTMLTool, RunPythonTool
        code_files = self.context.artifacts.get("code_files", [])
        for filepath in code_files:
            if filepath.endswith(".html"):
                tool = RunHTMLTool()
                result = await tool.execute({"path": filepath})
                if "问题" in result or "错误" in result:
                    return False
            elif filepath.endswith(".py"):
                tool = RunPythonTool()
                result = await tool.execute({"path": filepath})
                if "失败" in result or "错误" in result:
                    return False
        return True

    # ═══════════════════════════════════════
    #  修改已有产出物
    # ═══════════════════════════════════════

    async def _run_modify(self, user_input: str) -> WorkContext:
        prev = self.context.artifacts.get("engineer_output", "")
        await self._run_agent("builder",
            f"用户要求修改：{user_input}\n\n当前代码：\n{prev[:4000]}\n\n输出修改后的完整文件。",
            "user", timeout=180)
        return self.context

    # ═══════════════════════════════════════
    #  决策（模型自己判断）
    # ═══════════════════════════════════════

