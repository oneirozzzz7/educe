"""
Evolution Mixin — 从 orchestrator.py 抽取。
"""
from __future__ import annotations

import logging

log = logging.getLogger("educe.orchestrator")


class EvolutionMixin:
    """Evolution methods for Orchestrator."""

    async def _evolve_one_step(self, current_question: str):
        """懒评估——每5次交互评估1个问题，用pairwise比较（1次LLM调用）"""
        if not self.self_evolver or not self.self_evolver.evolving:
            return
        try:
            client = self._get_client()
            if not client:
                return
            from educe.core.activation_engine import ACTIVATION_PROMPT

            q = current_question
            model = self.config.default_model.model
            max_tokens = self.config.default_model.max_tokens
            sys_cur = ACTIVATION_PROMPT.format(activation_seed=self.self_evolver.current_best, extra_context="")
            sys_cand = ACTIVATION_PROMPT.format(activation_seed=self.self_evolver._candidate, extra_context="")

            resp_cur = await asyncio.wait_for(client.chat(
                messages=[{"role": "system", "content": sys_cur},
                          {"role": "user", "content": q}],
                model=model, max_tokens=max_tokens), timeout=30)
            resp_cand = await asyncio.wait_for(client.chat(
                messages=[{"role": "system", "content": sys_cand},
                          {"role": "user", "content": q}],
                model=model, max_tokens=max_tokens), timeout=30)

            judge_result = await asyncio.wait_for(client.chat(
                messages=[
                    {"role": "system", "content": "比较两个回答，哪个对用户更有帮助？只回复A或B。"},
                    {"role": "user", "content": "问题：{}\n\n回答A：{}\n\n回答B：{}".format(
                        q, resp_cur[:300], resp_cand[:300])},
                ],
                model=model, max_tokens=5, temperature=0.0), timeout=15)

            choice = "A" if "A" in judge_result.strip()[:3] else "B"
            import random
            if random.random() > 0.5:
                winner = "current" if choice == "A" else "candidate"
            else:
                winner = "candidate" if choice == "A" else "current"

            self.self_evolver._ab_results.append({
                "question": q[:50], "winner": winner,
            })
            console.print("[dim]  self-evolver: eval {}/{} -> {}[/dim]".format(
                len(self.self_evolver._ab_results), 10, winner))
        except Exception as e:
            console.print("[dim]  self-evolver step error: {}[/dim]".format(str(e)[:60]))

    async def _run_self_evolution(self):
        """后台完整进化循环：生成候选→回放历史问题→judge比较→finalize"""
        if not self.self_evolver:
            return
        try:
            await self.self_evolver.generate_candidate()
            if not self.self_evolver.evolving:
                return

            client = self._get_client()
            if not client:
                return

            from educe.core.activation_engine import ACTIVATION_PROMPT
            from educe.core.checklist_judge import evaluate

            questions = self._get_recent_questions(n=10)
            if len(questions) < 5:
                questions = [
                    "什么是人工智能", "TCP三次握手的过程",
                    "红烧肉怎么做", "光速为什么不能被超越",
                    "工作三年感觉迷茫怎么办",
                ]

            current_seed = self.self_evolver.current_best
            candidate_seed = self.self_evolver._candidate
            model = self.config.default_model.model
            max_tokens = self.config.default_model.max_tokens

            sys_current = ACTIVATION_PROMPT.format(activation_seed=current_seed, extra_context="")
            sys_candidate = ACTIVATION_PROMPT.format(activation_seed=candidate_seed, extra_context="")

            for q in questions:
                try:
                    resp_cur = await asyncio.wait_for(client.chat(
                        messages=[{"role": "system", "content": sys_current},
                                  {"role": "user", "content": q}],
                        model=model, max_tokens=max_tokens), timeout=30)
                    resp_cand = await asyncio.wait_for(client.chat(
                        messages=[{"role": "system", "content": sys_candidate},
                                  {"role": "user", "content": q}],
                        model=model, max_tokens=max_tokens), timeout=30)

                    eval_cur = await asyncio.wait_for(
                        evaluate(client, model, q, resp_cur), timeout=30)
                    eval_cand = await asyncio.wait_for(
                        evaluate(client, model, q, resp_cand), timeout=30)

                    winner = "candidate" if eval_cand.coverage > eval_cur.coverage else "current" if eval_cur.coverage > eval_cand.coverage else "tie"
                    self.self_evolver._ab_results.append({
                        "question": q[:50],
                        "current_score": eval_cur.coverage,
                        "candidate_score": eval_cand.coverage,
                        "winner": winner,
                    })
                    console.print("[dim]  self-evolver: evaluated '{}' -> {}[/dim]".format(q[:20], winner))
                except Exception as e:
                    console.print("[dim]  self-evolver eval error: {}[/dim]".format(str(e)[:60]))

            if self.self_evolver.ab_complete():
                result = self.self_evolver.finalize()
                if result.get("result") == "evolved" and self.activation_engine:
                    self.activation_engine._current_seed = self.self_evolver.current_best
                console.print("[dim]  self-evolver: cycle complete - {}[/dim]".format(
                    result.get("result", "?")))
        except Exception as e:
            console.print("[red]  self-evolver error: {}[/red]".format(str(e)[:100]))

    def _get_recent_questions(self, n: int = 10) -> list:
        questions = []
        for turn in reversed(self.conversation.turns):
            if turn.role == "user" and len(turn.content) > 5:
                questions.append(turn.content)
                if len(questions) >= n:
                    break
        return questions

    async def _evolve_from_result(self):
        """后台静默进化——用户无感知"""
        try:
            from educe.core.evolution import evolve_from_output
            engineer_output = self.context.artifacts.get("engineer_output", "")
            user_request = self.context.user_request
            if engineer_output:
                evolve_from_output(engineer_output, user_request, self.knowledge)
        except Exception as e:
            log.debug("evolution from result failed: %s", e)

    def _feedback_success(self):
        """有质量门控的反馈——只对非负向信号的回答标记成功"""
        if not self.knowledge:
            return

        signal = self.context.metadata.get("_last_user_signal", "unknown")
        if signal in ("error", "unsatisfied"):
            return

        recalled_ids = getattr(self.knowledge, '_last_recalled_ids', [])
        for eid in recalled_ids:
            self.knowledge.record_success(eid)
            if eid in self.knowledge._entries:
                self.knowledge._entries[eid].usage_count += 1
        if recalled_ids:
            self.knowledge._compile_l1()

        if self.knowledge.stats()["total"] > 500:
            self.knowledge.prune(max_entries=400)

    async def _audit(self, question: str, response: str) -> str:
        """反幻觉审计——标注不可靠内容"""
        try:
            from educe.core.hallucination_guard import audit_response
            client = self._get_client()
            if not client:
                return response
            return await audit_response(
                question, response, client,
                model=self.config.default_model.model,
                max_tokens=self.config.default_model.max_tokens,
                mode=self.config.hallucination_guard.mode,
            )
        except Exception:
            return response

    def _is_text_task(self, user_input: str) -> bool:
        """只有明确要做工具/网页/游戏才走code，其他全部走text"""
        import re
        code_patterns = self._get_knowledge_signals().get("code_intent_patterns", [])
        code_score = 0
        for group in code_patterns:
            pattern = "|".join(re.escape(k) for k in group)
            if re.search(pattern, user_input):
                code_score += 1
        return code_score == 0

    async def _direct_reply(self, user_input: str, file_hint: str = "") -> dict:
        """用激发引擎构建prompt——带对话历史和上下文信号"""
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        # 延迟初始化SelfEvolver（需要client可用）
        if not self.self_evolver and client:
            try:
                from educe.core.self_evolver import SelfEvolver
                from educe.core.activation_engine import DEFAULT_ACTIVATION_SEED
                self.self_evolver = SelfEvolver(
                    client, self.config.default_model.model, DEFAULT_ACTIVATION_SEED)
            except Exception as e:
                log.debug("SelfEvolver init skipped: %s", e)

        file_context = self.context.metadata.get("uploaded_files_text", "")

        domain_context = self.context.metadata.get("domain_knowledge", "")
        l1 = []
        if self.unified_store:
            l1 = self.unified_store.get_l1_compiled()
        elif self.knowledge:
            l1 = self.knowledge.get_l1_compiled()

        recalled = []
        if self.distiller:
            detected_domain = self._detect_domain(user_input, "")
            recalled = self.distiller.recall_for_domain(user_input, detected_domain, max_results=3)
        elif self.knowledge:
            recalled = self.knowledge.recall(user_input, max_results=5)

        all_knowledge = []
        for k in recalled:
            if k in all_knowledge:
                continue
            if not k.startswith("["):
                continue
            if k.startswith("[成功]") or k.startswith("[seed") or k.startswith("[失败]"):
                continue
            all_knowledge.append(k[:120])
        all_knowledge = all_knowledge[:3]

        # 上下文信号注入
        ctx_hint = ""
        ctx_signals = self.context.metadata.get("_context_signals")
        if ctx_signals and self.context_analyzer:
            ctx_hint = self.context_analyzer.build_context_hint(ctx_signals)

        # 用户画像注入
        profile_hint = ""
        session_id = self.context.metadata.get("session_id", "")
        if self.profile_manager and session_id:
            profile = self.profile_manager.get_or_create(session_id)
            profile_hint = profile.get_activation_hint()

        if self.activation_engine:
            cs = getattr(self, 'cognitive_state', None)
            if cs and cs.best_seed:
                self.activation_engine._current_seed = cs.best_seed
            system = self.activation_engine.build_activation_prompt(
                user_input=user_input,
                domain_context=domain_context + ctx_hint + profile_hint,
                l1_compiled=all_knowledge[:8] if all_knowledge else None,
            )
        else:
            system = "你是一位专业的AI助手，请准确回答用户的问题。"

        history = self.conversation.get_history_for_llm()
        # 截断过长的assistant回复（代码输出等），保留最近对话
        cleaned = []
        for h in history:
            content = h.get("content", "")
            if len(content) > 1500:
                cleaned.append({"role": h["role"], "content": content[:300] + "\n...(内容过长已截断)"})
            else:
                cleaned.append(h)
        history = cleaned[-6:]
        user_content = user_input + ("\n{}".format(file_hint) if file_hint else "") + ("\n{}".format(file_context) if file_context else "")

        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        try:
            # Streaming输出——用户实时看到回答生成
            raw = ""
            try:
                async def _stream_collect():
                    nonlocal raw
                    async for chunk in client.chat_stream(
                        messages=messages,
                        model=self.config.default_model.model,
                        max_tokens=self.config.default_model.max_tokens,
                    ):
                        raw += chunk
                        self._notify_chunk("assistant", chunk)
                await asyncio.wait_for(_stream_collect(), timeout=120)
            except (asyncio.TimeoutError, Exception):
                if not raw:
                    raw = await asyncio.wait_for(client.chat(
                        messages=messages,
                        model=self.config.default_model.model,
                        max_tokens=self.config.default_model.max_tokens,
                    ), timeout=120)

            # ResponseValidator：通用语义验证
            from educe.core.response_validator import should_validate, validate_response, build_retry_prompt
            if should_validate(user_input, raw, self.conversation.turns):
                vr = await validate_response(
                    client, self.config.default_model.model,
                    user_input, raw)
                self.context.metadata["_validation_result"] = vr
                if not vr["relevant"]:
                    retry_prompt = build_retry_prompt(
                        user_input, vr, self.conversation.turns)
                    messages[-1] = {"role": "user", "content": retry_prompt}
                    raw = await client.chat(
                        messages=messages,
                        model=self.config.default_model.model,
                        max_tokens=self.config.default_model.max_tokens,
                    )
                    console.print("[dim]  validator: off-topic detected, regenerated[/dim]")

            domain_tag = ""
            if self.activation_engine:
                activated = self.activation_engine.parse_activated_response(raw)

                # 领域识别：从回答+问题综合判断
                domain_tag = activated.domain or ""
                if not domain_tag or domain_tag == "通用":
                    domain_tag = self._detect_domain(user_input, raw)

                self.context.metadata["expert_name"] = domain_tag
                self.context.metadata["activation_confidence"] = activated.overall_confidence
                console.print("[dim]  {} | {}: {}[/dim]".format(
                    domain_tag, "confidence", activated.overall_confidence))

                # 精准知识蒸馏（替代Phase 0被禁用的旧策略）
                user_signal = self.context.metadata.get("_last_user_signal", "neutral")
                if self.distiller and raw and len(raw) > 100:
                    distilled = self.distiller.distill(user_input, raw, domain_tag, user_signal)
                    if distilled:
                        console.print("[dim]  distilled {} facts[/dim]".format(len(distilled)))

                signal_weight = self.context.metadata.get("_last_signal_weight", 0.0)
                vr = self.context.metadata.get("_validation_result", {})
                relevance = 1.0 if vr.get("relevant", True) else 0.3
                self.quality_tracker.record(
                    question=user_input, domain=domain_tag,
                    seed=self.activation_engine._current_seed[:60],
                    response=raw, user_signal=user_signal,
                    signal_weight=signal_weight,
                    model=self.config.default_model.model,
                    relevance=relevance,
                )

                # 异步checklist评估（不阻塞响应）
                async def _bg_judge():
                    try:
                        from educe.core.checklist_judge import evaluate
                        result = await evaluate(client, self.config.default_model.model, user_input, raw)
                        self.context.metadata["_judge_score"] = result.to_dict()
                    except Exception as e:
                        log.debug("bg judge evaluation failed: %s", e)
                asyncio.create_task(_bg_judge())

                # 每20次回答触发一次evolver演化
                if hasattr(self.activation_engine, '_evolver') and self.activation_engine._evolver:
                    self.activation_engine._use_count += 1
                    if self.activation_engine._use_count % 20 == 0:
                        try:
                            result = self.activation_engine._evolver.analyze_and_evolve()
                            if result.get("status") == "evolved":
                                console.print("[dim]Evolution gen {} - {} domains optimized[/dim]".format(
                                    result["generation"], result["domains_optimized"]))
                        except Exception as e:
                            log.debug("evolver cycle failed: %s", e)

                # (SelfEvolver已移至run()入口统一处理)
            else:
                self.context.metadata["expert_name"] = "Educe"

            self.context.artifacts["last_text_domain"] = domain_tag
            self.conversation.add_assistant(raw, domain=domain_tag)
            if hasattr(self, 'state'):
                self.state.add_ai_reply(raw)

            # 四信号融合可信度评估
            if self.credibility:
                cred = self.credibility.assess(
                    user_input, raw, domain_tag,
                    user_signal=self.context.metadata.get("_last_user_signal", "neutral"))
                self.context.metadata["credibility"] = cred
                self.context.metadata["activation_confidence"] = cred["level"]

            # 记录到用户画像
            if self.profile_manager and session_id:
                profile = self.profile_manager.get_or_create(session_id)
                profile.record_turn(user_input, domain_tag, is_code=False,
                                   signal=self.context.metadata.get("_last_user_signal", "neutral"))

            return {"action": "reply", "content": raw}
        except Exception as e:
            return {"action": "reply", "content": f"出错了: {e}"}

