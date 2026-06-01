# DeepForge 核心技术架构——超越 Claude Code 的路径

## 我们的定位

Claude Code 解决的问题：让强模型更方便地使用工具
DeepForge 解决的问题：**让弱模型释放出接近强模型的能力**

这是两个完全不同的命题。Claude Code 的框架是"透明管道"——模型强到不需要框架帮忙思考。我们的框架必须是"能力放大器"——在模型能力不足的地方补位，在模型能力够的地方不干扰。

## 核心哲学：三层能力模型

```
┌──────────────────────────────────────────┐
│  第一层：模型原生能力（预训练知识+推理）   │ ← 不可改变，但可以被激发
├──────────────────────────────────────────┤
│  第二层：框架增强能力（知识积累+策略演化）  │ ← DeepForge 的核心价值
├──────────────────────────────────────────┤
│  第三层：用户协作能力（反馈闭环+个性化）   │ ← 越用越强的飞轮
└──────────────────────────────────────────┘
```

Claude Code 只有第一层。它的框架是第一层的薄壳。
**DeepForge 的技术壁垒在第二层和第三层。**

## 五大核心机制设计

### 一、智能意图理解（替代硬编码路由）

**Claude Code 做法**：模型自己判断→工具调用或文本回复
**我们的问题**：弱模型判断力不足，会误判
**我们的方案**：框架辅助判断——不替代模型，而是给模型更好的判断依据

核心思想：**不是框架做决策，是框架给模型做决策的上下文**

```
用户输入"改成红色"
  ↓
框架分析上下文：
  - 上一轮是代码任务（conversation history里有代码）
  - "改成红色"在代码上下文中=修改样式
  - 在聊天上下文中=可能在讨论颜色偏好
  ↓
框架不做决策，而是把上下文信号注入system prompt：
  "用户上一轮生成了一个计算器网页，当前请求可能是要修改该代码"
  ↓
模型基于增强的上下文做出更准确的判断
```

与 Claude Code 的区别：Claude 的模型天然能理解上下文，不需要框架提示。我们的弱模型需要框架**显式提供上下文信号**，帮助它做出正确判断。

**技术实现**：

```python
class ContextAnalyzer:
    """分析对话上下文，生成辅助判断的信号"""
    
    def analyze(self, user_input, conversation_history):
        signals = []
        
        # 最近的产出物类型
        last_output_type = self._detect_last_output_type(conversation_history)
        if last_output_type == "code":
            signals.append("用户上一轮生成了代码，如果当前请求是修改类的，可能是要修改代码")
        
        # 话题连续性
        topic_shift = self._detect_topic_shift(user_input, conversation_history)
        if topic_shift:
            signals.append("用户切换了话题，当前请求与之前的代码任务无关")
        
        # 用户表达模式（从历史学习）
        user_style = self._detect_user_style(conversation_history)
        if user_style == "concise":
            signals.append("该用户习惯简短表达，请注意理解简短指令的完整意图")
        
        return signals
```

这些 signals 注入到 system prompt 里，弱模型拿到了更完整的判断依据。

### 二、渐进式知识蒸馏（超越 Claude Code 的 context compaction）

**Claude Code 做法**：context 接近满时压缩旧消息
**我们的超越**：不等 context 满，**实时提取高价值知识到永久存储**

Claude Code 的 compaction 是被动的——信息被压缩后就丢失了细节。
我们的蒸馏是主动的——**有价值的信息被提取到知识库，永不丢失**。

```
Claude Code 的信息生命周期：
  对话 → context window → 压缩摘要 → 丢弃
  （信息逐步衰减）

DeepForge 的信息生命周期：
  对话 → 实时蒸馏 → 知识库（永久） → 按需召回
  对话 → context window → 压缩 → 但核心知识已在知识库中保存
  （有价值的信息被永久保留）
```

这意味着：
- 用户第1次问"光速为什么不能超越"，模型给出深度回答
- 知识蒸馏提取关键洞察："光速本质是时空结构常数"
- 用户第100次 session 问物理问题时，这个洞察被召回注入
- **跨 session 的知识积累**——Claude Code 做不到（每个 session 从零开始）

**这就是"越用越强"的真正含义**——不是同一个 session 内越来越好，而是**框架整体的智慧随使用时间增长**。

### 三、自适应激发引擎（我们的核心算法）

已有的涌现式激发（v0.3）证明了一句话比12条推理链更有效。
但当前的激发语是静态的。

**终极形态**：激发语不是人写的，是框架从数据中**自动演化出来的**。

```
第0代：人工写的默认激发语
  ↓ 用户使用产生质量数据
第1代：框架发现科学领域的高分回答有什么共同的激发模式
  ↓ 提取成功模式，生成新变体
第2代：新变体在科学领域得分更高
  ↓ 保留科学领域的优化变体，其他领域继续探索
第N代：每个领域都有经过验证的最优激发策略
```

这不是换 prompt——是**框架自己学会了怎么激发不同领域的模型能力**。

关键算法设计：

```python
class ActivationEvolver:
    """激发语自动演化——基于质量数据的遗传算法"""
    
    def evolve(self):
        # 1. 评估：每个领域每个激发语变体的历史质量分
        domain_scores = self._aggregate_quality_by_domain_and_seed()
        
        # 2. 选择：保留高分变体
        survivors = self._select_top_variants(domain_scores, top_k=3)
        
        # 3. 变异：从高分变体的元素组合出新变体
        # 不是随机变异——是提取高分回答的开头模式作为新激发语的灵感
        new_variants = self._generate_from_success_patterns(survivors)
        
        # 4. 注入：下一轮使用新变体
        self._update_seed_pool(survivors + new_variants)
```

### 四、用户模型构建（个性化——Claude Code 完全没有）

Claude Code 对所有用户使用同一个 system prompt。
**我们为每个用户建立隐式画像**，个性化激发策略。

```python
class UserProfile:
    """从使用行为中隐式构建用户画像——用户完全无感知"""
    
    # 不是问用户"你是谁"，而是从行为推断
    primary_domains: list[str]       # 高频问题领域
    expertise_level: dict[str, str]  # 各领域的专业程度（从问题复杂度推断）
    response_preference: str         # 喜欢长回答还是简洁（从追问/满意信号推断）
    active_hours: list[int]          # 活跃时段
    satisfaction_patterns: dict      # 什么样的回答让他满意
```

