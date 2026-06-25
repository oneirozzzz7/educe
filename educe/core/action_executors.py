"""
Action Executor Mixin — 从 orchestrator.py 抽取的工具执行方法。

所有 _exec_* 方法通过 mixin 注入 Orchestrator 类。
"""
from __future__ import annotations

import asyncio
import logging

from educe.core.activity_log import log_activity

log = logging.getLogger("educe.orchestrator")


class ActionExecutorMixin:
    """Mixin providing all _exec_* tool execution methods."""

    async def _exec_recall(self, action, session_id: str) -> dict:
        """检索知识系统，返回具体内容"""
        if not self.unified_store:
            return {"success": False, "output": "知识系统未初始化"}

        keyword = action.params.strip()
        # 从 catalog 中搜索匹配的条目
        results = []
        for entry_data in self.unified_store._catalog:
            preview = entry_data.get("preview", "")
            domain = entry_data.get("domain", "")
            category = entry_data.get("category", "")
            if (keyword in preview or keyword in domain or keyword in category):
                entry = self.unified_store.get_entry(entry_data["id"])
                if entry:
                    results.append(entry.content.body)

        if not results:
            return {"success": True, "output": f"未找到与「{keyword}」相关的记忆。"}

        # 记录 recalled IDs 用于反馈闭环
        recalled_ids = [e["id"] for e in self.unified_store._catalog
                       if keyword in e.get("preview", "") or keyword in e.get("domain", "")]
        self.context.metadata["_recalled_knowledge_ids"] = recalled_ids
        log_activity(session_id, "knowledge_recall",
                    count=len(results), ids=recalled_ids,
                    keyword=keyword)

        lines = "\n".join(f"- {r}" for r in results[:5])
        return {"success": True, "output": f"找到 {len(results)} 条相关记忆：\n{lines}"}

    async def _exec_shell(self, action, session_id: str) -> dict:
        """执行 shell 命令（流式输出 + 自动后台检测）

        设计（Opus 4.8 确认）：
        - 立即开始 pump stdout/stderr
        - shield(wait) + GRACE_PERIOD 判定前台/后台
        - 通过 tool_start/tool_chunk/tool_end 推送流式事件
        """
        import json as _json_sh
        import os
        import time as _time_sh

        from educe.core.streaming_registry import (
            gen_tool_id, ToolHandle, get_config,
        )

        raw = action.params.strip()
        if not raw:
            return {"success": False, "output": "命令为空"}

        cwd_override = None
        try:
            parsed = _json_sh.loads(raw)
            cmd = parsed.get("cmd") or parsed.get("command") or raw
            cwd_override = parsed.get("cwd")
        except (ValueError, TypeError):
            cmd = raw

        cmd = cmd.rstrip().rstrip("&").rstrip()

        BLOCKED = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){", "sudo rm",
                   "chmod -R 777 /", "> /dev/sda", "shutdown", "reboot", "init 0"]
        cmd_lower = cmd.lower()
        for blocked in BLOCKED:
            if blocked in cmd_lower:
                return {"success": False, "output": f"安全限制：禁止执行危险命令 ({blocked})"}

        from pathlib import Path
        if cwd_override:
            work_dir = Path(cwd_override).expanduser()
        elif self.context.metadata.get("_project_context_path"):
            work_dir = Path(self.context.metadata["_project_context_path"])
        else:
            work_dir = Path(".educe/output") / session_id[:16]
        work_dir.mkdir(parents=True, exist_ok=True)

        env = {**os.environ, "PATH": os.environ.get("PATH", "")}
        # 注入用户凭据到 shell 环境（不暴露在命令字符串中）
        try:
            from educe.core.credential_store import CredentialStore
            cred_env = CredentialStore().get_env_dict()
            env.update(cred_env)
        except Exception as e:
            log.debug("credential injection skipped: %s", e)
        supervisor = self._get_process_supervisor()
        grace_period = get_config("shell", "grace_period_ms", 5000) / 1000.0
        max_output = get_config("shell", "max_output_bytes", 512000)
        max_line = get_config("shell", "max_line_bytes", 4096)
        timeout_s = get_config("shell", "timeout_s", 300)

        tool_id = gen_tool_id()
        start_mono = _time_sh.monotonic()

        self._emit_tool_event({
            "type": "tool_start",
            "id": tool_id,
            "tool": "shell",
            "meta": {"cmd": cmd, "cwd": str(work_dir)},
        })

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, cwd=str(work_dir), env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            handle = ToolHandle(
                tool_id=tool_id, tool="shell", proc=proc,
                meta={"cmd": cmd, "cwd": str(work_dir), "session_id": session_id},
            )
            self.streaming_registry.register(handle)

            collected = {"stdout": [], "stderr": [], "bytes": 0}

            async def pump(stream, name: str):
                while True:
                    if handle.cancel_event.is_set():
                        break
                    try:
                        line = await asyncio.wait_for(
                            stream.readline(), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        break
                    if not line:
                        break
                    decoded = line.decode(errors="replace")
                    if len(decoded) > max_line:
                        decoded = decoded[:max_line] + "…(truncated)\n"
                    collected[name].append(decoded)
                    collected["bytes"] += len(decoded)
                    self._emit_tool_event({
                        "type": "tool_chunk",
                        "id": tool_id,
                        "stream": name,
                        "data": decoded,
                    })
                    if collected["bytes"] > max_output:
                        break

            pump_stdout = asyncio.create_task(pump(proc.stdout, "stdout"))
            pump_stderr = asyncio.create_task(pump(proc.stderr, "stderr"))
            handle.pumps = [pump_stdout, pump_stderr]
            wait_task = asyncio.create_task(proc.wait())
            handle.wait_task = wait_task

            try:
                await asyncio.wait_for(
                    asyncio.shield(wait_task), timeout=grace_period)
            except asyncio.TimeoutError:
                if supervisor.is_full(session_id):
                    proc.terminate()
                    await asyncio.gather(pump_stdout, pump_stderr,
                                         return_exceptions=True)
                    self.streaming_registry.unregister(tool_id)
                    duration_ms = int((_time_sh.monotonic() - start_mono) * 1000)
                    self._emit_tool_event({
                        "type": "tool_end", "id": tool_id,
                        "result": {"exit_code": -1, "duration_ms": duration_ms,
                                   "background": False, "error": "后台进程已满"},
                    })
                    return {"success": False,
                            "output": f"$ {cmd}\n后台进程已满（最多{supervisor.MAX_PER_SESSION}个），请先停止旧服务"}

                supervisor.register(proc, cmd, session_id, str(work_dir))
                early = "".join(collected["stdout"])[:2000]
                log_activity(session_id, "shell_background", cmd=cmd[:100], pid=proc.pid)

                duration_ms = int((_time_sh.monotonic() - start_mono) * 1000)
                self._emit_tool_event({
                    "type": "tool_end", "id": tool_id,
                    "result": {"exit_code": None, "duration_ms": duration_ms,
                               "background": True, "pid": proc.pid},
                })
                self.streaming_registry.unregister(tool_id)
                return {
                    "success": True,
                    "output": (
                        f"$ {cmd}\n[cwd: .]\n"
                        f"[后台启动] PID={proc.pid}\n"
                        f"{early}"
                        f"服务已在后台运行（最长{int(supervisor.MAX_TTL/60)}分钟）。"
                    ),
                }

            await asyncio.gather(pump_stdout, pump_stderr, return_exceptions=True)
            self.streaming_registry.unregister(tool_id)

            stdout = "".join(collected["stdout"])
            stderr = "".join(collected["stderr"])
            output = stdout
            if stderr:
                output += ("\n[stderr]\n" + stderr) if output else stderr
            output = output[:5000] or "（无输出）"

            duration_ms = int((_time_sh.monotonic() - start_mono) * 1000)
            cancelled = handle.cancel_event.is_set()

            self._emit_tool_event({
                "type": "tool_end", "id": tool_id,
                "result": {
                    "exit_code": proc.returncode,
                    "duration_ms": duration_ms,
                    "background": False,
                    "cancelled": cancelled,
                },
            })

            log_activity(session_id, "shell_exec", cmd=cmd[:100],
                         success=proc.returncode == 0, exit_code=proc.returncode)

            # I/O Gateway: shell effect
            if hasattr(self, 'effects'):
                self.effects.emit("shell",
                    intent={"cmd": cmd[:200], "cwd": str(work_dir)},
                    outcome={"exit_code": proc.returncode,
                             "stdout_len": len(stdout),
                             "stderr_len": len(stderr),
                             "stdout_preview": stdout[:300]})

            if proc.returncode == 0:
                import re as _re_cd
                cd_match = _re_cd.match(r'cd\s+(/[^\s;&|]+)', cmd)
                if cd_match:
                    cd_path = Path(cd_match.group(1))
                    if cd_path.is_dir():
                        self.context.metadata["_project_context_path"] = str(cd_path)
                cd_and_match = _re_cd.match(r'cd\s+(/[^\s;&|]+)\s*&&', cmd)
                if cd_and_match:
                    cd_path = Path(cd_and_match.group(1))
                    if cd_path.is_dir():
                        self.context.metadata["_project_context_path"] = str(cd_path)

            if proc.returncode != 0:
                import os as _os_organ
                if _os_organ.environ.get("EDUCE_BARE_MODE", "0") != "1":
                    # Verify-Compile Loop: 失败分类 + 环境缺失自动修复
                    from educe.core.failure_classifier import classify_failure, AutoFixer
                    full_output = output + "\n" + stderr
                    classification = classify_failure(full_output)

                    if classification.auto_fixable:
                        fixer = self.context.metadata.setdefault("_auto_fixer", AutoFixer())
                        if not fixer.already_fixed(classification.detail) and fixer.can_fix():
                            fix_result = await fixer.attempt_fix(classification, str(work_dir))
                            if fix_result["success"]:
                                self._auto_write_memory(
                                    "scar",
                                    f"Command '{cmd[:50]}' failed: {classification.kind} ({classification.detail}). Auto-fixed: {fix_result['output'][:60]}",
                                    detail_key=f"{classification.kind}:{classification.detail}",
                                    tags=[classification.kind],
                                )
                                self._emit_tool_event({
                                    "type": "tool_chunk", "id": tool_id,
                                    "stream": "stdout",
                                    "data": f"\n🔧 {fix_result['output']}\n",
                                })
                                return {
                                    "success": False,
                                    "output": f"$ {cmd}\n[环境修复] {fix_result['output']}\n请重试该命令。",
                                    "_auto_fixed": True,
                                }

                    # 原有器官修复逻辑
                    organ_result = await self._try_organ(
                        cmd, full_output, proc.returncode, work_dir, session_id)
                    if organ_result:
                        return organ_result

            return {
                "success": proc.returncode == 0,
                "output": f"$ {cmd}\n[cwd: .]\n{output}\n[exit: {proc.returncode}]",
            }

        except Exception as e:
            self.streaming_registry.unregister(tool_id)
            duration_ms = int((_time_sh.monotonic() - start_mono) * 1000)
            self._emit_tool_event({
                "type": "tool_end", "id": tool_id,
                "result": {"exit_code": -1, "duration_ms": duration_ms,
                           "error": str(e)[:200]},
            })
            return {"success": False, "output": f"$ {cmd}\n执行失败: {str(e)[:200]}"}



    async def _exec_read_file(self, action, session_id: str = "") -> dict:
        """读取指定文件内容（诚实降级：二进制文件返回元信息而非乱码）"""
        from pathlib import Path
        import mimetypes

        target = action.params.strip()
        if not target:
            return {"success": False, "output": "未指定文件路径"}

        path = Path(target).expanduser()

        # 相对路径基于 session output_dir 解析
        if not path.is_absolute():
            if self.context.metadata.get("_project_context_path"):
                base = Path(self.context.metadata["_project_context_path"])
            else:
                base = Path(".educe/output") / session_id[:16]
            path = base / path

        if not path.exists():
            return {"success": False, "output": f"文件不存在: {target}"}
        if not path.is_file():
            return {"success": False, "output": f"不是文件: {target}（如果是目录请用 read_dir）"}

        size = path.stat().st_size
        mime = mimetypes.guess_type(path.name)[0] or "unknown"
        ext = path.suffix.lower()

        # 读取前 8KB 探测编码
        sample = path.read_bytes()[:8192]
        try:
            sample.decode("utf-8")
            encoding = "utf-8"
            decodable = True
        except UnicodeDecodeError:
            try:
                sample.decode("gbk")
                encoding = "gbk"
                decodable = True
            except UnicodeDecodeError:
                encoding = "unknown"
                decodable = False

        has_null = b"\x00" in sample

        if not decodable or has_null:
            meta = f"文件: {path.name}\n类型: {mime}\n扩展名: {ext}\n大小: {size} bytes\n编码: {encoding}\n可解码: {decodable}\nNull字节: {has_null}"
            hex_preview = sample[:256].hex(" ", 1)
            if hasattr(self, 'effects'):
                self.effects.emit("file_read",
                    intent={"path": target},
                    outcome={"success": True, "path": str(path), "size": size,
                             "encoding": encoding, "decodable": False})
            return {"success": True, "output": f"{meta}\n\n[前256字节 hex]\n{hex_preview}"}

        # 可以作为文本读取
        content = path.read_text(encoding=encoding, errors="replace")
        truncated = False
        if size > 100_000:
            content = content[:10000]
            truncated = True

        lines = content.count("\n") + 1

        if truncated:
            header = f"文件: {path.name} ({lines}行, 截断至前10000字符, 原文件{size}字节)"
        else:
            header = f"文件: {path.name} ({lines}行, {size}字节)"

        # I/O Gateway: file_read effect
        if hasattr(self, 'effects'):
            self.effects.emit("file_read",
                intent={"path": target},
                outcome={"success": True, "path": str(path), "size": size,
                         "lines": lines, "encoding": encoding, "decodable": True})

        return {"success": True, "output": f"{header}\n```\n{content}\n```"}

    async def _exec_write_file(self, action, session_id: str = "") -> dict:
        """写入/修改指定文件（流式：先推内容再写盘）

        支持两种格式（按优先级）：
        1. Heredoc: "path: /tmp/x.py\n---\n文件内容"（Markdown-native，主格式）
        2. JSON: {"path":"...","content":"..."}（向后兼容）
        """
        import json as _json_wf
        import time as _time_wf
        from pathlib import Path
        from educe.core.streaming_registry import gen_tool_id, get_config

        raw = action.params.strip()
        file_path = ""
        content = ""

        if raw.startswith("path:") or raw.startswith("path："):
            first_line, rest = raw.split('\n', 1) if '\n' in raw else (raw, "")
            file_path = first_line.split(':', 1)[1].strip()
            if '\n---\n' in rest:
                content = rest.split('\n---\n', 1)[1]
            elif rest.startswith('---\n'):
                content = rest[4:]
            else:
                content = rest

        if not file_path:
            try:
                params = _json_wf.loads(raw)
                file_path = params.get("path", "")
                content = params.get("content", "")
            except (ValueError, TypeError):
                pass

        if not file_path and '\n' in raw:
            lines = raw.split('\n', 1)
            if '/' in lines[0] or '.' in lines[0]:
                file_path = lines[0].strip()
                content = lines[1]

        if not file_path:
            return {"success": False, "output": "未指定文件路径"}
        if not content:
            return {"success": False, "output": f"文件内容为空 (path={file_path})"}

        path = Path(file_path).expanduser()

        if self.context.metadata.get("_project_context_path"):
            base = Path(self.context.metadata["_project_context_path"])
        else:
            base = Path(".educe/output") / session_id[:16]
        base.mkdir(parents=True, exist_ok=True)

        if not path.is_absolute():
            path = base / path
        elif not path.parent.exists():
            path = base / path.name

        str_path = str(path)
        if any(str_path.startswith(d) for d in ["/etc", "/usr", "/bin", "/sbin", "/System"]):
            return {"success": False, "output": f"安全限制：禁止写入系统目录 ({path.parent})"}

        tool_id = gen_tool_id()
        start_mono = _time_wf.monotonic()
        existed = path.exists()
        mode = "modify" if existed else "create"

        self._emit_tool_event({
            "type": "tool_start",
            "id": tool_id,
            "tool": "write_file",
            "meta": {"path": file_path, "mode": mode},
        })

        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            if mode == "modify":
                max_diff_lines = get_config("write_file", "max_diff_lines", 5000)
                old_content = path.read_text(encoding="utf-8", errors="replace")
                old_lines = old_content.splitlines(keepends=True)
                new_lines = content.splitlines(keepends=True)

                if len(old_lines) <= max_diff_lines and len(new_lines) <= max_diff_lines:
                    import difflib
                    diff = "".join(difflib.unified_diff(
                        old_lines, new_lines,
                        fromfile=f"a/{file_path}", tofile=f"b/{file_path}",
                        lineterm=""))
                    if diff:
                        self._emit_tool_event({
                            "type": "tool_chunk",
                            "id": tool_id,
                            "stream": "diff",
                            "data": diff,
                        })
                    else:
                        self._emit_tool_event({
                            "type": "tool_chunk",
                            "id": tool_id,
                            "stream": "content",
                            "data": "(内容无变化)\n",
                        })
                else:
                    self._emit_tool_event({
                        "type": "tool_chunk",
                        "id": tool_id,
                        "stream": "content",
                        "data": f"(文件过大 {len(new_lines)} 行，跳过 diff)\n",
                    })
            else:
                for line in content.splitlines(keepends=True):
                    self._emit_tool_event({
                        "type": "tool_chunk",
                        "id": tool_id,
                        "stream": "content",
                        "data": line,
                    })

            path.write_text(content, encoding="utf-8")

            # I/O Gateway: file_write effect
            if hasattr(self, 'effects'):
                self.effects.emit("file_write",
                    intent={"path": file_path},
                    outcome={"success": True, "path": str(path), "size": len(content),
                             "mode": mode, "lines": len(content.splitlines())})
                self._emit_tool_event({
                    "type": "artifact_produced",
                    "path": str(path),
                    "filename": path.name,
                    "size": len(content),
                    "mode": mode,
                })

            duration_ms = int((_time_wf.monotonic() - start_mono) * 1000)
            lines_count = len(content.splitlines())
            self._emit_tool_event({
                "type": "tool_end",
                "id": tool_id,
                "result": {
                    "mode": mode,
                    "lines": lines_count,
                    "chars": len(content),
                    "duration_ms": duration_ms,
                },
            })

            action_word = "修改" if existed else "创建"
            display_path = file_path
            return {"success": True, "output": f"✅ {action_word}文件: {display_path}\n({len(content)}字符, {lines_count}行)"}
        except Exception as e:
            duration_ms = int((_time_wf.monotonic() - start_mono) * 1000)
            self._emit_tool_event({
                "type": "tool_end",
                "id": tool_id,
                "result": {"error": str(e)[:200], "duration_ms": duration_ms},
            })
            return {"success": False, "output": f"写入失败: {e}"}

    async def _exec_edit_file(self, action, session_id: str = "") -> dict:
        """局部编辑文件：搜索替换（git conflict 标记格式）"""
        import re as _re_edit
        from pathlib import Path

        raw = action.params.strip()

        # 解析 path
        file_path = ""
        if raw.startswith("path:") or raw.startswith("path："):
            first_line, rest = raw.split("\n", 1)
            file_path = first_line.split(":", 1)[1].strip()
            raw = rest
        else:
            return {"success": False, "output": "edit_file 需要 path: 行"}

        # 解析 OLD/NEW（git conflict 标记）
        old_match = _re_edit.search(r'<{3,}\s*OLD\s*\n([\s\S]*?)\n={3,}\n([\s\S]*?)\n>{3,}\s*NEW', raw)
        if not old_match:
            return {"success": False, "output": "格式错误：需要 <<<<<<< OLD\\n原文\\n=======\\n新文\\n>>>>>>> NEW"}

        old_string = old_match.group(1)
        new_string = old_match.group(2)

        # 解析文件路径
        base = Path(".educe/output") / session_id[:16] if session_id else Path(".")
        if self.context.metadata.get("_project_context_path"):
            base = Path(self.context.metadata["_project_context_path"])
        base.mkdir(parents=True, exist_ok=True)

        path = base / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            inferred = self._infer_project_path(file_path)
            if inferred and inferred.exists():
                path = inferred
            else:
                return {"success": False, "output": f"文件不存在: {file_path}"}

        content = path.read_text(encoding="utf-8", errors="ignore")

        # 分级匹配
        def normalize_trailing(s):
            return "\n".join(line.rstrip() for line in s.split("\n"))

        def strip_lines(s):
            return "\n".join(line.strip() for line in s.split("\n"))

        # Level 0: 精确匹配
        if old_string in content:
            new_content = content.replace(old_string, new_string, 1)
        # Level 1: 行尾空白归一化
        elif normalize_trailing(old_string) in normalize_trailing(content):
            c_norm = normalize_trailing(content)
            o_norm = normalize_trailing(old_string)
            idx = c_norm.find(o_norm)
            lines = content.split("\n")
            norm_lines = normalize_trailing(content).split("\n")
            start_line = c_norm[:idx].count("\n")
            end_line = start_line + o_norm.count("\n")
            new_lines = lines[:start_line] + new_string.split("\n") + lines[end_line + 1:]
            new_content = "\n".join(new_lines)
        # Level 2: strip 后匹配
        elif strip_lines(old_string) in strip_lines(content):
            c_stripped = strip_lines(content)
            o_stripped = strip_lines(old_string)
            idx = c_stripped.find(o_stripped)
            start_line = c_stripped[:idx].count("\n")
            end_line = start_line + o_stripped.count("\n")
            lines = content.split("\n")
            new_lines = lines[:start_line] + new_string.split("\n") + lines[end_line + 1:]
            new_content = "\n".join(new_lines)
        else:
            # 匹配失败——给诊断信息
            lines = content.split("\n")
            first_word = old_string.split("\n")[0].strip()[:30]
            candidates = [(i+1, l.strip()[:60]) for i, l in enumerate(lines) if first_word and first_word in l][:5]
            hint = "\n".join(f"  第{n}行: {t}" for n, t in candidates) if candidates else "  无相似内容"
            return {"success": False, "output": f"未找到匹配内容。\n最相似的行：\n{hint}\n请用 read_lines 确认原文后重试。"}

        # 唯一性检查
        count = content.count(old_string)
        if count > 1:
            positions = []
            idx = 0
            for _ in range(min(count, 5)):
                idx = content.find(old_string, idx)
                line_no = content[:idx].count("\n") + 1
                positions.append(f"  第{line_no}行")
                idx += 1
            return {"success": False, "output": f"old_string 匹配到 {count} 处，无法确定改哪个：\n" + "\n".join(positions) + "\n请加入更多上下文使其唯一。"}

        # 写回
        path.write_text(new_content, encoding="utf-8")
        changed_lines = abs(new_content.count("\n") - content.count("\n"))
        return {"success": True, "output": f"✅ 已修改 {file_path}（替换成功，变更约{changed_lines}行）"}

    async def _exec_search_in_file(self, action, session_id: str = "") -> dict:
        """在文件中搜索关键词，返回行号+上下文"""
        from pathlib import Path

        parts = action.params.strip().split("\n", 1)
        if len(parts) < 2:
            return {"success": False, "output": "格式：第一行文件路径，第二行搜索关键词"}

        file_path, query = parts[0].strip(), parts[1].strip()

        base = Path(".educe/output") / session_id[:16] if session_id else Path(".")
        if self.context.metadata.get("_project_context_path"):
            base = Path(self.context.metadata["_project_context_path"])

        path = base / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            inferred = self._infer_project_path(file_path)
            if inferred and inferred.exists():
                path = inferred
            else:
                return {"success": False, "output": f"文件不存在: {file_path}"}

        content = path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        results = []
        for i, line in enumerate(lines):
            if query.lower() in line.lower():
                context_lines = []
                for j in range(max(0, i-2), min(len(lines), i+3)):
                    prefix = "→" if j == i else " "
                    context_lines.append(f"{prefix} {j+1:4d} | {lines[j]}")
                results.append("\n".join(context_lines))
                if len(results) >= 10:
                    break

        if not results:
            return {"success": True, "output": f"未找到 '{query}' in {file_path}"}

        output = f"在 {file_path} 中找到 {len(results)} 处：\n\n" + "\n\n".join(results)
        return {"success": True, "output": output[:3000]}

    async def _exec_read_lines(self, action, session_id: str = "") -> dict:
        """读取文件指定行范围"""
        from pathlib import Path

        parts = action.params.strip().split("\n", 1)
        if len(parts) < 2:
            return {"success": False, "output": "格式：第一行文件路径，第二行行号范围（如 100-120）"}

        file_path = parts[0].strip()
        range_str = parts[1].strip()

        base = Path(".educe/output") / session_id[:16] if session_id else Path(".")
        if self.context.metadata.get("_project_context_path"):
            base = Path(self.context.metadata["_project_context_path"])

        path = base / file_path if not Path(file_path).is_absolute() else Path(file_path)
        if not path.exists():
            # Fallback: 尝试从 shell 历史推断项目路径
            inferred = self._infer_project_path(file_path)
            if inferred and inferred.exists():
                path = inferred
            else:
                return {"success": False, "output": f"文件不存在: {file_path}"}

        content = path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        # 解析范围
        import re
        m = re.match(r'(\d+)\s*[-~]\s*(\d+)', range_str)
        if not m:
            return {"success": False, "output": f"无法解析行号范围: {range_str}（格式如 100-120）"}

        start = max(1, int(m.group(1)))
        end = min(len(lines), int(m.group(2)))

        result_lines = []
        for i in range(start - 1, end):
            result_lines.append(f"{i+1:4d} | {lines[i]}")

        output = f"文件: {file_path} (第{start}-{end}行，共{len(lines)}行)\n" + "\n".join(result_lines)

        if hasattr(self, 'effects'):
            self.effects.emit("file_read",
                intent={"path": file_path},
                outcome={"success": True, "path": str(path), "lines": len(lines),
                         "range": f"{start}-{end}"})

        return {"success": True, "output": output[:3000]}

    def _infer_project_path(self, relative_path: str):
        """从 shell 历史推断项目根路径，解析相对文件路径。

        安全约束：
        - 拒绝含 .. 的路径（防遍历）
        - 只允许 /tmp/ 和用户目录下的路径
        - 不跟踪符号链接
        """
        from pathlib import Path

        if ".." in relative_path:
            return None

        history = self.conversation.get_history_for_llm() if hasattr(self, 'conversation') else []
        import re
        candidates = set()
        SAFE_PREFIXES = ("/tmp/", "/private/tmp/", str(Path.home()) + "/")

        for msg in reversed(history[-10:]):
            content = msg.get("content", "")
            for m in re.finditer(r'cd\s+(/[^\s;&|]+)', content):
                path_str = m.group(1).rstrip('/')
                if any(path_str.startswith(p) for p in SAFE_PREFIXES):
                    candidates.add(path_str)
            for m in re.finditer(r'\[cwd:\s*(/[^\]]+)\]', content):
                path_str = m.group(1).rstrip('/')
                if any(path_str.startswith(p) for p in SAFE_PREFIXES):
                    candidates.add(path_str)
            for m in re.finditer(r'(/tmp/[^\s\]"\']+)', content):
                p = Path(m.group(1))
                if p.is_dir() and not p.is_symlink():
                    candidates.add(str(p))
                elif p.parent.is_dir() and not p.parent.is_symlink():
                    candidates.add(str(p.parent))

        for cand in candidates:
            full = Path(cand) / relative_path
            if full.exists() and not full.is_symlink():
                resolved = full.resolve()
                if any(str(resolved).startswith(p.rstrip('/')) for p in SAFE_PREFIXES):
                    self.context.metadata["_project_context_path"] = cand
                    return full
        return None

    def _normalize_tool_params(self, action_type: str, params: str) -> str:
        """将 JSON 格式参数转换为内置 action 的纯文本格式"""
        if not params.strip().startswith("{"):
            return params
        try:
            import json as _j
            data = _j.loads(params)
        except (ValueError, TypeError):
            return params

        if action_type == "read_lines":
            path = data.get("path") or data.get("file") or data.get("file_path", "")
            start = data.get("start") or data.get("from") or data.get("start_line", "")
            end = data.get("end") or data.get("to") or data.get("end_line", "")
            range_str = data.get("range", "")
            if not range_str and start and end:
                range_str = f"{start}-{end}"
            return f"{path}\n{range_str}" if range_str else params

        elif action_type == "search_in_file":
            path = data.get("path") or data.get("file") or data.get("file_path", "")
            query = data.get("query") or data.get("keyword") or data.get("pattern") or data.get("search", "")
            return f"{path}\n{query}" if path and query else params

        elif action_type == "edit_file":
            path = data.get("path") or data.get("file") or data.get("file_path", "")
            old = data.get("old") or data.get("old_string") or data.get("search", "")
            new = data.get("new") or data.get("new_string") or data.get("replace", "")
            if path and old is not None and new is not None:
                return f"path: {path}\n<<<<<<< OLD\n{old}\n=======\n{new}\n>>>>>>> NEW"
            return params

        elif action_type == "read_dir":
            path = data.get("path") or data.get("dir") or data.get("directory", "")
            return path if path else params

        elif action_type == "read_file":
            path = data.get("path") or data.get("file") or data.get("file_path", "")
            return path if path else params

        elif action_type == "write_file":
            path = data.get("path") or data.get("file") or data.get("file_path", "")
            content = data.get("content") or data.get("text") or data.get("data", "")
            if path and content:
                import json as _j2
                return _j2.dumps({"path": path, "content": content}, ensure_ascii=False)
            return params

        elif action_type == "shell":
            cmd = data.get("cmd") or data.get("command") or data.get("script", "")
            return cmd if cmd else params

        return params

    async def _exec_plan(self, action, session_id: str) -> dict:
        """执行多步计划——逐步执行每个步骤，反馈结果"""
        import json as _json_plan

        try:
            params = _json_plan.loads(action.params)
            steps = params.get("steps", [])
        except (ValueError, TypeError):
            steps = [action.params.strip()]

        if not steps:
            return {"success": False, "output": "计划为空"}

        # Get model client
        client = self._get_client()
        if not client:
            return {"success": False, "output": "模型未配置"}

        results = []
        context_so_far = ""

        # Notify frontend about plan start
        if hasattr(self, 'state'):
            self.state.add_event("plan_start", steps=steps, total=len(steps))

        notify_fn = self.context.metadata.get("_notify_fn")

        for i, step in enumerate(steps):
            # Notify progress
            if hasattr(self, 'state'):
                self.state.add_event("transcript", content=f"步骤 {i+1}/{len(steps)}: {step}")
            if notify_fn:
                progress_msg = Message(type=MessageType.SYSTEM, sender="system", receiver="user",
                    content=f"__TOOL_EVENT__" + _json_plan.dumps({
                        "event": "transcript", "phase": "plan", "role": "system",
                        "content": f"📋 步骤 {i+1}/{len(steps)}: {step}", "elapsed": 0
                    }, ensure_ascii=False))
                notify_fn(progress_msg)

            # Ask model to execute this step
            step_prompt = (
                f"你正在执行一个多步计划。\n"
                f"当前是第 {i+1}/{len(steps)} 步：{step}\n"
            )
            if context_so_far:
                step_prompt += f"\n之前步骤的结果：\n{context_so_far[-2000:]}\n"
            step_prompt += "\n请执行这一步。可以使用 read_dir/read_file/shell 等 action，也可以直接给出分析。"

            try:
                response = await client.chat(
                    messages=[
                        {"role": "system", "content": "你是 Educe Agent，正在逐步执行用户的计划。每步只做一件事，简洁输出结果。"},
                        {"role": "user", "content": step_prompt},
                    ],
                    model=self.config.default_model.model,
                    max_tokens=1500,
                )
                step_result = response or "(无输出)"
            except Exception as e:
                step_result = f"(步骤失败: {str(e)[:100]})"

            results.append(f"步骤{i+1} [{step}]: {step_result[:300]}")
            context_so_far += f"\n步骤{i+1}: {step_result[:500]}"

        # Summary
        output = f"✅ 计划执行完成 ({len(steps)}步)\n\n" + "\n".join(results)

        if hasattr(self, 'state'):
            self.state.add_event("transcript", content=f"计划执行完成 ({len(steps)}步)")

        return {"success": True, "output": output[:4000]}

    async def _exec_read_dir(self, action) -> dict:
        """读取目录结构，返回文件树 + 关键文件摘要"""
        from pathlib import Path
        import os

        target = action.params.strip()
        if not target:
            return {"success": False, "output": "未指定目录路径"}

        # 兼容 JSON 格式参数 {"path": "..."}
        if target.startswith("{"):
            try:
                import json as _j
                parsed = _j.loads(target)
                target = parsed.get("path") or parsed.get("dir") or target
            except (ValueError, TypeError):
                pass

        target_path = Path(target).expanduser()
        if not target_path.is_absolute() and self.context.metadata.get("_project_context_path"):
            # 相对路径基于项目上下文解析
            target_path = Path(self.context.metadata["_project_context_path"]) / target
        if not target_path.exists():
            # Fallback: 尝试推断
            inferred = self._infer_project_path(target)
            if inferred and inferred.exists():
                target_path = inferred
            else:
                return {"success": False, "output": f"目录不存在: {target}"}
        if not target_path.is_dir():
            # Single file — read it
            try:
                content = target_path.read_text(encoding="utf-8", errors="ignore")[:5000]
                return {"success": True, "output": f"文件 {target_path.name}:\n```\n{content}\n```"}
            except Exception as e:
                return {"success": False, "output": f"读取失败: {e}"}

        # Build file tree
        IGNORE = {".git", "node_modules", "__pycache__", ".next", ".educe", "venv", ".venv", "dist", "build"}
        CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".java", ".go", ".rs", ".rb", ".sh"}

        lines = []
        key_files = []
        file_count = 0

        for root, dirs, files in os.walk(str(target_path)):
            dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith(".")]
            rel = Path(root).relative_to(target_path)
            depth = len(rel.parts)
            if depth > 4:
                continue

            indent = "  " * depth
            if depth > 0:
                lines.append(f"{indent}{rel.name}/")

            for f in sorted(files)[:30]:
                fp = Path(root) / f
                ext = fp.suffix.lower()
                size = fp.stat().st_size
                lines.append(f"{indent}  {f} ({size}B)")
                file_count += 1

                if ext in CODE_EXTS and size < 10000 and len(key_files) < 5:
                    try:
                        content = fp.read_text(encoding="utf-8", errors="ignore")[:2000]
                        key_files.append(f"### {fp.relative_to(target_path)}\n```\n{content}\n```")
                    except Exception as e:
                        log.debug("read_dir preview skipped %s: %s", fp, e)

            if file_count > 100:
                lines.append("  ... (超过100个文件，已截断)")
                break

        tree = "\n".join(lines[:80])
        summaries = "\n\n".join(key_files)
        output = f"目录: {target_path}\n文件数: {file_count}\n\n## 结构\n{tree}"
        if summaries:
            output += f"\n\n## 关键文件内容\n{summaries}"

        # Inject into context for follow-up questions
        self.context.metadata["_project_context"] = output[:8000]
        self.context.metadata["_project_context_path"] = str(target_path)

        return {"success": True, "output": output[:4000]}

    async def _exec_memorize(self, action, session_id: str) -> dict:
        """执行记忆操作"""
        import json as _json
        if not self.unified_store:
            return {"success": False, "output": "知识系统未初始化"}
        try:
            parsed = _json.loads(action.params)
        except Exception:
            parsed = {"op": "add", "content": action.params}

        op = parsed.get("op", "add")
        log_activity(session_id, "memorize_op", op=op, parsed=parsed)

        if op == "list":
            entries = self.unified_store._catalog
            if not entries:
                return {"success": True, "output": "当前没有已记录的知识。"}
            lines = [f"- {e['preview']}" for e in entries[:15]]
            return {"success": True, "output": f"已记录 {len(entries)} 条知识：\n" + "\n".join(lines)}

        elif op == "delete":
            keyword = parsed.get("keyword", parsed.get("key", ""))
            for e in list(self.unified_store._catalog):
                if keyword and keyword in e["preview"]:
                    path = self.unified_store.entries_dir / f"{e['id']}.json"
                    if path.exists():
                        path.unlink()
                    self.unified_store._catalog.remove(e)
                    self.unified_store._save_catalog()
                    self.unified_store._invalidate_compiled()
                    return {"success": True, "output": f"已删除包含「{keyword}」的知识。"}
            return {"success": False, "output": f"未找到包含「{keyword}」的知识。"}

        else:
            content = parsed.get("content", parsed.get("value", action.params))
            if isinstance(content, dict):
                content = str(content)
            category = parsed.get("category", "insight")
            domain = parsed.get("domain", "general")
            self.unified_store.add(
                content=content, source="user", maturity="pattern",
                scope="project", category=category, domain=domain,
                session_id=session_id)
            return {"success": True, "output": f"已记住：{content}"}

    async def _exec_use_tool(self, action) -> dict:
        """执行外部工具调用（通过 ConnectorRegistry 路由）"""
        result = await self._get_connector_registry().invoke(action.name, action.params)
        # 如果 connector 找不到，提供内置工具建议
        if not result.get("success") and ("不存在" in result.get("output", "") or "not found" in result.get("output", "").lower()):
            BUILTIN_HINTS = {
                "read_lines": "读取文件指定行，格式：```read_lines\\n文件路径\\n行号范围```",
                "search_in_file": "搜索文件内容，格式：```search_in_file\\n文件路径\\n关键词```",
                "edit_file": "编辑文件，格式：```edit_file\\npath: 文件路径\\n<<<<<<< OLD\\n原文\\n=======\\n新文\\n>>>>>>> NEW```",
                "shell": "执行命令，格式：```shell\\n命令```",
                "read_dir": "读取目录，格式：```read_dir\\n目录路径```",
                "read_file": "读取文件，格式：```read_file\\n文件路径```",
                "write_file": "写入文件，格式：```write_file\\n{\"path\":\"...\",\"content\":\"...\"}```",
            }
            tool_name = action.name.split(".")[-1] if action.name else ""
            if tool_name in BUILTIN_HINTS:
                result["output"] += f"\n\n💡 '{tool_name}' 是内置操作，请直接使用：{BUILTIN_HINTS[tool_name]}"
        return result
