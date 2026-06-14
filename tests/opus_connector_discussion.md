# 连接万物讨论

# 关于 Educe "连接万物" 的思考

先说结论性的判断，再展开：**改名值得做，但不是现在最重要的事；"连接万物"的真正难点不在抽象层，而在认知层——如何让弱模型不被淹没。**

---

## 1. "连接万物"的本质理解

我认为你在直觉上想做的事，比"给工具改名"深刻得多。让我帮你把它说清楚。

**Tool 的隐喻是"手"——模型伸手去拿一个东西用。**
**Connector 的隐喻应该是"感官 + 肢体"——模型把自己延伸到外部世界。**

但这里有个陷阱。如果"连接万物"最后变成"注册了 50 个工具"，那它和 Tool 没有本质区别，只是数量变多——而**数量变多对弱模型是负面的**。

真正的"连接万物"应该是：

> **框架替模型管理"世界的复杂度"，让模型只面对"意图"，不面对"协议"。**

举个例子：
- Tool 思维：模型需要知道有 `read_file`、`write_file`、`http_get`、`db_query`、`git_commit`……
- Connector 思维：模型知道有"文件系统"、"这个 API"、"这个数据库"，而每个连接器**自己描述自己能做什么**，并在被需要时才展开细节。

**本质是从"扁平的能力列表"变成"分层的世界模型"。** 模型先选择"连接到哪个世界"，再在那个世界里行动。这正好契合你的哲学——不替模型思考，但创造"更清晰的判断结构"。

---

## 2. 是否改名，以及怎么改

**我的建议：改，但分两步走，且不要一刀切。**

### 关键洞察：Tool 和 Connector 不是同一个东西，不该互相替换

我反对简单的 `Tool → Connector` 重命名。因为它们的粒度不同：

| 概念 | 粒度 | 例子 |
|------|------|------|
| **Connector** | 一个"外部世界" | filesystem、github、postgres、某个 MCP server |
| **Capability / Action** | 世界里的一个动作 | read_file、create_issue、query |

也就是说：

```
Connector (filesystem)
  ├── read_file
  ├── write_file
  └── list_dir

Connector (github)
  ├── create_issue
  ├── list_prs
  └── comment
```

你现有的 `ToolDef` 其实是 **Capability** 级别的。所以正确的演进不是改名，而是**新增一层**：把散落的 capability 归拢到 connector 下面。

### 改名方案

- 保留 `use_tool` action 作为**别名兼容**（用户习惯、弱模型已学会），底层映射到新机制。**不要破坏已有用户习惯**——这违背你的约束。
- 对外叙事层（文档、官网、prompt 的引导语）用 "Connector"。
- 代码层可以叫 `Connector` + `Capability`，但 action 名保持 `use_tool` 或增加 `connect` 作为新动作。

**结论：改的是"心智模型"和"分层结构"，不是字符串替换。**

---

## 3. 架构建议

```
┌─────────────────────────────────────────┐
│  Model (看到的世界)                       │
│  - 一份"连接器清单"（精简描述）            │
│  - 按需展开某个连接器的详细能力            │
└─────────────────────────────────────────┘
              │ intent
┌─────────────▼───────────────────────────┐
│  ConnectorRegistry (路由层)               │
│  - 发现 (discover)                        │
│  - 描述 (describe, 两级：概要/详细)       │
│  - 路由 (route intent → connector)        │
└─────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│  Connector (统一接口)                     │
│  - manifest(): 我是谁、我能干什么          │
│  - capabilities(): 详细能力列表            │
│  - invoke(capability, params)             │
└─────────────────────────────────────────┘
              │ adapters
┌──────┬──────┬──────┬──────┬──────────────┐
│ FS   │ HTTP │ MCP  │ Shell│ DB / Git ... │
└──────┴──────┴──────┴──────┴──────────────┘
```

### 三个核心机制

**(a) 两级描述（这是对弱模型最关键的设计）**

不要把所有 capability 一次性塞进 system prompt。改为：

- **Level 1（常驻 prompt）**：连接器清单，每个一行。
  ```
  可用连接器：
  - filesystem: 读写本地文件
  - github: 操作 GitHub 仓库（issue/PR/代码）
  - db_main: 查询主数据库（只读）
  ```
- **Level 2（按需注入）**：模型说"我要用 github"时，框架才注入 github 的详细 capability 和参数 schema。

这就是你框架哲学的完美体现：**创造条件（清晰的两级结构），让模型做更好判断（先选世界，再选动作）。** 弱模型在 5 个连接器里选 1 个，比在 50 个工具里选 1 个，准确率高得多。

**(b) 统一的 Connector 接口**

```python
class Connector(ABC):
    name: str
    summary: str  # Level 1 描述，一句话

    @abstractmethod
    def capabilities(self) -> list[Capability]: ...  # Level 2

    @abstractmethod
    def invoke(self, capability: str, params: dict) -> Result: ...

    def health(self) -> bool: ...  # 连接是否可用
```

MCP、HTTP、FS、DB 全部实现这个接口。`ToolRegistry` 现有逻辑变成 `BuiltinConnector` / `ScriptConnector` 的实现。

**(c) 路由 = 不需要复杂路由**

不要做语义路由（让模型自然语言→自动选工具）。那会引入不确定性，对弱模型反而是灾难。**让模型显式选择**：先选 connector，再选 capability。显式 > 智能。

### 调用语法演进

```xml
<!-- 兼容旧的（保留） -->
<action type="use_tool" name="read_file">...</action>

<!-- 新的（鼓励，但等价） -->
<action type="connect" to="github" do="create_issue">
  {"title": "...", "body": "..."}
</action>
```

---

## 4. 优先级排序

判断标准：**哪个最能证明"框架管理复杂度"的价值，而不是"功能多"。**

| 优先级 | Connector | 理由 |
|--------|-----------|------|
| **P0** | **重构现有 → Connector 分层 + 两级描述** | 不加新功能，先验证心智模型。这是地基。 |
| **P0** | **MCP** | 见下节，这是"连接万物"的杠杆点 |
| **P1** | **Git** | 高频、闭环价值强（改代码→提交），弱模型友好（动作明确） |
| **P1** | **HTTP API（已有，升级）** | 通用性最强，万物皆可包成 API |
| **P2** | **数据库（只读优先）** | 价值高但危险，先只读 |
| **P2** | **浏览器** | 价值高但复杂、不稳定，对弱模型困难（页面状态太多） |
| **P3** | **连接其他 AI 模型** | 有趣但属于"编排"范畴，建议另立系统，别混进 connector |

**特别提醒**：连接"其他 AI 模型"在概念上不属于 Connector——它是 Agent 编排/委派，应该是 Educe 的另一个支柱。混进来会污染"连接外部世界"的清晰隐喻。

---

## 5. MCP 怎么接入 & 它的价值

**MCP 的价值用一句话说清：它让"连接万物"从"你的框架要一个个适配"变成"生态帮你适配"。**

你不可能自己写完 GitHub、Slack、Notion、Postgres……所有 connector。但 MCP 已经有了大量现成 server。接入 MCP = 接入整个生态。

**MCP 完美契合你的两级架构**：
- 一个 MCP server 天然就是一个 **Connector**
- MCP server 的 tools 天然就是 **Capabilities**
- MCP 的 `tools/list` 天然就是你的 `capabilities()`

```python
class MCPConnector(Connector):
    def __init__(self, server_url):
        self.client = MCPClient(server_url)
        self.name = ...  # 从 server 元信息