这些画像影响激发策略：
- 程序员用户 → 技术回答更深入，给代码示例
- 学生用户 → 解释更通俗，给学习建议
- 高频用户 → 回答更简洁（他已经熟悉框架风格）
- 新用户 → 回答更详细，带引导

**这是真正的"千人千面"——不是推荐算法，是回答策略的个性化。**

### 五、可信度体系（真正解决幻觉问题——不是标注，是系统工程）

当前的置信度是模型自评（不可靠）。融合置信度的完整设计：

```
可信度 = f(模型自评, 框架历史, 知识验证, 用户反馈)

信号源：
1. 模型自评：✅⚠️标注（权重低，因为模型不知道自己不知道什么）
2. 框架历史：同类问题过去的用户满意率（权重随数据量增加）
3. 知识验证：回答中的事实是否和已验证知识库匹配（权重高）
4. 用户反馈：点赞/踩/追问/说不对（权重最高，但数据最少）

随时间演进：
- 第1天：只有模型自评（不可靠但有总比没有好）
- 第30天：框架历史开始有统计意义
- 第90天：知识库足够大，能做知识验证
- 第180天：用户反馈积累足够，可以校准其他信号的权重

这不是一个功能，是一个随时间自我校准的系统。
```

## 架构全景

```
用户输入
  ↓
┌─ ContextAnalyzer ──────────────────────────────┐
│  分析对话历史+上下文信号                          │
│  生成辅助判断的 context signals                   │
│  （帮助弱模型做出正确的路由判断）                  │
└────────────────────────────────────────────────┘
  ↓
┌─ ActivationEngine ─────────────────────────────┐
│  涌现式激发语（自动演化）                         │
│  + 领域知识注入（从知识库召回）                    │
│  + 用户画像适配                                   │
│  + context signals 注入                           │
│  → 构建 system prompt                            │
└────────────────────────────────────────────────┘
  ↓
┌─ 模型调用 ─────────────────────────────────────┐
│  模型自己决定：文本回复 or 工具调用                │
│  （框架不做路由决策，但给了模型足够的判断依据）     │
└────────────────────────────────────────────────┘
  ↓
┌─ QualityTracker ───────────────────────────────┐
│  记录质量数据（被动信号+回答特征）                 │
│  聚合领域统计                                     │
│  检测薄弱领域                                     │
└────────────────────────────────────────────────┘
  ↓
┌─ KnowledgeDistiller ───────────────────────────┐
│  从高质量回答中提取知识点                          │
│  存入知识库（按质量门控）                          │
│  知识老化+裁剪                                    │
│  → 下次同领域问题自动注入                         │
└────────────────────────────────────────────────┘
  ↓
┌─ ActivationEvolver ────────────────────────────┐
│  分析质量数据                                     │
│  发现薄弱领域                                     │
│  演化激发语变体                                   │
│  A/B验证                                         │
└────────────────────────────────────────────────┘
  ↓
  飞轮：越用 → 数据越多 → 知识越丰富 → 激发越精准 → 效果越好 → 用的人越多
```

## 与 Claude Code 的对比

| 维度 | Claude Code | DeepForge |
|---|---|---|
| 模型依赖 | 强模型必须 | 弱模型也行 |
| 路由机制 | 模型自决 | 框架辅助+模型自决 |
| 知识积累 | 无（每session重置） | 永久知识库+跨session |
| 个性化 | 无 | 用户画像+策略适配 |
| 可信度 | 无 | 四信号融合+自校准 |
| 激发策略 | 固定system prompt | 自动演化 |
| Context管理 | 被动压缩 | 主动蒸馏+被动压缩 |
| 越用越强 | 否 | 是（核心卖点） |

## 实施路线

这套架构不是一次性实现的。按以下顺序：

**Phase 1：修复当前 bug + ContextAnalyzer（解决路由问题）**
- 用上下文信号辅助模型判断，替代硬编码路由
- 解决"坦克大战后问论文"这类问题
- 解决"文本聊天不保存"问题

**Phase 2：完善知识蒸馏闭环（v0.5重做到位）**
- 质量门控、信号反馈、L1/L2真正工作
- 越用越强闭环有数据证明

**Phase 3：ActivationEvolver（激发语自动演化）**
- 从数据中发现最优激发策略
- 领域级优化

**Phase 4：UserProfile（个性化）**
- 隐式用户画像构建
- 策略适配

**Phase 5：融合可信度体系**
- 四信号融合
- 自校准

**Phase 6：Context Distillation（主动蒸馏替代被动压缩）**
- 实时知识提取到永久存储
- 跨session知识传递

---

# 五大核心机制——详细实施方案

---

## 机制一：智能意图理解（ContextAnalyzer）

### 1.1 要解决的问题

当前路由有两种失败模式：
- **误触发代码修改**：做完代码后问论文→走了_run_modify→输出代码
- **误触发代码生成**：口语化问题"帮我看看这个事儿"→被判为code

根因：路由依赖硬编码规则或状态残留，而非理解用户意图。

### 1.2 技术架构

```
用户输入
  ↓
ContextAnalyzer.analyze(user_input, conversation)
  ↓
生成 context_signals: list[str]
  ↓
注入到 system prompt 的上下文段
  ↓
模型基于增强上下文自行判断：文本回复 or 工具调用
```

ContextAnalyzer 不做决策，只提供信号。决策权在模型。

### 1.3 数据结构

```python
@dataclass
class ContextSignals:
    last_output_type: str          # "code" | "text" | "file_analysis" | "none"
    last_output_summary: str       # 上一轮产出物的一句话摘要
    topic_continuity: float        # 0~1，当前问题与上一轮的话题连续度
    turn_count: int                # 当前session的总轮次数
    recent_domains: list[str]      # 最近3轮的领域标签
    has_pending_code: bool         # 是否有未完成的代码任务
    user_sentiment: str            # "neutral" | "frustrated" | "curious" | "grateful"
    
    def to_prompt_section(self) -> str:
        """转换为注入system prompt的自然语言段"""
```

### 1.4 核心算法

