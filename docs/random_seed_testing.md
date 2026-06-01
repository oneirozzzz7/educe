# 随机种子测试体系设计

## 核心思想

真实用户的行为有两个特征：
1. **不可预测**——你不知道用户下一步会做什么
2. **有模式**——用户不是完全随机的，有行为倾向（程序员更可能问技术问题）

随机种子测试要同时模拟这两点：用可控的随机性生成多样化行为，但行为模式符合真实用户分布。

## 三层随机架构

```
Layer 1: 用户人格生成（seed → 用户画像）
  ↓
Layer 2: 行为轨迹生成（画像 + seed → 操作序列）
  ↓  
Layer 3: 具体问题生成（操作类型 + seed → 自然语言问题）
```

每层的随机性独立控制，组合起来产生指数级的多样性。

---

## Layer 1: 用户人格生成

一个 seed 生成一个"虚拟用户"，这个用户有自己的行为倾向。

```python
class UserPersona:
    """一个seed确定一个用户人格——行为模式可预测但每个人不同"""
    
    # 用户类型分布（从创始人使用模式+常识推断）
    ARCHETYPES = {
        "explorer": {        # 探索者：什么都问，频繁切换话题
            "weight": 25,
            "topic_switch_rate": 0.7,    # 70%概率切换话题
            "code_rate": 0.2,            # 20%概率要做工具
            "follow_up_rate": 0.15,      # 15%概率追问
            "avg_turns": 12,
            "patience": 0.3,             # 耐心低，回答不好就换话题
            "domains": "uniform",        # 各领域均匀分布
        },
        "builder": {         # 建造者：主要做工具/代码
            "weight": 20,
            "topic_switch_rate": 0.3,
            "code_rate": 0.5,
            "follow_up_rate": 0.3,       # 经常追问修改需求
            "avg_turns": 8,
            "patience": 0.6,
            "domains": ["tech", "tool"],
        },
        "learner": {         # 学习者：深入了解某个领域
            "weight": 20,
            "topic_switch_rate": 0.2,    # 很少切换话题
            "code_rate": 0.05,
            "follow_up_rate": 0.5,       # 大量追问
            "avg_turns": 15,
            "patience": 0.7,
            "domains": ["science", "tech", "history", "education"],
        },
        "helper": {          # 求助者：有具体问题要解决
            "weight": 20,
            "topic_switch_rate": 0.4,
            "code_rate": 0.15,
            "follow_up_rate": 0.2,
            "avg_turns": 6,
            "patience": 0.4,
            "domains": ["medical", "legal", "finance", "life"],
        },
        "chatter": {         # 闲聊者：随便聊聊
            "weight": 15,
            "topic_switch_rate": 0.6,
            "code_rate": 0.05,
            "follow_up_rate": 0.1,
            "avg_turns": 10,
            "patience": 0.5,
            "domains": "uniform",
        },
    }
    
    def __init__(self, seed: int):
        rng = random.Random(seed)
        
        # 根据权重选择原型
        archetypes = list(self.ARCHETYPES.keys())
        weights = [self.ARCHETYPES[a]["weight"] for a in archetypes]
        self.archetype = rng.choices(archetypes, weights=weights)[0]
        
        profile = self.ARCHETYPES[self.archetype]
        
        # 在原型基础上加个体差异（±20%随机扰动）
        self.topic_switch_rate = self._perturb(rng, profile["topic_switch_rate"], 0.2)
        self.code_rate = self._perturb(rng, profile["code_rate"], 0.2)
        self.follow_up_rate = self._perturb(rng, profile["follow_up_rate"], 0.2)
        self.avg_turns = int(self._perturb(rng, profile["avg_turns"], 0.3))
        self.patience = self._perturb(rng, profile["patience"], 0.15)
        self.domains = profile["domains"]
        
        # 个性化表达风格
        self.style = rng.choice(["formal", "casual", "terse", "verbose", "mixed"])
        self.uses_emoji = rng.random() < 0.3
        self.makes_typos = rng.random() < 0.15
    
    def _perturb(self, rng, value, range_pct):
        delta = value * range_pct
        return max(0.01, min(0.99, value + rng.uniform(-delta, delta)))
```

---

## Layer 2: 行为轨迹生成

给定一个 UserPersona，生成一连串操作（不是具体问题，是操作类型）。

