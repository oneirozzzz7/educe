from __future__ import annotations

"""
AI质检归因 Skill模板

基于"自进化归因"项目沉淀的最佳实践，将多Agent协作应用于
智能客服会话质检归因场景。

核心改进（vs 单Agent大Prompt模式）：
1. 拆成多个Agent，每步职责单一，弱模型也能胜任
2. 内置质量自检和迭代修正机制
3. 群像用户从业务视角评审归因结果
"""

SKILL_CONFIG = {
    "name": "customer_service_attribution",
    "description": "智能客服会话质检归因分析：多Agent协作定位转人工根因",
    "version": "1.0.0",
    "tags": ["customer_service", "attribution", "quality", "analysis"],
    "pipeline": [
        "project_manager",
        "product_manager",
        "architect",
        "engineer",
        "reviewer",
        "crowd_user",
        "memory_keeper",
    ],
}

ATTRIBUTION_ROOT_CAUSES = """
一级根因: 客户不信任机器
  - 机器开场答错: 开场答案错误，用户进线后直接要求人工
  - 用户高预期/厌机: 开场答案正确，用户进线后直接要求人工

一级根因: 机器不理解用户
  - 模糊意图未澄清: 用户表达模糊，Agent直接猜测并给错误方案
  - 意图切片agent未覆盖: 机器未识别到正确意图
  - 意图识别不准: 用户问法在agent中但被识别错误
  - 复合意图未全部识别: 用户含多个关键意图，Agent只处理一个
  - 上下文记忆缺失: 用户已提供的信息，Agent后续又追问

一级根因: 用户不接受方案
  - 用户不理解规则: 用户质疑规则类方案
  - 方案不接受: 用户明确不接受方案或要求其他方案
  - 要求增加方案额度: 接受方案但要求增加额度
  - 用户耐心不足: 反复催促后转人工

一级根因: 方案无法解决客户问题
  - 方案本身不合适: 方案明显无法解决该场景问题
  - 智能缺能力: 智能能力缺失暂无法执行
  - 智能缺权限: 机器有能力但业务未授权
  - 外部依赖失败: 商家/骑手原因导致方案执行失败

一级根因: 机器交互流程问题
  - 工具执行异常: 方案执行失败
  - 步骤/顺序不合理: 步骤复杂导致客户放弃

一级根因: 机器话术问题
  - 话术生硬: 话术机械不拟人
  - 共情能力差: 情绪波动时未有效安抚
""".strip()


AGENT_PROMPTS = {
    "intent_analyst": """你是意图分析专家。你的任务是逐条分析会话消息，识别：
1. 用户的每一次意图表达（包括隐含意图）
2. 意图切换节点（用户话题改变的时刻）
3. 机器人对意图的响应是否正确

输出格式：
```json
{{
  "intents": [
    {{
      "event_seq": 消息序号,
      "user_intent": "用户在这条消息中的意图",
      "bot_response_correct": true/false,
      "mismatch_reason": "如果不正确，说明原因"
    }}
  ],
  "intent_switches": [消息序号列表],
  "overall_understanding_score": 1-10
}}
```""",

    "problem_locator": """你是问题定位专家。基于意图分析结果，你的任务是：
1. 逐条检查所有机器人/非机器人应答消息
2. 标注有问题的消息（答非所问、重复回答、话术生硬、工具执行失败等）
3. 严格遵循双条件判定：
   - 条件A：消息客观上存在问题（错误、遗漏、不当等）
   - 条件B：该问题实质性阻碍了用户问题的解决
   两个条件必须同时满足才标注

禁止标注清单（以下情况不算有问题）：
- 标准欢迎语/结束语
- 合理的安抚话术
- 按规则/SOP正确回复但用户不满意
- 信息收集类追问

输出格式：
```json
{{
  "flagged_messages": [
    {{
      "event_seq": 消息序号,
      "role": "角色",
      "content_preview": "内容前30字",
      "condition_a": "客观问题描述",
      "condition_b": "如何阻碍了解决",
      "severity": "high/medium/low"
    }}
  ],
  "clean_messages_count": 无问题的消息数
}}
```""",

    "root_cause_analyst": """你是根因归因专家。基于问题定位结果，你的任务是：
1. 为每条有问题的消息分配根因（从根因体系中选择）
2. 为整通会话的转人工事件确定核心根因
3. 提供evidence（事实引用）和reasoning（逻辑推导）

根因体系：
{root_causes}

防止万金油归因的规则：
- "用户高预期/厌机"仅用于：开场就要转人工，且机器人首次回复内容正确
- "用户耐心不足"仅用于：用户重复催促3次以上，且每次机器人回复都有实质推进
- "智能缺权限"需要有明确证据表明机器人能力具备但未授权

输出格式：
```json
{{
  "session_attribution": {{
    "transfer_reason": "转人工核心原因",
    "l1": "一级根因",
    "l2": "二级根因",
    "evidence": "支撑归因的事实引用（引用具体消息内容）",
    "reasoning": "逻辑推导过程"
  }},
  "message_attributions": [
    {{
      "event_seq": 消息序号,
      "l1": "一级根因",
      "l2": "二级根因",
      "evidence": "事实引用",
      "reasoning": "推导"
    }}
  ]
}}
```""",

    "quality_checker": """你是归因质量审核专家。你的任务是检查归因结果的质量：

检查项：
1. **过度标注**: 是否把正常消息标注为有问题？（误报）
2. **万金油归因**: 某个二级根因占比>30%是异常信号
3. **证据缺失**: evidence是否引用了具体消息内容？空泛的不算
4. **逻辑自洽**: reasoning的推导是否合理？结论是否与evidence一致？
5. **遗漏检测**: 是否有明显的问题消息未被标注？（漏报）

输出格式：
```json
{{
  "quality_score": 1-10,
  "passed": true/false,
  "issues": [
    {{
      "type": "over_labeling/catch_all/missing_evidence/logic_error/missed_issue",
      "description": "具体描述",
      "affected_event_seq": [相关消息序号],
      "fix_suggestion": "修复建议"
    }}
  ],
  "distribution_check": {{
    "l2_distribution": {{"根因名": 占比}},
    "concentration_warning": "是否存在万金油归因"
  }}
}}
```""",
}


def get_attribution_prompt(agent_type: str, root_causes: str = ATTRIBUTION_ROOT_CAUSES) -> str:
    prompt = AGENT_PROMPTS.get(agent_type, "")
    return prompt.format(root_causes=root_causes) if "{root_causes}" in prompt else prompt