```python
class ContextAnalyzer:
    def analyze(self, user_input: str, conversation: ConversationManager) -> ContextSignals:
        turns = conversation.turns
        
        # 1. 上一轮产出物类型
        last_output_type = "none"
        last_output_summary = ""
        for t in reversed(turns):
            if t.role == "assistant":
                if "<!DOCTYPE" in t.content or "```filepath:" in t.content:
                    last_output_type = "code"
                    # 提取文件名作为摘要
                    import re
                    files = re.findall(r'filepath:([^\n]+)', t.content)
                    last_output_summary = f"生成了 {', '.join(files)}" if files else "生成了代码"
                else:
                    last_output_type = "text"
                    last_output_summary = t.content[:50]
                break
        
        # 2. 话题连续度（不用TF-IDF，用简单的关键词重叠）
        topic_continuity = 0.0
        if len(turns) >= 2:
            prev_user = ""
            for t in reversed(turns):
                if t.role == "user" and t.content != user_input:
                    prev_user = t.content
                    break
            if prev_user:
                prev_tokens = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', prev_user.lower()))
                curr_tokens = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', user_input.lower()))
                if curr_tokens:
                    topic_continuity = len(prev_tokens & curr_tokens) / len(curr_tokens)
        
        # 3. 领域标签
        recent_domains = [t.domain for t in turns[-6:] if t.role == "assistant" and t.domain]
        
        # 4. 用户情绪（从关键词推断）
        user_sentiment = "neutral"
        if re.search(r'谢谢|感谢|太好了|不错', user_input):
            user_sentiment = "grateful"
        elif re.search(r'不对|错了|不行|垃圾|什么鬼', user_input):
            user_sentiment = "frustrated"
        elif re.search(r'为什么|怎么|原理|如何|什么是', user_input):
            user_sentiment = "curious"
        
        return ContextSignals(
            last_output_type=last_output_type,
            last_output_summary=last_output_summary,
            topic_continuity=topic_continuity,
            turn_count=len(turns),
            recent_domains=recent_domains[-3:],
            has_pending_code=last_output_type == "code",
            user_sentiment=user_sentiment,
        )
```

### 1.5 Prompt注入格式

```python
def to_prompt_section(self) -> str:
    parts = []
    
    if self.last_output_type == "code":
        parts.append(f"[上下文] 上一轮你{self.last_output_summary}。")
        if self.topic_continuity < 0.2:
            parts.append("用户当前话题与代码无关，请直接回答问题，不要修改代码。")
        else:
            parts.append("用户可能在要求修改代码，请判断。")
    
    if self.user_sentiment == "frustrated":
        parts.append("[注意] 用户对上一轮回答不满意，请更仔细地理解需求。")
    
    return "\n".join(parts) if parts else ""
```

### 1.6 集成点

```python
# orchestrator.py _direct_reply() 中
# 在构建activation prompt之前
context_analyzer = ContextAnalyzer()
signals = context_analyzer.analyze(user_input, self.conversation)
context_section = signals.to_prompt_section()

# 传给 activation_engine
system = self.activation_engine.build_activation_prompt(
    user_input=user_input,
    domain_context=domain_context,
    l1_compiled=all_knowledge,
    context_signals=context_section,  # 新增参数
)
```

### 1.7 验证策略

**单元测试（10个case）：**
```
1. 做完番茄钟 → 问"什么是AI" → signals.topic_continuity < 0.2 → prompt含"话题与代码无关"
2. 做完计算器 → "改成红色" → signals.topic_continuity > 0.5 → prompt含"可能在要求修改代码"
3. 纯聊天 → signals.last_output_type == "none" → 不注入代码相关信号
4. 用户说"不对" → signals.user_sentiment == "frustrated"
5. 用户说"谢谢" → signals.user_sentiment == "grateful"
```

**随机种子集成测试（30题混合场景）：**
```python
MIXED_SCENARIOS = [
    ("做一个番茄钟", "code"),
    ("今天天气怎么样", "text"),        # 话题切换
    ("改成暗色主题", "code_modify"),    # 回到代码
    ("量子计算是什么", "text"),         # 又切换
    ("谢谢", "text"),                   # 感谢
    ("帮我分析这个数据", "text"),       # 新话题
    ("做一个贪吃蛇游戏", "code"),      # 新代码任务
    ("为什么蛇不能穿墙", "text"),      # 关于游戏的问题（不是修改代码）
    ...
]
# 每个case验证：模型是否做出了正确的路由判断
```

**端到端验证（Playwright）：**
1. 做番茄钟→问论文→不输出代码 ✅
2. 做计算器→改红色→正常修改 ✅
3. 连续混合10轮无错误 ✅

### 1.8 失败回退

如果 ContextAnalyzer 的信号导致模型判断更差怎么办？
- 信号是additive的——只增加信息，不删除信息
- 即使信号错误（把代码修改误判为话题切换），模型仍然能从conversation history里看到上一轮的代码
- 降级方案：如果检测到连续2次路由错误（用户纠正），关闭ContextAnalyzer的信号注入，回退到纯模型判断

---

## 机制二：渐进式知识蒸馏（KnowledgeDistiller）

### 2.1 要解决的问题

- Claude Code 的知识在 session 结束后丢失
- 当前的知识提取太粗糙（正则匹配"本质/核心"）
- 提取的知识质量参差不齐，注入后可能引入噪声

### 2.2 技术架构

```
模型回答
  ↓
QualityGate（质量门控——只有高质量回答才提取）
  ↓
KnowledgeDistiller.extract(question, response, domain, quality_score)
  ↓
提取出 KnowledgeNugget 列表
  ↓
去重+验证（和已有知识对比）
  ↓
写入 LayeredCache（category="insight"）
  ↓
下次同领域问题 → recall → 注入 prompt
```

### 2.3 数据结构

```python
@dataclass
class KnowledgeNugget:
    content: str              # 知识点内容（一句话）
    domain: str               # 所属领域
    source_question: str      # 来源问题
    extraction_method: str    # "keyword" | "structural" | "conclusion"
    quality_score: float      # 提取时的质量分
    verified: bool            # 是否被后续使用验证过
    created_at: float