```python
class TrajectoryGenerator:
    """生成行为轨迹——每个决策点都由persona的概率分布决定"""
    
    # 操作类型
    ACTIONS = [
        "chat",              # 闲聊/提问
        "deep_question",     # 深入问题
        "code_request",      # 要做工具/代码
        "code_modify",       # 修改上一轮的代码
        "file_upload",       # 上传文件
        "file_followup",     # 追问文件内容
        "follow_up",         # 追问上一轮
        "topic_switch",      # 完全切换话题
        "negative_feedback",  # 否定/纠错
        "positive_feedback",  # 感谢/肯定
        "ambiguous",         # 模糊/歧义输入
        "greeting",          # 打招呼
    ]
    
    def generate(self, persona: UserPersona, seed: int) -> list[dict]:
        rng = random.Random(seed)
        turns = persona.avg_turns + rng.randint(-3, 3)
        turns = max(3, min(20, turns))
        
        trajectory = []
        last_action = None
        last_was_code = False
        consecutive_same_topic = 0
        
        for i in range(turns):
            action = self._decide_action(
                rng, persona, last_action, last_was_code,
                consecutive_same_topic, i, turns
            )
            
            # 为每个action选择领域
            domain = self._select_domain(rng, persona, trajectory)
            
            trajectory.append({
                "turn": i + 1,
                "action": action,
                "domain": domain,
                "is_first_turn": i == 0,
                "is_last_turn": i == turns - 1,
            })
            
            # 更新状态
            if action == "topic_switch":
                consecutive_same_topic = 0
            else:
                consecutive_same_topic += 1
            last_was_code = action in ("code_request", "code_modify")
            last_action = action
        
        return trajectory
    
    def _decide_action(self, rng, persona, last_action, last_was_code, 
                        consecutive_same_topic, turn_idx, total_turns):
        """每个决策点的概率分布——不是均匀随机，是有条件的"""
        
        # 第一轮：只能是greeting/chat/code/deep_question
        if turn_idx == 0:
            return rng.choices(
                ["greeting", "chat", "code_request", "deep_question"],
                weights=[20, 40, 20, 20]
            )[0]
        
        # 最后一轮：倾向结束性操作
        if turn_idx == total_turns - 1:
            return rng.choices(
                ["positive_feedback", "chat", "topic_switch"],
                weights=[40, 30, 30]
            )[0]
        
        # 上一轮是代码 → 后续行为分布
        if last_was_code:
            return rng.choices(
                ["code_modify", "follow_up", "topic_switch", "chat", "positive_feedback", "negative_feedback"],
                weights=[25, 15, 30, 15, 10, 5]
            )[0]
        
        # 上一轮是否定 → 可能重新问或换话题
        if last_action == "negative_feedback":
            return rng.choices(
                ["follow_up", "topic_switch", "chat"],
                weights=[50, 35, 15]
            )[0]
        
        # 同一话题太久 → 换话题概率增加
        switch_boost = min(consecutive_same_topic * 0.1, 0.3)
        
        # 基于persona的概率
        base_weights = {
            "chat": 20,
            "deep_question": 15,
            "code_request": persona.code_rate * 100,
            "follow_up": persona.follow_up_rate * 100,
            "topic_switch": (persona.topic_switch_rate + switch_boost) * 100,
            "file_upload": 5,
            "negative_feedback": 3,
            "positive_feedback": 5,
            "ambiguous": 5,
        }
        
        actions = list(base_weights.keys())
        weights = list(base_weights.values())
        return rng.choices(actions, weights=weights)[0]
    
    def _select_domain(self, rng, persona, trajectory):
        """选领域——不是均匀随机，和persona的领域偏好相关"""
        ALL_DOMAINS = [
            "medical", "legal", "math", "tech", "finance",
            "writing", "psychology", "history", "science",
            "cooking", "education", "life", "pets", "fitness",
        ]
        
        if persona.domains == "uniform":
            return rng.choice(ALL_DOMAINS)
        else:
            # 80%概率从偏好领域选，20%随机
            if rng.random() < 0.8:
                return rng.choice(persona.domains)
            else:
                return rng.choice(ALL_DOMAINS)
```

---

## Layer 3: 具体问题生成

给定操作类型+领域+用户风格，生成自然语言问题。

