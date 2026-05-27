# DeepForge 7-Agent 归因实验技术架构设计  
（版本 v0.1，可直接落地）

---

## 1. 技术选型

| 维度 | 选型 | 理由 | 备注 |
|------|------|------|------|
| 语言 | Python 3.8-3.12 | 团队统一、DeepForge 原生支持、数据科学生态好 | 实验脚本与评估脚本同栈 |
| 框架 | DeepForge 7-Agent 框架（已存在 deepforge/） | 直接复用 Agent 通信、消息总线、日志、Meter | 只做「归因」场景任务编排 |
| 指标计算 | pandas + polars（混合） | polars 处理大样本≤5 ms/条；pandas 做二次统计 | 自动降级：无 polars 回退 pandas |
| 可视化 | Express.js + Vue3（Vite） | 前端独立服务，与 CLI 解耦；打包后体积 <3 MB | 仅 dashboard 子目录 |
| 存储 | 本地文件系统（jsonl + yaml） | 实验阶段无并发、无需事务；版本控制友好 | 后续可插件化到 S3/MinIO |
| 第三方 | 无外部 API 依赖 | 合规、可离线运行；CI 可 100% 容器复现 | 如需 LLM 反向调用，走 DeepForge 插件 |

---

## 2. 系统架构（文本图）

```
┌-------------------------┐
│  CLI (Typer)            │
│  deepforge metrics *    │
└-----------┬-------------┘
            │ invoke
┌-----------┴-------------┐
│  Metrics SDK Core       │
│  ├─ config_loader       │
│  ├─ eval_engine (polars)│
│  ├─ gate                │
│  └─ exporter (csv/png)  │
└-----------┬-------------┘
            │ read/write
┌-----------┴-------------┐
│  File System            │
│  ├─ gold.jsonl          │
│  ├─ pred.jsonl          │
│  ├─ metrics.json        │
│  └─ metrics_config.yaml │
└-----------┬-------------┘
            │ spawn
┌-----------┴-------------┐
│  Dashboard (Node)       │
│  8080端口，SPA，WebSocket│
└-------------------------┘

实验侧（独立进程）
┌-------------------------┐
│  run_7agent.py          │──► pred.jsonl
│  run_1agent.py (基线)    │──► pred_baseline.jsonl
└-------------------------┘
```

关键约定：  
1. 实验脚本只负责生成 `pred*.jsonl`，不依赖指标系统；指标系统只读文件，二者解耦。  
2. 所有指标公式集中写在 `eval/metrics_config.yaml`，代码不动硬编码。  
3. Gate 判定与 CI 零耦合：只要进程 exit code ≠0 即可，CI 脚本只需 `deepforge metrics gate`。

---

## 3. 目录结构（tree）

```
deepforge-attribution-exp/
├── README.md
├── pyproject.toml              # 包入口 + 依赖
├── Makefile                    # 一键 install & demo
├── eval/
│   ├── metrics_config.yaml     # 单一指标定义源
│   ├── gold.jsonl              # 人工标注 50 条
│   ├── pred.jsonl              # 实验组最新结果
│   ├── pred_baseline.jsonl     # 对照组结果
│   └── __init__.py
├── deepforge_metrics/          # pip 包主目录
│   ├── __init__.py
│   ├── cli.py                  # Typer 命令树
│   ├── config.py               # YAML 转 Pydantic
│   ├── engine.py               # polars 计算核心
│   ├── gate.py                 # 判定 & exit code
│   ├── exporter.py             # CSV / PNG
│   └── utils.py
├── dashboard/                  # 前端独立目录
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.vue
│       ├── components/MetricCard.vue
│       └── api.ts              # 调用 /api/metrics
├── scripts/
│   ├── run_7agent.py           # 实验组
│   ├── run_1agent.py           # 对照组（复现基线）
│   └── sample_selector.py      # 从 200 通选 100 通
├── experiment/
│   ├── agent_roles.yaml        # 7-Agent 分工配置
│   └── prompts/                # 各 Agent jinja2 模板
└── tests/
    ├── test_eval.py
    └── test_gate.py
```

---

## 4. 核心模块设计

### 4.1 config.py

职责：加载 `metrics_config.yaml` → Pydantic 模型，供引擎 & Gate 使用。

```python
class Metric(BaseModel):
    name: str
    formula: str          # polars expression 字符串
    target: float
    gate: bool = False
    higher_is_better: bool = True

class Config(BaseModel):
    metrics: List[Metric]
```

关键函数：  
`load_config(path: Path) -> Config`

---

### 4.2 engine.py

职责：读入 gold & pred，返回 `List[MetricResult]`。

```python
class MetricResult(BaseModel):
    name: str
    value: float
    pass_gate: bool

def evaluate(gold: Path, pred: Path, config: Config) -> List[MetricResult]:
    """
    1. 读 gold -> polars df_g
    2. 读 pred -> polars df_p
    3. 按 config.formula 计算指标
    4. 返回结果 + 是否通过
    """
```

公式示例（YAML 片段）：

```yaml
- name: attribution_accuracy
  formula: "(pl.col('pred_label') == pl.col('gold_label')).mean()"
  target: 0.75
  gate: true
  higher_is_better: true
```

---

### 4.3 gate.py

职责：接收 `List[MetricResult]`，任一 Gate 指标未通过 → exit(1)。

```python
def run_gate(results: List[MetricResult]) -> None:
    fails = [r for r in results if r.gate and not r.pass_gate]
    if fails:
        print_json(fails)
        sys.exit(1)
    sys.exit(0)
```

---

### 4.4 exporter.py

职责：  
1. `to_csv(results, raw_df, out: Path)` → 审查专家模板。  
2. `to_png(scatter_df, out: Path)` → 成本-效果散点图（matplotlib 300 dpi）。

