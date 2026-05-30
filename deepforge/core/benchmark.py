"""
DeepForge Benchmark 期望列表（金标准）
人工定义每题"用户真正关心什么"，作为评估的最终校准。

原则：
- 期望是"用户真正关心的"，不是"技术上应该有的"
- 每个期望可客观验证（提到了/没提到）
- 分为必须期望（invariant）和加分期望（bonus）
- 反期望（anti）：好回答不应该有的内容
"""

BENCHMARK_EXPECTATIONS = [
    {
        "question": "孩子发烧38.5度应该怎么处理",
        "domain": "medical",
        "invariant": [
            "给出具体的物理降温方法（擦浴/冰敷/通风等）",
            "说明什么情况下必须立即就医（体温阈值或伴随症状）",
            "提醒观察孩子的精神状态",
        ],
        "bonus": [
            "提到退烧药的使用建议和注意事项",
            "提醒不要用酒精擦浴",
        ],
        "anti": [
            "给出具体药物剂量处方",
            "说'没事不用担心'",
        ],
    },
    {
        "question": "长期失眠有什么科学的改善方法",
        "domain": "medical",
        "invariant": [
            "提到睡眠卫生习惯（固定作息/环境调整等）",
            "提到认知行为或放松技术",
            "区分偶尔失眠和需要就医的慢性失眠",
        ],
        "bonus": [
            "提到运动对睡眠的影响",
            "提到褪黑素等辅助手段的利弊",
        ],
        "anti": [
            "推荐安眠药作为首选方案",
        ],
    },
    {
        "question": "劳动合同到期公司不续签需要赔偿吗",
        "domain": "legal",
        "invariant": [
            "明确回答'需要赔偿'（经济补偿金）",
            "说明补偿标准（N或N+1，按工作年限）",
            "提到劳动合同法的相关条款",
        ],
        "bonus": [
            "区分公司不续签和员工不续签的不同",
            "提到仲裁时效",
        ],
        "anti": [
            "说'不需要赔偿'",
        ],
    },
    {
        "question": "租房合同没到期房东要求搬走怎么办",
        "domain": "legal",
        "invariant": [
            "明确告知'房东单方面要求搬走属于违约'",
            "说明租户有权要求违约赔偿",
            "建议保留合同和沟通记录作为证据",
        ],
        "bonus": [
            "提到可以向住建部门投诉或走法律途径",
            "区分房东自住需求和无理驱赶的不同处理",
        ],
        "anti": [],
    },
    {
        "question": "证明：任意正整数n，n(n+1)能被2整除",
        "domain": "math",
        "invariant": [
            "给出完整的数学证明过程",
            "利用'连续整数必有一个偶数'这个核心性质",
            "结论明确：n(n+1)一定是偶数",
        ],
        "bonus": [
            "给出分情况讨论（n为奇数/偶数）",
            "用数学归纳法作为备选证明",
        ],
        "anti": [
            "只举例不证明",
        ],
    },
    {
        "question": "一个袋子3红球5蓝球，不放回取2个，两个都是红球的概率",
        "domain": "math",
        "invariant": [
            "计算过程正确（组合数或条件概率）",
            "最终答案正确（3/28）",
            "展示推导步骤",
        ],
        "bonus": [
            "用两种方法验证（组合数法+条件概率法）",
        ],
        "anti": [
            "答案错误",
            "只给答案不给过程",
        ],
    },
    {
        "question": "TCP三次握手的过程，第三次丢失会怎样",
        "domain": "tech",
        "invariant": [
            "正确描述三次握手的SYN/SYN-ACK/ACK序列",
            "说明第三次ACK丢失后服务端的状态（SYN_RCVD）",
            "说明服务端会重传SYN-ACK",
        ],
        "bonus": [
            "说明客户端此时认为连接已建立",
            "提到超时机制和重传次数限制",
        ],
        "anti": [
            "把三次握手描述错误",
        ],
    },
    {
        "question": "Redis和Memcached在高并发场景下各自优缺点",
        "domain": "tech",
        "invariant": [
            "列出Redis的核心优势（数据结构丰富/持久化/主从复制）",
            "列出Memcached的核心优势（多线程/内存效率/简单稳定）",
            "给出选择建议（什么场景用哪个）",
        ],
        "bonus": [
            "提到性能对比数据",
            "提到集群方案的差异",
        ],
        "anti": [],
    },
    {
        "question": "光速为什么不能被超越",
        "domain": "science",
        "invariant": [
            "提到狭义相对论",
            "解释接近光速时质量/能量趋于无穷",
            "说明光速是时空结构的基本常数",
        ],
        "bonus": [
            "提到因果律（超光速会导致因果悖论）",
            "用通俗类比帮助理解",
        ],
        "anti": [],
    },
    {
        "question": "mRNA疫苗和传统灭活疫苗的本质区别",
        "domain": "science",
        "invariant": [
            "解释mRNA疫苗的工作原理（让细胞自己产生抗原蛋白）",
            "解释灭活疫苗的工作原理（直接注入灭活的病原体）",
            "对比两者的核心差异（信息vs实体）",
        ],
        "bonus": [
            "提到各自的优劣（研发速度/存储条件/免疫持久性）",
            "举具体疫苗的例子",
        ],
        "anti": [
            "对mRNA疫苗安全性做出未经证实的负面评价",
        ],
    },
    {
        "question": "安史之乱为什么是唐朝由盛转衰的转折点",
        "domain": "history",
        "invariant": [
            "说明安史之乱对中央集权的破坏（藩镇割据）",
            "说明对经济的破坏（人口锐减/农业受损）",
            "把安史之乱放在唐朝整体历史脉络中分析",
        ],
        "bonus": [
            "提到对唐朝军事体制的影响",
            "提到安史之乱的起因",
        ],
        "anti": [],
    },
    {
        "question": "秦始皇统一六国的关键因素有哪些",
        "domain": "history",
        "invariant": [
            "提到秦国的制度优势（商鞅变法/法治/军功爵制）",
            "提到军事和外交策略（远交近攻）",
            "提到经济基础（关中平原/都江堰/郑国渠）",
        ],
        "bonus": [
            "提到六国自身的弱点",
            "提到秦始皇个人的作用",
        ],
        "anti": [],
    },
    {
        "question": "工作三年感觉没成长很迷茫该怎么办",
        "domain": "psychology",
        "invariant": [
            "肯定这种感受是正常的（情感认同）",
            "帮助分析迷茫的可能原因",
            "给出具体可执行的建议（不是空话）",
        ],
        "bonus": [
            "建议做职业规划或技能盘点",
            "建议和行业前辈交流",
        ],
        "anti": [
            "否定用户的感受（'不要想太多'）",
        ],
    },
    {
        "question": "考试前极度焦虑怎么缓解",
        "domain": "psychology",
        "invariant": [
            "给出立即可用的放松技术（深呼吸/冥想/肌肉放松）",
            "分析焦虑的认知根源",
            "给出考前准备的实用建议",
        ],
        "bonus": [
            "区分正常焦虑和需要专业帮助的焦虑",
            "提到适度焦虑有助于发挥",
        ],
        "anti": [],
    },
    {
        "question": "红烧肉怎么做才能肥而不腻入口即化",
        "domain": "cooking",
        "invariant": [
            "说明选五花肉及处理方法（焯水去腥）",
            "说明炒糖色的方法",
            "强调小火慢炖的重要性和时间",
        ],
        "bonus": [
            "说明调料配比",
            "说明收汁技巧",
        ],
        "anti": [],
    },
    {
        "question": "糖醋排骨的正宗做法和关键步骤",
        "domain": "cooking",
        "invariant": [
            "给出完整的步骤流程",
            "说明糖醋汁的配比",
            "说明排骨的预处理（焯水/腌制）",
        ],
        "bonus": [
            "说明炸/煎排骨的火候",
            "说明挂汁的关键时机",
        ],
        "anti": [],
    },
    {
        "question": "月收入1万，存款20万，如何规划养老投资",
        "domain": "finance",
        "invariant": [
            "建议先留应急备用金",
            "给出资产配置建议（稳健+增长的比例）",
            "考虑到长期投资和复利效应",
        ],
        "bonus": [
            "提到保险保障的重要性",
            "给出具体产品类型建议（基金/国债/养老保险）",
        ],
        "anti": [
            "推荐具体股票代码",
            "保证收益率",
        ],
    },
    {
        "question": "什么是可转债，什么情况下适合转股",
        "domain": "finance",
        "invariant": [
            "解释可转债的定义（可转换为股票的债券）",
            "说明转股的时机条件（正股价>转股价）",
            "说明可转债的双重属性（债性+股性）",
        ],
        "bonus": [
            "举具体例子说明转股价值计算",
            "提到强赎条款",
        ],
        "anti": [],
    },
    {
        "question": "高考数学怎么从100分提到130分",
        "domain": "education",
        "invariant": [
            "分析100分水平的薄弱环节在哪",
            "给出针对性的提分策略（不是泛泛的'多做题'）",
            "有具体的时间规划或阶段目标",
        ],
        "bonus": [
            "按题型给出不同策略",
            "推荐具体的学习方法或资源",
        ],
        "anti": [],
    },
    {
        "question": "如何用费曼技巧学习复杂概念",
        "domain": "education",
        "invariant": [
            "解释费曼技巧的核心步骤",
            "说明'用简单语言教别人'这个关键环节",
            "说明如何发现自己理解的盲区",
        ],
        "bonus": [
            "举具体例子示范",
            "说明费曼技巧适用和不适用的场景",
        ],
        "anti": [],
    },
]