```

### 2.4 核心算法——多策略提取

当前只有关键词匹配（"本质/核心/因为"）。升级为三种策略并行：

```python
class KnowledgeDistiller:
    def extract(self, question: str, response: str, domain: str, quality: float) -> list[KnowledgeNugget]:
        if quality < 0.4:  # 质量门控
            return []
        
        nuggets = []
        
        # 策略1：关键词提取（现有，保留）
        nuggets.extend(self._extract_by_keywords(response, domain))
        
        # 策略2：结构提取——提取标题下的第一句话（通常是核心论点）
        nuggets.extend(self._extract_by_structure(response, domain))
        
        # 策略3：结论提取——提取"总之/因此/综上"后面的句子
        nuggets.extend(self._extract_conclusions(response, domain))
        
        # 去重（和已有知识对比）
        nuggets = self._deduplicate(nuggets)
        
        # 限制数量
        return nuggets[:3]
    
    def _extract_by_structure(self, response, domain):
        """提取每个标题后的第一句话——通常是该段的核心论点"""
        import re
        nuggets = []
        # 匹配 ## 标题\n第一句话
        for match in re.finditer(r'(?:^|\n)#{1,3}\s+.+?\n+([^#\n].+?[。\n])', response):
            sentence = match.group(1).strip()
            if 20 < len(sentence) < 150:
                nuggets.append(KnowledgeNugget(
                    content=f"[{domain}] {sentence}",
                    domain=domain,
                    source_question="",
                    extraction_method="structural",
                    quality_score=0,
                    verified=False,
                    created_at=0,
                ))
        return nuggets
    
    def _extract_conclusions(self, response, domain):
        """提取结论句"""
        import re
        nuggets = []
        for match in re.finditer(r'(?:总之|因此|综上|核心是|本质上|关键在于)[，：:]\s*(.+?)[。\n]', response):
            sentence = match.group(1).strip()
            if 15 < len(sentence) < 150:
                nuggets.append(KnowledgeNugget(
                    content=f"[{domain}] {sentence}",
                    domain=domain,
                    source_question="",
                    extraction_method="conclusion",
                    quality_score=0,
                    verified=False,
                    created_at=0,
                ))
        return nuggets
```

### 2.5 质量门控——和用户信号联动

```python
# 不是每次都提取，只在以下条件满足时提取：
should_extract = (
    quality_score >= 0.4                    # 回答特征分达标
    and prev_signal != "error"              # 上一轮不是用户否定
    and len(response) > 200                 # 回答有足够内容
    and not skip_extraction_flag            # 没有被标记跳过
)

# 如果用户后续给了正向反馈（追问/感谢），提升已提取知识的权重
# 如果用户给了负向反馈（不对/错了），降级已提取知识
```

### 2.6 知识召回——精准度保证

```python
def recall_insights(self, query: str, domain: str, max_results: int = 3) -> list[str]:
    """只召回高度相关的insight，避免噪声注入"""
    candidates = []
    
    for entry in self._entries.values():
        if entry.category != "insight":
            continue
        
        # 领域匹配（必须同领域或通用）
        entry_domain = entry.content.split("]")[0].strip("[") if entry.content.startswith("[") else ""
        if entry_domain and entry_domain != domain and entry_domain != "通用":
            continue
        
        # 触发词重叠度
        query_tokens = self._tokenize(query)
        overlap = len(query_tokens & entry.triggers)
        if overlap < 2:  # 至少2个token重叠
            continue
        
        # 质量加权
        score = overlap * (1 + entry.success_rate)
        candidates.append((score, entry.content))
    
    candidates.sort(key=lambda x: -x[0])
    return [c[1] for c in candidates[:max_results]]
```

### 2.7 验证策略

**越用越强闭环测试（必须通过）：**
```
1. 清空知识库
2. 跑10题科学领域（第1批）→ 记录得分A + 提取的insight数量
3. 验证insight质量：每条insight是否是有价值的知识点（人工检查）
4. 不清空，跑同样10题（第2批）→ 记录得分B
5. 验证：B >= A（越用越强）
6. 验证：第2批的回答中是否引用了第1批提取的知识
```

**噪声测试：**
```
1. 故意喂10条低质量回答（短/无结构/错误信息）
2. 验证：质量门控拦住了，insight数=0
3. 然后喂10条高质量回答
4. 验证：只有高质量的被提取
```

### 2.8 失败回退

- 知识注入导致得分下降 → 自动减少注入数量（3→2→1→0）
- 知识库膨胀 → prune + merge_duplicates（已有）
- 召回不相关知识 → 提高overlap阈值（2→3）

---

## 机制三：自适应激发引擎（ActivationEvolver）

### 3.1 要解决的问题

激发语是静态的。不同领域、不同模型、不同用户可能需要不同的激发策略。

### 3.2 技术架构

```
质量数据积累（quality_log.jsonl）
  ↓ 每50次回答触发一次
ActivationEvolver.evolve()
  ↓
分析各领域各变体的质量分布
  ↓
保留高分变体 + 从成功模式生成新变体
  ↓
更新激发语种群（per-domain）
  ↓
下次该领域问题 → 使用最优变体
```

### 3.3 数据结构

```python
@dataclass
class SeedVariant:
    id: str
    content: str                   # 激发语文本
    domain: str                    # "general" 或具体领域
    total_uses: int                # 总使用次数
    avg_quality: float             # 平均质量分
    quality_history: list[float]   # 最近20次质量分
    created_at: float
    parent_id: str | None          # 从哪个变体演化来的

class SeedPool:
    variants: dict[str, list[SeedVariant]]  # domain → variants
    # 每个领域最多5个变体
```

### 3.4 核心算法

```python
class ActivationEvolver:
    def __init__(self, seed_pool_path=".deepforge/seed_pool.json"):
        self.pool = self._load_pool(seed_pool_path)
    
    def select_seed(self, domain: str) -> str:
        """为当前领域选择最优激发语——epsilon-greedy策略"""
        variants = self.pool.get(domain, self.pool.get("general", []))
        if not variants:
            return DEFAULT_ACTIVATION_SEED
        
        # 90%的时间用最优变体（exploit），10%随机探索（explore）
        import random
        if random.random() < 0.1 and len(variants) > 1:
            return random.choice(variants).content
        
        # 最优 = 最高avg_quality且uses >= 5
        qualified = [v for v in variants if v.total_uses >= 5]
        if qualified:
            return max(qualified, key=lambda v: v.avg_quality).content
        
        # 数据不足时用默认
        return variants[0].content
    
    def evolve(self):
        """每50次回答触发一次——演化激发语种群"""
        from deepforge.core.quality_tracker import QualityTracker
        qt = QualityTracker()
        stats = qt.get_domain_stats()
        
        for domain, stat in stats.items():
            if stat["total_responses"] < 10:
                continue  # 数据不足
            
            variants = self.pool.get(domain, [])
            
            # 淘汰：avg_quality < 全局均值 - 0.1 的变体
            global_avg = stat["avg_quality"]
            survivors = [v for v in variants if v.avg_quality >= global_avg - 0.1 or v.total_uses < 5]
            
            # 变异：从最优变体的成功回答中提取开头模式
            if survivors:
                best = max(survivors, key=lambda v: v.avg_quality)
                new_variant = self._mutate(best, domain)
                if new_variant:
                    survivors.append(new_variant)
            
            # 限制种群大小
            self.pool[domain] = survivors[:5]
        
        self._save_pool()
    
    def _mutate(self, parent: SeedVariant, domain: str) -> SeedVariant | None:
        """从成功模式生成新变体——不是随机变异"""
        # 读取该领域的高质量回答开头
        # 提取共同的表达模式
        # 生成新的激发语
        # 这是一个需要积累足够数据后才有效的操作
        return None  # v1先不实现变异，只做选择