---

### 4.5 7-Agent 归因任务分工（experiment/agent_roles.yaml）

| Agent | 模型 | 职责 | 输出字段 |
|-------|------|------|----------|
| A1 会话切分 | 弱 | 把 200 轮对话切成「催单子话题」 | `sub_topics[]` |
| A2 根因粗分类 | 弱 | 6 选 1 一级根因 | `level1` |
| A3 二级细化 | 弱 | 19 选 1 二级根因 | `level2` |
| A4 evidence 抽取 | 弱 | 从对话中 copy 原文片段 | `evidence[]` |
| A5 置信度打分 | 弱 | 0-1 分 | `confidence` |
| A6 冲突检查 | 弱 | 检查同一子话题内冲突标签 | `conflicts[]` |
| A7 汇总生成 | 强（大）| 综合以上，输出最终 `session_analysis` | 最终 pred.jsonl 结构 |

约定：  
- 弱模型统一用 7B 级本地模型，通过 DeepForge 插件 `local_llm` 部署。  
- 强模型用 GPT-4o-mini，通过 `openai_api` 插件，仅 A7 使用。  
- 所有 Agent 输出通过 Message Bus 汇总到「结果聚合器」，再写 `pred.jsonl`。

---

## 5. API / CLI 设计

| 命令 | 参数 | 输出 | 备注 |
|------|------|------|------|
| `deepforge metrics init` | – | 创建 `eval/metrics_config.yaml` 模板 | 首次用 |
| `deepforge metrics eval <gold> <pred>` | `--out metrics.json` | 写 metrics.json | 默认 eval/ 下 |
| `deepforge metrics gate` | `--metrics metrics.json` | exit 0/1 | CI 调用 |
| `deepforge metrics export-csv` | `--raw` | 原始样本+指标 | 审查专家 |
| `deepforge dashboard` | `--port 8080` | 启动 Node 服务 | 自动打开浏览器 |

REST（dashboard 内部）：  
`GET /api/metrics` → 返回 metrics.json 内容  
`GET /api/scatter` → 返回 cost-effectiveness 散点数据

---

## 6. 数据模型

### 6.1 gold.jsonl / pred.jsonl 单行 Schema

```json
{
  "session_id": "s_001",
  "level1": "物流",
  "level2": "快递延迟",
  "evidence": ["客服：您的包裹已到分拣中心"],
  "confidence": 0.92
}
```

### 6.2 metrics.json

```json
{
  "timestamp": "2025-06-05T12:00:00Z",
  "gold_sha256": "abc...",
  "pred_sha256": "def...",
  "results": [
    {"name": "attribution_accuracy", "value": 0.78, "pass_gate": true}
  ]
}
```

---

## 7. 编码任务拆解（可建 GitHub Issue）

| 序号 | 任务标题 | 涉及文件 | 实现要点 | 预计代码量 |
|------|----------|----------|----------|------------|
| 1 | 创建项目脚手架 | `pyproject.toml`, `Makefile`, `README.md` | 一键 `make install` 装出 `deepforge` 命令 | 50 行 |
| 2 | 指标配置模板 & Pydantic 模型 | `eval/metrics_config.yaml`, `config.py` | 用 `pydantic` 校验，支持公式字符串 | 80 行 |
| 3 | 评估引擎 polars 实现 | `engine.py` | 读 jsonl → polars → 计算 → 输出 MetricResult | 120 行 |
| 4 | Gate 脚本 | `gate.py` | 读 metrics.json → exit code & 打印失败项 | 40 行 |
| 5 | CLI 命令树 | `cli.py` | Typer 分组，复用以上模块 | 60 行 |
| 6 | CSV/PNG 导出 | `exporter.py` | 用 polars 写 CSV；matplotlib 画散点 | 100 行 |
| 7 | Dashboard 前端初始化 | `dashboard/package.json` | Vite + Vue3 + ECharts | 30 行 |
| 8 | Dashboard 指标卡片 & 散点图 | `MetricCard.vue`, `ScatterPlot.vue` | 调 `/api/metrics`, `/api/scatter` | 150 行 |
| 9 | Dashboard 后端代理 | `dashboard/server/middleware.ts` | 起 mock server，转发本地文件 | 40 行 |
| 10 | 7-Agent 任务编排脚本 | `scripts/run_7agent.py` | 读 `agent_roles.yaml` → DeepForge 启动 | 200 行 |
| 11 | 单 Agent 基线脚本 | `scripts/run_1agent.py` | 复现原 `auto_analysis.py` 逻辑，输出同格式 | 100 行 |
| 12 | 样本选择器 | `scripts/sample_selector.py` | 从 200 通随机选 100，写 `sample_ids.txt` | 50 行 |
| 13 | 人工标注模板生成 | `notebooks/make_gold_template.ipynb` | 输出待标注 Excel，双盲编号 | 1 份 |
| 14 | 单元测试 | `tests/test_*.py` | 覆盖 config、engine、gate | 150 行 |
| 15 | GitHub Actions CI | `.github/workflows/gate.yml` | 跑 `deepforge metrics gate` & comment | 60 行 |

总预计：~1 200 行 Python + 200 行 TypeScript，2 名工程师 1 周可交付。

---

## 8. 需要其他 Agent 协助

| 角色 | 任务 | 交付物 |
|------|------|--------|
| 审查专家 | 人工标注 50 条 gold 数据 | gold.jsonl & 标注指南 |
| 记忆守护者 | 把本设计文档归档到 `docs/adr/0001-architecture.md` | 版本记录 & 后续 diff |
| 产品经理 | 确认 7-Agent 分工是否满足「弱模型可胜任」 | 在 agent_roles.yaml 上签字 |

—— 架构师交付完毕，可直接开工。