```python
class QuestionGenerator:
    """生成具体的自然语言问题——多样但可复现"""
    
    # 每个领域的问题模板池
    TEMPLATES = {
        "medical": {
            "chat": [
                "头疼怎么办", "感冒了吃什么药", "孩子发烧{temp}度",
                "最近总是{symptom}", "体检报告{item}偏高",
                "{body_part}疼是什么原因",
            ],
            "deep_question": [
                "为什么{disease}会遗传", "{treatment}的原理是什么",
                "{medicine}的副作用有哪些", "免疫系统是怎么工作的",
            ],
            "vars": {
                "temp": ["37.5", "38.5", "39", "40"],
                "symptom": ["失眠", "头疼", "胃疼", "腰疼", "疲劳"],
                "item": ["血压", "血糖", "尿酸", "转氨酶", "胆固醇"],
                "body_part": ["肩膀", "膝盖", "手腕", "脖子", "后背"],
                "disease": ["糖尿病", "高血压", "近视", "过敏"],
                "treatment": ["针灸", "理疗", "化疗", "手术"],
                "medicine": ["布洛芬", "阿莫西林", "头孢", "板蓝根"],
            },
        },
        "tech": {
            "chat": [
                "Python和{lang}哪个好", "什么是{concept}",
                "{tool}怎么用", "学{tech}从哪开始",
            ],
            "code_request": [
                "做一个{app}", "帮我写个{script}",
                "做个{app}网页", "写一个{algorithm}",
            ],
            "code_modify": [
                "改成{color}色", "加个{feature}", "字体改大一点",
                "把{element}去掉", "加一个{ui_element}",
            ],
            "vars": {
                "lang": ["Java", "Go", "Rust", "C++", "JavaScript"],
                "concept": ["微服务", "Docker", "REST API", "WebSocket", "Redis"],
                "tool": ["Git", "Docker", "Nginx", "Webpack", "Vim"],
                "tech": ["React", "Vue", "Python", "机器学习", "数据库"],
                "app": ["番茄钟", "计算器", "待办清单", "天气查询", "密码生成器", "贪吃蛇", "坦克大战"],
                "script": ["爬虫", "数据清洗脚本", "批量改名工具", "日志分析脚本"],
                "algorithm": ["冒泡排序", "二分查找", "快速排序", "斐波那契"],
                "color": ["红", "蓝", "绿", "暗", "白"],
                "feature": ["搜索功能", "导出按钮", "深色模式", "音效"],
                "element": ["标题", "边框", "阴影", "动画"],
                "ui_element": ["返回按钮", "进度条", "提示框", "设置页面"],
            },
        },
        # ... 其他领域类似定义
    }
    
    # 通用模板（不分领域）
    GENERIC = {
        "greeting": ["你好", "嗨", "在吗", "hi", "你好呀"],
        "positive_feedback": ["谢谢", "太好了", "不错", "很有帮助", "学到了", "👍"],
        "negative_feedback": ["不对", "错了", "不是这样的", "你说的不准确", "重新回答"],
        "follow_up": [
            "继续说", "详细讲讲", "举个例子", "为什么", "还有呢",
            "这个{ref}是什么意思", "你说的{ref}能展开说说吗",
        ],
        "topic_switch": [
            "换个话题", "另外问个事", "对了", "忽然想到",
            # 直接问一个新领域的问题也是topic_switch
        ],
        "ambiguous": [
            "那个怎么弄", "帮我看看", "这个对吗", "有什么好的",
            "能不能搞一下", "你觉得呢",
        ],
    }
    
    def generate(self, action: str, domain: str, persona: UserPersona,
                 trajectory: list[dict], seed: int) -> str:
        rng = random.Random(seed)
        
        # 如果是通用操作（greeting/feedback/follow_up）
        if action in self.GENERIC:
            question = rng.choice(self.GENERIC[action])
            # follow_up需要引用上一轮的内容
            if action == "follow_up" and "{ref}" in question:
                # 从上一轮回答中提取一个关键词作为ref
                question = question.replace("{ref}", "那个")
            return self._apply_style(rng, question, persona)
        
        # 如果是topic_switch，从另一个随机领域生成问题
        if action == "topic_switch":
            other_domains = [d for d in self.TEMPLATES if d != domain]
            domain = rng.choice(other_domains) if other_domains else domain
            action = "chat"  # topic_switch本质是换领域的chat
        
        # 领域+操作类型 → 模板
        domain_templates = self.TEMPLATES.get(domain, {})
        action_templates = domain_templates.get(action, domain_templates.get("chat", ["问个{domain}的问题"]))
        
        template = rng.choice(action_templates)
        
        # 填充变量
        vars_pool = domain_templates.get("vars", {})
        question = template
        for var_name, var_values in vars_pool.items():
            placeholder = "{" + var_name + "}"
            if placeholder in question:
                question = question.replace(placeholder, rng.choice(var_values))
        
        question = question.replace("{domain}", domain)
        
        return self._apply_style(rng, question, persona)
    
    def _apply_style(self, rng, question, persona):
        """根据用户风格调整表达"""
        if persona.style == "terse":
            # 简短风格：去掉尾部的语气词
            question = question.rstrip("呢吗吧啊呀")
        elif persona.style == "verbose":
            # 啰嗦风格：加前缀
            prefixes = ["请问一下，", "我想问问，", "麻烦帮我看看，", "有个问题想请教，"]
            question = rng.choice(prefixes) + question
        elif persona.style == "casual":
            # 口语化：加语气词
            suffixes = ["呢", "啊", "呗", "吧", "嘛"]
            question = question + rng.choice(suffixes)
        
        if persona.uses_emoji and rng.random() < 0.3:
            emojis = ["😊", "🤔", "👀", "💡", "🙏"]
            question = question + " " + rng.choice(emojis)
        
        return question
```