```

### 3.5 验证策略

**A/B 自动轮替验证：**
```
1. 给科学领域准备3个激发语变体
2. 跑30题科学问题，每个变体用10次
3. 比较三个变体的avg_quality
4. 验证：select_seed选出的是最高分的那个
```

**演化效果验证：**
```
1. 跑100题混合问题（积累数据）
2. 触发evolve()
3. 检查：薄弱领域是否被标记
4. 检查：薄弱领域的变体是否被淘汰或新增
5. 跑同样100题，对比得分
```

---

## 机制四：用户模型构建（UserProfile）

### 4.1 技术架构

```
用户每次交互
  ↓
UserProfileBuilder.update(question, response, signal, domain)
  ↓
更新 UserProfile（存储在 .deepforge/users/{user_id}.json）
  ↓
ActivationEngine 读取 profile
  ↓
个性化调整激发策略
```

### 4.2 数据结构

```python
@dataclass
class UserProfile:
    user_id: str
    total_interactions: int
    first_seen: float
    last_seen: float
    
    # 领域偏好（从问题领域分布推断）
    domain_distribution: dict[str, int]    # {"技术": 45, "科学": 12, ...}
    primary_domain: str                     # 最高频领域
    
    # 专业度（从问题复杂度推断）
    avg_question_length: float
    uses_technical_terms: bool              # 是否经常使用专业术语
    expertise_estimate: str                 # "beginner" | "intermediate" | "expert"
    
    # 回答偏好（从反馈信号推断）
    preferred_response_length: str          # "concise" | "detailed" | "adaptive"
    satisfaction_rate: float                # 正向信号 / 总信号
    
    # 行为模式
    avg_turns_per_session: float
    tends_to_follow_up: bool               # 倾向于追问还是单轮
```

### 4.3 个性化注入

```python
def personalize_prompt(self, profile: UserProfile) -> str:
    """根据用户画像生成个性化提示"""
    hints = []
    
    if profile.expertise_estimate == "expert":
        hints.append("该用户是有经验的专业人士，回答可以更深入技术细节，减少基础解释。")
    elif profile.expertise_estimate == "beginner":
        hints.append("该用户可能是初学者，请用通俗易懂的语言，多给例子。")
    
    if profile.preferred_response_length == "concise":
        hints.append("该用户偏好简洁回答，请精炼要点。")
    
    if profile.tends_to_follow_up:
        hints.append("该用户习惯追问，可以在回答末尾留一个引导性问题。")
    
    return "\n".join(hints) if hints else ""
```

### 4.4 验证策略

**画像准确性验证：**
```
1. 模拟"程序员用户"（连续问20个技术问题）
2. 检查profile: primary_domain="技术", expertise_estimate="expert"
3. 模拟"学生用户"（问简单学习问题）
4. 检查profile: expertise_estimate="beginner"
5. 验证个性化提示是否正确注入
```

---

## 机制五：融合可信度体系

### 5.1 技术架构

```
模型回答
  ↓
CredibilityEngine.assess(question, response, domain)
  ↓
四信号计算：
  signal_1: 模型自评（✅⚠️标注） → weight_1
  signal_2: 框架历史（同领域满意率）→ weight_2  
  signal_3: 知识验证（和知识库匹配）→ weight_3
  signal_4: 用户反馈（累积）→ weight_4
  ↓
composite_credibility = Σ(signal_i * weight_i)
  ↓
权重自校准：
  - 数据少时：weight_1高（只有自评可用）
  - 数据多时：weight_2,3,4提升，weight_1下降
```

### 5.2 权重自校准算法

```python
def _calibrate_weights(self, domain: str) -> tuple[float, float, float, float]:
    """根据数据量动态调整四个信号的权重"""
    stats = self.quality_tracker.get_domain_stats()
    domain_stat = stats.get(domain, {})
    n = domain_stat.get("total_responses", 0)
    
    knowledge_count = sum(1 for e in self.knowledge._entries.values() 
                         if e.category == "insight" and domain in e.content[:10])
    
    feedback_count = sum(1 for r in self._read_quality_log()
                        if r.get("domain") == domain and r.get("user_signal") not in ("unknown", "topic_switch"))
    
    # 数据越多，该信号的权重越高
    w_self = max(0.1, 0.4 - n * 0.005)           # 自评：数据越多权重越低
    w_history = min(0.3, n * 0.003)                # 历史：数据越多权重越高
    w_knowledge = min(0.3, knowledge_count * 0.02)  # 知识验证：知识越多越可靠
    w_feedback = min(0.3, feedback_count * 0.03)    # 用户反馈：反馈越多越可靠
    
    # 归一化
    total = w_self + w_history + w_knowledge + w_feedback
    return (w_self/total, w_history/total, w_knowledge/total, w_feedback/total)
```

### 5.3 验证策略

**校准曲线验证：**
```
1. 模拟0次使用 → 权重应该是：self=高, 其他=低
2. 模拟50次使用 → 权重应该开始平衡
3. 模拟200次使用 → history和feedback权重应该超过self
4. 验证权重变化曲线是否平滑
```

**可信度和实际质量的相关性验证：**
```
1. 跑20题，记录composite_credibility和人工评分
2. 计算相关系数
3. 随使用次数增加，相关系数应该提升（校准在改善）
```

---

## 全局验证策略

### 随机种子压力测试

```python
import random
random.seed(42)

# 生成100个混合场景
scenarios = []
for _ in range(100):
    scenario_type = random.choice(["chat", "code", "file", "modify", "topic_switch"])
    # 每种类型生成对应的随机问题
    # 连续执行，验证路由正确率、知识积累量、质量分趋势