VERIFY_SYSTEM = (
    "检查回答是否满足以下要求。逐条判断，每条回复Y（满足）或N（未满足）。"
    "格式：1.Y 2.N 3.Y ..."
)

ANTI_VERIFY_SYSTEM = (
    "检查回答是否包含以下不应该出现的内容。逐条判断，每条回复Y（出现了）或N（没出现）。"
    "格式：1.Y 2.N ..."
)


async def evaluate_with_expectations(client, model: str, question: str,
                                      response: str, expectations: dict) -> dict:
    import re

    invariant = expectations.get("invariant", [])
    bonus = expectations.get("bonus", [])
    anti = expectations.get("anti", [])

    async def check_list(items, system_prompt):
        if not items:
            return []
        numbered = "\n".join("{}. {}".format(i+1, item) for i, item in enumerate(items))
        try:
            raw = await client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "要求：\n{}\n\n回答：\n{}".format(
                        numbered, response[:500])},
                ],
                model=model, max_tokens=50, temperature=0.0)
            results = []
            for i in range(len(items)):
                pattern = r'{}[.、):\s]*[Yy]'.format(i + 1)
                results.append(bool(re.search(pattern, raw)))
            return results
        except Exception:
            return [False] * len(items)

    inv_results = await check_list(invariant, VERIFY_SYSTEM)
    bonus_results = await check_list(bonus, VERIFY_SYSTEM)
    anti_results = await check_list(anti, ANTI_VERIFY_SYSTEM)

    inv_score = sum(inv_results) / len(inv_results) if inv_results else 1.0
    bonus_score = sum(bonus_results) / len(bonus_results) if bonus_results else 0.0
    anti_violations = sum(anti_results)

    return {
        "invariant_score": round(inv_score, 3),
        "bonus_score": round(bonus_score, 3),
        "anti_violations": anti_violations,
        "invariant_details": list(zip([i[:40] for i in invariant], inv_results)),
        "bonus_details": list(zip([b[:40] for b in bonus], bonus_results)),
        "anti_details": list(zip([a[:40] for a in anti], anti_results)) if anti else [],
    }


def find_expectations(question: str) -> dict:
    for b in BENCHMARK_EXPECTATIONS:
        if b["question"] == question:
            return b
    return {"invariant": [], "bonus": [], "anti": []}