---

## 完整的测试运行器

```python
class RandomSeedTester:
    """随机种子驱动的端到端测试"""
    
    def run_test(self, seed: int) -> dict:
        """一个seed = 一个完整的用户session模拟"""
        
        # Layer 1: 生成用户人格
        persona = UserPersona(seed)
        
        # Layer 2: 生成行为轨迹
        trajectory = TrajectoryGenerator().generate(persona, seed + 1000)
        
        # Layer 3: 生成具体问题
        qgen = QuestionGenerator()
        questions = []
        for step in trajectory:
            q = qgen.generate(
                action=step["action"],
                domain=step["domain"],
                persona=persona,
                trajectory=trajectory,
                seed=seed + step["turn"] * 100,
            )
            step["question"] = q
            questions.append(step)
        
        # 执行测试
        results = self._execute_session(questions)
        
        return {
            "seed": seed,
            "persona": persona.archetype,
            "style": persona.style,
            "turns": len(questions),
            "results": results,
            "pass_rate": sum(1 for r in results if r["passed"]) / len(results),
        }
    
    def run_batch(self, seeds: list[int]) -> dict:
        """批量测试——多个不同的seed"""
        all_results = []
        for seed in seeds:
            result = self.run_test(seed)
            all_results.append(result)
            print(f"  seed={seed}: {result['persona']:10s} {result['turns']}turns pass={result['pass_rate']:.0%}")
        
        overall_pass = sum(r["pass_rate"] for r in all_results) / len(all_results)
        return {
            "total_seeds": len(seeds),
            "overall_pass_rate": overall_pass,
            "by_persona": self._aggregate_by_persona(all_results),
            "failures": [r for r in all_results if r["pass_rate"] < 1.0],
        }

# 使用方式：
# tester = RandomSeedTester()
# result = tester.run_batch(seeds=range(42, 72))  # 30个不同的虚拟用户
```

---

## 验证标准

```
每次代码改动后运行：
  tester.run_batch(seeds=range(42, 52))   # 快速10个seed
  
每个Phase完成后运行：
  tester.run_batch(seeds=range(42, 72))   # 完整30个seed

标准：
  - 快速测试：pass_rate >= 90%
  - 完整测试：pass_rate >= 85%
  - 没有任何seed的pass_rate < 70%（没有特别脆弱的用户类型）
```

## 可复现性保证

```
同一个seed永远生成同样的：
  - 用户人格（archetype/style/rates）
  - 行为轨迹（action序列）
  - 具体问题（自然语言）
  
但不同seed生成完全不同的用户行为。
seed=42的explorer和seed=43的explorer，虽然都是探索者，
但表达风格、领域偏好、具体问题都不同。
```