```

### 持续集成验证

每次代码改动必须通过：
1. 单元测试（各组件独立验证）
2. Playwright E2E（前端全链路）
3. 随机种子30题（混合场景无错误）
4. 专家刁钻问题10题（回答质量达标）
5. 越用越强闭环（第2批 >= 第1批）

### 回归测试

每个新版本必须和上一版本做A/B对比（20题标准基准），得分不能下降。

---

# 补充：执行纪律、测试体系、失败处理、全局一致性、哲学对齐

---

## 一、设计哲学校验——所有决策的判断标准

每一个技术决策都必须通过这个校验：

### 哲学三问

**Q1: 这是在帮助模型更好地判断，还是在替代模型判断？**
- 帮助 = 给模型更多上下文信息，让它自己做出更好的决策 ✅
- 替代 = 框架用规则/关键词/分类器做了模型应该做的决策 ❌
- 例：`_is_text_task` 用正则判断路由 = 替代 ❌
- 例：ContextAnalyzer 生成上下文信号注入prompt = 帮助 ✅

**Q2: 这让框架越用越强了吗？还是只解决了当下？**
- 越用越强 = 每次交互产生的数据/知识能让下一次更好 ✅
- 解决当下 = 硬编码一个修复，不会随使用改善 ❌
- 例：hardcode推理链模板 = 解决当下 ❌
- 例：从高质量回答中提取insight → 下次注入 = 越用越强 ✅

**Q3: 这对用户透明吗？**
- 透明 = 用户不需要知道框架在做什么，体验自然流畅 ✅
- 打扰 = 需要用户配合、额外操作、看到内部机制 ❌
- 例：用户看到"[领域]：数学" 标记 = 打扰 ❌
- 例：回答自然地更有深度但用户不知道为什么 = 透明 ✅

### 违反哲学的历史决策（需要纠正）

| 决策 | 违反了什么 | 应该怎么做 |
|---|---|---|
| `_is_text_task` 正则路由 | Q1替代模型 | 删掉，让模型自己判断 |
| `_run_modify` 自动触发 | Q1替代模型 | 删掉，让模型从history理解意图 |
| TF-IDF领域分类器 | Q1替代模型 | 降级为辅助信号，不做路由决策 |
| 12条推理链模板 | Q1替代模型 | 已替换为涌现式激发 ✅ |
| 知识提取靠正则"本质/核心" | Q2解决当下 | 升级为多策略+质量门控 |
| `record_response_quality` | Q2不会改善 | 已删除，用quality_tracker替代 ✅ |

---

## 二、测试体系——怎么做到非常彻底

### 测试不是验证"能不能跑"，是验证"用户使用时会不会出问题"

### 2.1 四层测试金字塔

```
         ╱╲
        ╱  ╲     L4: 真实用户场景模拟（最重要）
       ╱────╲    模拟用户的真实使用轨迹，混合多种操作
      ╱      ╲
     ╱────────╲  L3: 路径切换测试
    ╱          ╲ 不同路径之间的切换是否正确（代码→聊天→文件→修改）
   ╱────────────╲
  ╱              ╲ L2: 功能回归测试
 ╱                ╲ 每个已知bug的场景作为永久test case
╱──────────────────╲
╲                  ╱ L1: 单元测试
 ╲                ╱  各组件独立验证（输入→输出正确）
  ╲──────────────╱
```

### 2.2 L4 真实用户场景模拟（最关键）

不是我设计的理想化问题，而是模拟真实用户的随机行为：

```python
class UserSimulator:
    """模拟真实用户——随机、混合、不可预测"""
    
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.session_history = []
    
    def generate_session(self, turns=15) -> list[dict]:
        """生成一个完整的用户session——混合多种操作"""
        session = []
        last_action = None
        
        for i in range(turns):
            # 用户行为概率分布（基于真实使用模式）
            if last_action == "code":
                # 做完代码后的行为分布
                action = self.rng.choices(
                    ["modify_code", "ask_about_code", "switch_topic", "chat"],
                    weights=[30, 20, 35, 15]  # 35%概率换话题——这是出bug的高发区
                )[0]
            elif last_action == "file_upload":
                action = self.rng.choices(
                    ["ask_about_file", "switch_topic", "upload_another"],
                    weights=[60, 30, 10]
                )[0]
            else:
                action = self.rng.choices(
                    ["chat", "code", "file_upload", "deep_question", "follow_up"],
                    weights=[30, 20, 10, 25, 15]
                )[0]
            
            question = self._generate_question(action, session)
            expected_behavior = self._expected_behavior(action)
            
            session.append({
                "turn": i + 1,
                "action": action,
                "question": question,
                "expected": expected_behavior,
            })
            last_action = action
        
        return session
    
    def _expected_behavior(self, action):
        """每个action的预期行为——这是验证的依据"""
        return {
            "chat": {"type": "text", "should_not": "contain code blocks"},
            "code": {"type": "code", "should": "generate runnable code"},
            "modify_code": {"type": "code", "should": "modify previous code"},
            "switch_topic": {"type": "text", "should_not": "reference previous code"},
            "ask_about_file": {"type": "text", "should": "reference file content"},
            "follow_up": {"type": "text", "should": "reference previous answer"},
            "deep_question": {"type": "text", "should": "have depth and structure"},
        }.get(action, {})
