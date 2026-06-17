# Educe 全场景 Benchmark v2

## 设计原则

- 每领域 5 个精选 case，L1/L2/L3 分级
- 真实用户口吻，客观验收标准
- 验证不同能力维度：shell/文件操作/build/memorize/clarify/多轮对话

---

## Coding (CODE)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| CODE-01 | L1 | "给 click 加一个 --version-short 选项，只输出纯数字版本号" | decorators.py 有新函数；__init__.py export | search+edit_file |
| CODE-02 | L1 | "这个项目的 core.py 里 BaseCommand 类没 docstring，补一个" | `BaseCommand.__doc__` 非空 | 定位+edit_file |
| CODE-03 | L2 | "帮我给 Command 类加个 aliases 支持，一个命令多个名字" | self.aliases 存在；add_command 注册别名 | 跨位置修改 |
| CODE-04 | L2 | "这个项目里有个函数特别长看着头疼，帮我拆一下" | pytest 通过；单函数行数下降 | 自主定位+重构 |
| CODE-05 | L3 | "这个项目的错误处理太分散了，能整理统一一点吗？" | 应触发 clarify；不该直接动手 | 决策判断 |

## 金融 (FIN)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| FIN-01 | L1 | "帮我算下这笔房贷：300万，30年，利率3.5%，等额本息，月供多少" | 月供≈13473元（误差<5元）；展示计算式 | shell计算 |
| FIN-02 | L1 | "把这个 CSV 里的交易记录按月汇总支出，存成新文件" | 生成 monthly.csv；各月合计正确 | 文件读写/数据处理 |
| FIN-03 | L2 | "我有10万，想做个简单的资产配置，风险中等，给个方案" | 主动 clarify 风险偏好/期限；比例合计100% | clarify/多轮 |
| FIN-04 | L2 | "对比这三家公司近三年的营收增长，做个表" | 读取数据源；增长率正确；输出对比表 | 文件读/格式化 |
| FIN-05 | L3 | "做一个可交互的复利计算器网页，能调本金/利率/年限看曲线" | build HTML 可打开；输入联动；曲线正确 | build/前端 |

## 科技 (TECH)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| TECH-01 | L1 | "查下这台机器的内存和磁盘占用" | 执行系统命令；输出真实数值 | shell |
| TECH-02 | L1 | "把这个 log 里所有 ERROR 行提取出来计数" | grep 计数正确；列出条目 | shell/文本处理 |
| TECH-03 | L2 | "帮我把这个项目的依赖列一下，看有没有过时的" | 解析依赖文件；标注版本；指出可升级项 | 文件读/分析 |
| TECH-04 | L2 | "我想给团队介绍一下 Docker，做个要点提纲，记下来" | memorize 关键点；提纲分层清晰 | memorize/组织 |
| TECH-05 | L3 | "搭一个最小的 REST API demo，有 GET/POST 两个接口，能跑起来" | 文件完整；本地启动；接口响应正确 | build/多文件/shell |

## 教育 (EDU)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| EDU-01 | L1 | "用初中生能懂的话解释什么是函数" | 无术语堆砌；含1个生活类比 | 表达/通俗化 |
| EDU-02 | L1 | "给我出5道二元一次方程练习题，带答案" | 5题；答案正确可验算 | 生成/数学 |
| EDU-03 | L2 | "帮我备一节关于光合作用的课，记一下重点和板书安排" | memorize 成功；含目标/重点/板书结构 | memorize/教学设计 |
| EDU-04 | L2 | "我想学 Python，但完全零基础，给个4周计划" | 主动 clarify 每周时间；计划分周递进 | clarify/规划 |
| EDU-05 | L3 | "做个交互式九九乘法表网页，点击格子高亮整行整列" | build HTML 可打开；交互正确 | build/前端 |

## 生活 (LIFE)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| LIFE-01 | L1 | "帮我把这周的待办整理成清单存起来" | 生成清单文件；条目无遗漏 | write_file |
| LIFE-02 | L1 | "算下北京到上海开车大概多少油钱，油耗8升百公里" | 距离合理；油价×油耗计算正确 | 计算/常识 |
| LIFE-03 | L2 | "我下周要搬家，帮我列个准备清单，别漏东西" | 清单按时间线分阶段；覆盖核心项 | 组织/生成 |
| LIFE-04 | L2 | "帮我写封英文邮件，跟导师请两天假，语气正式但不卑微" | 格式正确；语气适当；无语法错误 | 写作/语气 |
| LIFE-05 | L3 | "做一个精美的个人待办网页，支持添加/完成/删除，数据本地存" | build HTML；CRUD 功能正确；localStorage 持久化 | build/完整应用 |

## 科研 (SCI)

| ID | L | 指令 | 验收 | 能力 |
|---|---|---|---|---|
| SCI-01 | L1 | "写一段 Python 代码画正弦函数图像，保存成图片" | 代码可运行；生成 .png 文件 | shell/代码生成 |
| SCI-02 | L1 | "这个 CSV 数据集有多少行、多少列、各列的类型分布" | 统计正确；输出清晰表格 | 数据分析 |
| SCI-03 | L2 | "帮我对这组实验数据做个 t 检验，看两组有没有显著差异" | 计算 t 值和 p 值正确；给出结论 | 统计/shell |
| SCI-04 | L2 | "用拉丁方设计一个8人品鉴实验的分组方案" | 方案满足拉丁方约束；无重复 | 实验设计/逻辑 |
| SCI-05 | L3 | "做个数据可视化面板，展示三组实验数据的箱线图对比" | build HTML；箱线图正确；数据可配置 | build/可视化 |

---

## 评分维度（每 case 0-5 分 × 4 维）

1. **完成度**：验收标准是否达成
2. **过程效率**：轮次数 / 冗余操作 / 是否回退重做
3. **决策质量**：该问就问（L3-CODE-05）、该做就做（L1）、不越界
4. **产出质量**：代码风格 / 文档结构 / 计算精度

---

## 日志系统重构方案要点

### 三层架构
- L0 summary: session 级元数据（成功/失败/轮数/耗时/token）
- L1 event: 行为链事件（turn/action/framework_event）
- L2 trace: 完整 payload（system prompt/raw output/full action result）

### 存储结构
```
.educe/logs/
  index.jsonl              # L0: 每行一个 session summary
  sessions/
    2025-01-01/
      <session_id>/
        events.jsonl       # L1: 按 seq 排序的行为链
        trace.jsonl        # L2: 大 payload（可选关闭）
        meta.json          # session 元数据
```

### 当前缺失的 5 个关键事件
1. **framework_event** — nudge/continuation/safety_net 触发记录
2. **turn_start** — 含 system_prompt_ref + messages 摘要
3. **raw_output_ref** — parse 前的原始模型输出
4. **reply_full** — 不截断的完整回复
5. **session_end + L0 index** — 完整生命周期闭环