```

**关键设计：`weights` 来源于用户截图里暴露的真实使用模式。**
35%概率在做完代码后换话题——这正是出 bug 的高发区。

### 2.3 L3 路径切换测试

针对已知的路径切换 bug，构建永久 test case：

```python
PATH_SWITCH_TESTS = [
    # (操作序列, 每步预期)
    {
        "name": "代码后聊天",
        "steps": [
            ("做一个番茄钟", "code"),
            ("什么是AI", "text"),        # 不应输出代码
            ("帮我改成暗色主题", "code"), # 应该修改番茄钟
        ]
    },
    {
        "name": "文件后聊天",
        "steps": [
            ("上传PDF+帮我解读", "text_with_file"),
            ("第三部分讲了什么", "text"),  # 应保留文件上下文
            ("今天天气怎么样", "text"),    # 不应引用PDF
        ]
    },
    {
        "name": "多任务交错",
        "steps": [
            ("做一个计算器", "code"),
            ("1+1等于几", "text"),
            ("把计算器改成红色", "code"),
            ("谢谢", "text"),
            ("做一个番茄钟", "code"),      # 新代码任务，不是修改计算器
        ]
    },
    {
        "name": "否定后继续",
        "steps": [
            ("什么是光合作用", "text"),
            ("不对你说错了", "text"),       # 否定
            ("重新解释一下", "text"),       # 应该重新回答，不受上轮影响
        ]
    },
]
```

### 2.4 L2 回归测试——每个bug永久存活

每次发现一个bug，都创建一个永久的test case：

```python
REGRESSION_TESTS = [
    # Bug: 做完坦克大战问论文→输出代码 (2026-05-30发现)
    {"input_sequence": ["做一个坦克大战游戏", "这篇论文讲了什么"],
     "turn_2_should_not": "contain <!DOCTYPE or ```filepath"},
    
    # Bug: 文件上传后上下文污染 (2026-05-29发现)
    {"input_sequence": ["上传PDF+帮我解读", "你是谁"],
     "turn_2_should_not": "mention PDF content"},
    
    # Bug: react-markdown Runtime TypeError (2026-05-29发现)
    {"check": "no JS console errors after page load"},
    
    # ... 每次发现新bug就追加
]
```

### 2.5 L1 单元测试

每个组件独立验证，不依赖外部服务：

```python
# ContextAnalyzer 单元测试
def test_context_analyzer():
    analyzer = ContextAnalyzer()
    
    # 上一轮是代码，当前是聊天
    signals = analyzer.analyze("什么是AI", mock_conversation_with_code)
    assert signals.last_output_type == "code"
    assert signals.topic_continuity < 0.3
    assert "话题与代码无关" in signals.to_prompt_section()
    
    # 上一轮是代码，当前是修改请求
    signals = analyzer.analyze("改成红色", mock_conversation_with_code)
    assert signals.topic_continuity > 0.3
    assert "可能在要求修改" in signals.to_prompt_section()
```

---

## 三、严格执行协议——怎么保证按计划做

### 3.1 执行 Checklist 制度

每个 Phase 开始前，把方案里的验证标准转化为一个 checklist 文件：

```markdown
# Phase 1 执行 Checklist

## 实现
- [ ] ContextAnalyzer 类创建
- [ ] analyze() 方法实现
- [ ] to_prompt_section() 方法实现
- [ ] 集成到 orchestrator._direct_reply()
- [ ] 删除 _is_text_task 硬编码路由
- [ ] 删除 _run_modify 自动触发
- [ ] task_store 保存文本回复

## 单元测试 (L1)
- [ ] ContextAnalyzer: 代码后聊天 → topic_continuity < 0.3
- [ ] ContextAnalyzer: 代码后修改 → topic_continuity > 0.3
- [ ] ContextAnalyzer: 用户情绪检测 (frustrated/grateful/curious)
- [ ] task_store: 文本回复保存+读取

## 路径切换测试 (L3)
- [ ] 做番茄钟→问AI→不出代码
- [ ] 做计算器→改红色→正常修改
- [ ] 文件解读→追问→保留上下文→换话题→不引用文件

## 真实用户模拟 (L4)
- [ ] UserSimulator seed=42 生成15轮→全部正确
- [ ] UserSimulator seed=123 生成15轮→全部正确
- [ ] UserSimulator seed=456 生成15轮→全部正确

## 回归测试 (L2)
- [ ] 所有 REGRESSION_TESTS 通过

## E2E
- [ ] Playwright 25/26
- [ ] 前端 rebuild + 验证

## 得分
- [ ] 20题标准基准 >= 7.70

## 哲学校验
- [ ] 没有新增硬编码路由规则
- [ ] 没有替代模型判断的逻辑
- [ ] 新功能是帮助模型而非替代模型
```

**规则：checklist 里有一项未打勾，就不能宣布完成。**

### 3.2 执行日志

每个 Phase 维护一个执行日志，记录：
- 做了什么改动
- 为什么做这个改动（对应方案的哪一步）
- 改动后哪些测试通过了/失败了
- 如果偏离了方案，原因是什么

```markdown
# Phase 1 执行日志

## 2026-05-30 00:30
- 改动：创建 ContextAnalyzer 类
- 对应方案：机制一 §1.4
- 测试结果：L1 单元测试 5/5 通过
- 偏离：无

## 2026-05-30 01:15
- 改动：集成到 orchestrator
- 对应方案：机制一 §1.6
- 测试结果：L3 路径切换 2/3 通过
- 失败项：做计算器→改红色→未走修改路径
- 分析：因为删掉了 _run_modify，Builder 没有从 history 里找到代码
- 决策：不恢复 _run_modify，而是在 Builder prompt 里注入上一轮代码
```

### 3.3 禁止事项

- ❌ 不准在测试没全通过时提交代码
- ❌ 不准跳过方案里的某一步"之后再做"
- ❌ 不准用临时补丁解决问题（除非明确标记+创建跟踪任务）
- ❌ 不准在未重启后端的情况下宣布修复生效
- ❌ 不准只跑自动化测试就宣布完成——必须包含用户场景模拟

---

## 四、达不到预期怎么办——失败处理协议

### 4.1 分级处理

**Level 1：得分下降 < 5%**
- 可能是LLM输出随机性
- 处理：跑3次取平均，如果平均分达标则通过
- 如果平均分仍低：检查是否引入了噪声（如知识注入不相关）

**Level 2：得分下降 5-15%**
- 大概率是实现有问题
- 处理：
  1. 用 git diff 对比改了什么
  2. 逐个改动回退，定位哪个改动导致下降
  3. 分析根因（是逻辑错误？是信号冲突？是prompt变长了？）
  4. 修复根因，不是调参数

**Level 3：得分下降 > 15%**
- 架构设计有问题
- 处理：
  1. 停止实施
  2. 回退到上一个稳定版本
  3. 重新审视方案设计
  4. 和用户讨论方向是否正确
  5. 修改方案后重新开始

**Level 4：功能性 bug（用户可感知的错误）**
- 优先级最高，立刻修复
- 处理：
  1. 复现 bug → 创建 REGRESSION_TEST
  2. 分析根因（不是症状）
  3. 修复根因
  4. 验证 REGRESSION_TEST 通过
  5. 验证没有引入新 bug（全量回归测试）

### 4.2 回退机制

每个 Phase 开始前打一个 git tag：
```bash
git tag phase-1-start
```

如果 Phase 1 失败需要回退：
```bash
git reset --hard phase-1-start
```

不要在半完成的状态上继续堆代码。

### 4.3 方案修改协议

实施过程中发现方案有问题时：
1. 停止编码
2. 记录发现的问题
3. 分析原因
4. 更新方案文档（不是只在脑子里改）
5. 通知用户方案有调整
6. 确认后继续

---

## 五、全局一致性——站在框架整体看设计

### 5.1 组件交互矩阵

每增加一个新机制，必须评估它和所有现有机制的交互：

```
                Context  Activation  Knowledge  Quality   Credibility  User
                Analyzer  Engine     Distiller  Tracker   Engine       Profile
ContextAnalyzer   -        输入信号    无         无        无           读取偏好
ActivationEngine 接收信号    -        读取知识    无        无           读取画像
KnowledgeDistill  无       提供L1     -          读取分数   无           无
QualityTracker    无       无         门控提取    -         提供数据     更新画像
CredibilityEng    无       无         验证匹配   读取历史    -           无
UserProfile      提供偏好   适配策略   无         更新画像   无            -
```

每个格子里的"无"要验证——确认确实没有交互，不是遗漏。
每个有交互的格子要测试——确认交互正确，不冲突。

### 5.2 数据流全景

```
用户输入
  │
  ├─→ ConversationManager.add_user()     [存储]
  ├─→ QualityTracker.detect_signal()     [上一轮的反馈]
  ├─→ ContextAnalyzer.analyze()          [上下文信号]
  │
  ├─→ ActivationEngine.build_prompt()    [构建system prompt]
  │     ├── 涌现式激发语                  [from SeedPool]
  │     ├── 上下文信号                    [from ContextAnalyzer]
  │     ├── 领域知识                      [from LayeredCache recall]
  │     ├── 用户画像适配                  [from UserProfile]
  │     └── 可信度校准提示                [from CredibilityEngine]
  │
  ├─→ LLM调用                           [模型自行决策]
  │
  ├─→ 回答后处理
  │     ├── ConversationManager.add_assistant()  [存储]
  │     ├── QualityTracker.record()              [质量日志]
  │     ├── KnowledgeDistiller.extract()         [知识提取，有门控]
  │     ├── CredibilityEngine.assess()           [可信度评估]
  │     └── UserProfile.update()                 [画像更新]
  │
  └─→ 定期后台任务
        ├── QualityTracker.aggregate()           [每10次]
        ├── ActivationEvolver.evolve()           [每50次]
        ├── LayeredCache.prune()                 [超500条时]
        └── UserProfile.save()                   [每次]
```

### 5.3 不变量（Invariants）——系统在任何时刻都必须满足

1. **对话历史只增不删**（compaction除外）——不会因为bug导致用户对话丢失
2. **知识库只通过门控写入**——不会写入垃圾知识
3. **激发语至少有默认值**——即使SeedPool为空也不会崩溃
4. **路由决策永远由模型做**——框架不做路由决策
5. **用户操作不应阻塞超过60秒**——任何超时都有fallback
6. **每轮回答之间无状态泄漏**——上一轮的artifacts不污染下一轮的路由
7. **质量分不是模型自评**——融合了框架历史+用户反馈
8. **测试红线：得分不低于上一版本**——新版本不能regression

### 5.4 每个Phase的全局检查

每个Phase完成后，除了自身的checklist，还要通过全局检查：

```
全局检查：
- [ ] 不变量1-8全部满足
- [ ] 组件交互矩阵里的交互都测试了
- [ ] 数据流全景里的每条线都验证了
- [ ] 哲学三问通过
- [ ] 所有REGRESSION_TESTS通过
- [ ] 20题标准基准得分不低于上一版
```

---

## 六、实施路线（更新版——带具体步骤和验收标准）

### Phase 1：ContextAnalyzer + 路由修复（预计2天）

**目标**：解决"坦克大战后问论文出代码"这类路由bug

**步骤**：
1. 创建 `deepforge/core/context_analyzer.py`
2. 实现 `ContextSignals` 数据结构
3. 实现 `ContextAnalyzer.analyze()`
4. 实现 `to_prompt_section()`
5. 集成到 `orchestrator.py`——删除 `_is_text_task`、删除 `_run_modify` 自动触发
6. 修改 `task_store.py`——保存文本回复
7. 修改 Builder prompt——注入上一轮代码（如果有）

**验收**：Phase 1 Checklist 全部打勾

### Phase 2：知识蒸馏重做（预计2天）

**目标**：越用越强闭环，有数据证明

**步骤**：
1. 创建 `deepforge/core/knowledge_distiller.py`（替代当前的_extract_and_store_knowledge）
2. 实现三策略提取（关键词+结构+结论）
3. 质量门控和信号联动
4. 精准召回（领域匹配+overlap阈值）
5. L1/L2验证真正工作
6. 越用越强闭环测试

**验收**：Phase 2 Checklist + 第2批得分 > 第1批

### Phase 3：ActivationEvolver（预计3天）

**目标**：激发语从数据中自动演化

**步骤**：
1. 创建 `deepforge/core/activation_evolver.py`
2. 实现 SeedPool 数据结构
3. 实现 epsilon-greedy 选择算法
4. 实现演化（淘汰+选择+变异）
5. A/B自动轮替测试

**验收**：Phase 3 Checklist + 薄弱领域得分提升

### Phase 4：UserProfile（预计2天）

**目标**：隐式用户画像，个性化激发

**步骤**：
1. 创建 `deepforge/core/user_profile.py`
2. 实现画像构建算法
3. 个性化prompt注入
4. 验证不同"用户"得到不同回答风格

**验收**：Phase 4 Checklist + 个性化效果验证

### Phase 5：融合可信度（预计2天）

**目标**：四信号融合的可信度体系

**步骤**：
1. 创建 `deepforge/core/credibility_engine.py`
2. 四信号计算
3. 权重自校准算法
4. 校准曲线验证

**验收**：Phase 5 Checklist + 可信度和实际质量的相关性 > 0.5

### Phase 6：Context Distillation（预计2天）

**目标**：主动蒸馏替代被动压缩

**步骤**：
1. 实现 context window 监控
2. 实现主动蒸馏（到知识库）
3. 实现被动压缩（到摘要）
4. 跨session知识传递测试

**验收**：Phase 6 Checklist + 50轮对话无context overflow
