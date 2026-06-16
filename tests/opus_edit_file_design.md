# Opus 4.8 — edit_file 设计讨论


## Round 1 — 开发者

Educe 框架刚刚暴露了一个关键能力缺失：

实验：让 Educe（Qwen3.6-35B）修改自己的 page.tsx（739行），给示例按钮加描述文字。
结果：模型能正确找到文件、读取内容，但无法输出修改后的完整 739 行文件。卡住了。

根因：当前只有 write_file（全量覆盖），没有 edit_file（局部修改）。
弱模型的 output token 限制（4096）无法容纳完整大文件。

我需要设计一个 edit_file action，让弱模型能像 Claude Code 的 Edit 工具一样做局部修改。

关键设计问题：
1. edit_file 的输入格式应该是什么？（sed命令？diff patch？搜索替换？行号范围？）
2. 哪种格式对弱模型最友好（它容易生成正确的）？
3. 如何处理歧义（如果搜索文本匹配多处）？
4. 如何处理大文件（模型看不完整个文件时怎么定位修改点）？
5. 失败恢复：edit 失败了怎么办（原文不匹配等）？

请给出你的设计建议。参考 Claude Code 的 Edit 工具设计（old_string→new_string 搜索替换），但要考虑弱模型的特性（容易出错、格式不严格、context 有限）。

## Round 1 — Opus 4.8

# edit_file 设计建议（面向弱模型）

## 核心结论先行

**采用搜索替换（old_string → new_string），但要为弱模型做三层加固：容错匹配、强制唯一性、失败可诊断。** 不要用 diff/sed/行号。

---

## 1. 输入格式选型

| 格式 | 弱模型友好度 | 致命缺陷 |
|------|-------------|---------|
| diff/patch | ❌ 极差 | 需要精确行号 + @@ 上下文 + 行首 +/- 符号，弱模型几乎必错 |
| sed 命令 | ❌ 差 | 正则转义地狱，特殊字符 `/`、`.`、`*` 必爆 |
| 行号范围 | ⚠️ 中 | 模型无法可靠数行号，尤其大文件分块看时；插入/删除后行号全错 |
| **搜索替换** | ✅ 最好 | 唯一性问题（可解决） |

**搜索替换是唯一对弱模型可行的方案**——它只要求"复制一段我看到的文本"，这是弱模型最擅长的能力（抄写），而不是"计算"（行号）或"构造语法"（diff/正则）。

---

## 2. 推荐 Schema

```json
{
  "name": "edit_file",
  "input": {
    "path": "app/page.tsx",
    "old_string": "完整复制要替换的原文，含足够上下文",
    "new_string": "替换后的新内容",
    "occurrence": "first"   // 可选: "first"(默认) | "all" | 数字
  }
}
```

**关键约束（写进 prompt 和 tool description）：**
- `old_string` 必须**逐字符复制**原文（含缩进、空格）
- `old_string` 应包含**足够上下文使其唯一**（建议 ≥3 行）
- 一次只改一处；多处修改请多次调用

---

## 3. 歧义处理（匹配多处）

**默认严格模式 + 明确报错引导，而不是静默改第一个。**

```
匹配 0 处 → 报错，附带"最接近的候选"（见第5节）
匹配 1 处 → 执行
匹配 N 处 → 报错，要求增加上下文，并展示每处的行号+前后2行
```

报错示例（给模型看的）：
```
ERROR: old_string 在文件中匹配到 3 处，无法确定改哪个。
  位置1 (第 102 行): <button>示例</button>
  位置2 (第 245 行): <button>示例</button>
  位置3 (第 511 行): <button>示例</button>
请在 old_string 中加入更多上下文（如上一行或下一行）使其唯一，然后重试。
```

> 不要默认用 `occurrence: all`——弱模型对"批量影响"缺乏判断，容易误伤。

---

## 4. 大文件定位（模型看不全 739 行）

这是真正的关键问题。分两步走：

### 配套提供 `read_file` 的范围读 + grep 能力

```json
// 让模型先定位再编辑
{ "name": "search_in_file", "input": { "path": "...", "query": "示例" } }
// 返回: 行号 + 该行内容 + 前后各2行上下文
```

工作流变成：
```
1. search_in_file("示例按钮")  → 得到第 245 行附近代码块
2. read_file(path, start=240, end=255)  → 看清完整上下文
3. edit_file(old_string=那15行中唯一的一段, new_string=...)
```

**这样模型永远只需要处理几十行，而不是 739 行。** output token 限制问题自然消失——`old_string` + `new_string` 加起来通常 < 500 token。

---

## 5. 失败恢复（弱模型必然出错）

弱模型最常见的失败：**空格/缩进不一致、漏字符、自作主张改了原文**。设计要假设它一定会失败几次。

### 容错匹配（按严格度降级尝试）

```python
def match(content, old_string):
    # 第1级：精确匹配
    if old_string in content: return exact
    # 第2级：行尾空白归一化后匹配（最常见错误）
    if normalize_trailing_ws(old) in normalize(content): return fuzzy_ws
    # 第3级：每行 strip 后匹配（缩进错误）
    if strip_lines_match(): 
        return fuzzy_indent  # ⚠️ 用原文件的缩进，而非模型给的
    # 失败
    return suggest_closest()
```

> 缩进容错时，**采纳文件中的真实缩进**而非模型提供的——弱模型常把 tab/空格搞错。

### 失败时返回"可纠错"的信息

```
EDIT FAILED: 未找到精确匹配。
最相似的文件内容（第 245 行）：
    <button className="btn">示例</button>
            ^^^ 你提供的: <button className='btn'>示例</button>
差异：引号 ' vs "，请使用 read_file 重新确认原文后重试。
```

给出 **diff 高亮 + 具体修复建议**，弱模型靠这个能在第二轮纠正。

### 兜底：自动回退

- 编辑后**校验文件可解析**（如 tsx 跑一次 lint/parse），失败则自动回滚并报错
- 保留 `.bak`，提供 `undo_last_edit` action

---

## 总结：给弱模型的三条护栏

1. **只让它抄写，不让它计算**（搜索替换 > 行号/diff）
2. **先搜索后编辑**（search_in_file 解决大文件 + token 限制，这是你实验卡住的真正解药）
3. **假设它会错，把错误变成可纠正的反馈**（容错匹配 + 唯一性强制 + diff 报错 + 自动回滚）

最小落地顺序：`search_in_file` → `edit_file(精确匹配+唯一性检查)` → 加空白容错 → 加 diff 报错 → 加回滚。前两步就能解掉你当前的核心阻塞。

## Round 2 — 开发者

你的设计很好。追问几点：

a) 弱模型容易把 old_string 写错（多/少空格、缩进不对）。怎么做容错？模糊匹配？strip后比较？

b) 如果文件很大（500+行），模型可能记不住文件内容（read_file 输出被截断）。
   是否需要一个'查看文件片段'的能力（如 read_file_lines 100-120）？

c) Claude Code 的 Edit 要求 old_string 在文件中唯一。但弱模型经常给出太短的 old_string 导致不唯一。
   策略：要求更长的上下文？还是加行号辅助？还是自动扩展匹配？

d) Markdown-native 格式设计：当前 write_file 用 ```write_file\npath: xxx\n---\ncontent```。
   edit_file 应该用什么格式？考虑弱模型的自然输出习惯。

## Round 2 — Opus 4.8

# 深入设计：四个追问

## a) old_string 容错：分级匹配策略

**核心原则：保留必要的精确性（防误伤），但对"无意义差异"宽容。**

空白差异分两类，要区别对待：
- **无意义空白**：行尾空格、文件末尾换行、CRLF vs LF → 直接归一化
- **有意义空白**：行首缩进 → **谨慎容错**（Python 里缩进是语义；JSX 里不是）

### 分级匹配管线

```python
def find_match(content, old_string):
    # Level 0: 精确匹配
    if (idx := content.find(old_string)) != -1:
        return Match(idx, "exact", confidence=1.0)

    # Level 1: 行尾空白 + 换行符归一化（最高频错误，几乎无风险）
    c_norm = normalize_eol_and_trailing(content)
    o_norm = normalize_eol_and_trailing(old_string)
    if (idx := c_norm.find(o_norm)) != -1:
        return Match(map_back(idx), "trailing_ws", confidence=0.95)

    # Level 2: 逐行 strip 后比较（缩进容错，有风险，需校验）
    matches = match_by_stripped_lines(content, old_string)
    if len(matches) == 1:
        return Match(matches[0], "indent_fuzzy", confidence=0.7,
                     # ⚠️ 关键：用文件真实缩进重建，丢弃模型给的缩进
                     rebuilt_old=use_file_indent(matches[0]))

    # Level 3: 失败，进入诊断
    return suggest_closest(content, old_string)
```

### 三条铁律

1. **缩进容错时，永远采用文件的真实缩进**，模型提供的缩进只用于"内容比对"，不用于"重建"。否则会把对齐改坏。
2. **容错命中后降低 confidence，触发额外校验**（如 parse 检查）。Level 2 的修改建议自动跑一次语法校验再落盘。
3. **不做"相似度模糊匹配"（如编辑距离 fuzzy）**——这会让 `<button>A</button>` 误匹配 `<button>B</button>`，比报错更危险。模糊只限于"空白"，不及于"字符内容"。

---

## b) 大文件：必须有片段读 + 定位能力（这是你实验卡住的根因）

**结论：需要，而且是整套设计的地基。** read_file 全量截断正是模型"记不住"的来源。

### 提供两个互补 action

```
read_lines(path, start, end)      # 按行号读片段，行号一起返回
search_in_file(path, query)       # 关键词定位，返回所有命中行号+上下文
```

**read_lines 必须带行号前缀输出**，这让模型建立"位置感"：

```
242 |   <div className="examples">
243 |     <button className="btn">示例</button>
244 |     <button className="btn">示例2</button>
245 |   </div>
```

> 注意：行号只用于**人/模型阅读和定位**，**不进入 edit_file 的输入**。edit_file 仍然只吃 old_string/new_string（见 c 节）。行号是"导航工具"，不是"编辑坐标"。

### 推荐工作流（强制写进 system prompt）

```
处理大文件三步法：
1. search_in_file 找到目标大概在哪 → 得到行号 N
2. read_lines(path, N-5, N+10) 看清局部上下文
3. 从看到的片段里复制一段唯一文本作为 old_string，edit_file
```

这套流程下，模型每次处理 < 20 行，**output token 限制问题、记不住问题、定位问题一次性全解**。

---

## c) 唯一性：要求长上下文 + 自动诊断引导，不要加行号辅助

三个候选方案的评估：

| 方案 | 评价 |
|------|------|
| 加行号辅助（old_string 里带行号） | ❌ 否决。行号让模型必须精确数行，且增删后失效，把"抄写"任务又变回"计算"任务 |
| 自动扩展匹配（系统自动向外扩上下文） | ❌ 否决。系统不知道模型想改哪一个，扩了也是瞎猜 |
| **要求更长上下文 + 报错引导重试** | ✅ 采用。符合"只让模型抄写"原则 |

### 具体策略：让"唯一性"成为模型可学习的反馈循环

**第一次不唯一时，不要只说"失败"，要展示每一处并教它怎么改：**

```
ERROR: old_string 匹配到 3 处。请加入上下文使其唯一。

  ▶ 处1 (242-243 行):
      <div className="examples">
      <button className="btn">示例</button>   ← 候选
  ▶ 处2 (244 行):
      <button className="btn">示例2</button>  ← 候选
  ▶ 处3 (511 行):
      <button className="btn">示例</button>   ← 候选

建议：把上一行或下一行一起复制进 old_string。
例如改处1，可用：
  <div className="examples">
    <button className="btn">示例</button>
```

**直接给出一个可用的扩展示例**，弱模型照抄就能成功。这比任何"规则说明"都有效。

### 防御性默认值

- tool description 里**默认要求 old_string ≥ 3 行**
- 如果模型给了单行且不唯一 → 自动触发上面的引导
- 配合 b) 的 read_lines（带行号上下文），模型很容易抄到"上下行"

---

## d) Markdown-native 格式：用代码块包裹，结构对称于 write_file

弱模型的输出习惯：**会写 markdown 代码块，但对"嵌套分隔符"很脆弱**。难点在于 old_string / new_string 本身可能含 `---`、`` ``` ``、`:` 等字符，会破坏分隔。

### 推荐格式（鲜明分隔符 + 显式段标记）

```
```edit_file
path: app/page.tsx
<<<<<<< OLD
    <button className="btn">示例</button>
=======
    <button className="btn" title="点我看示例">示例</button>
>>>>>>> NEW
```
```

选择理由：
- `<<<<<<< OLD` / `=======` / `>>>>>>> NEW` 是 **git conflict 标记**，大量出现在训练数据里，弱模型见过、能稳定生成
- 比 `---` 更**抗冲突**：代码内容里几乎不会出现连续 7 个 `<<<<<<<`
- 段落语义明确（OLD/NEW），比纯分隔符不易搞反方向

### 但要为弱模型加解析容错

实测弱模型常见变体，解析器都要兼容：
- 标记符数量不对（`<<<<` 或 `<<<<<<<<`）→ 用正则 `<{3,} ?OLD` 宽松匹配
- 漏掉 `path:` → 回退到"当前打开文件"或报错要求补全
- 把 OLD/NEW 写反 → 难自动判断，但若 OLD 匹配失败而 NEW 能匹配，提示"是否写反了"
- 用

## Round 3 — 开发者

最后一个问题：实现优先级。

方案 A（最简单）：搜索替换，exact match，失败就报错让模型重试。
方案 B（中等）：搜索替换 + 模糊匹配（strip/忽略空行）+ 行号范围读取。
方案 C（完整）：搜索替换 + 模糊匹配 + 行号读取 + 多处替换 + diff预览。

对弱模型（Qwen3.6-35B），你推荐先做哪个方案？
以及：从'搜索替换'到'让弱模型达到 Claude Code 水平'，还差什么关键能力？
只回答核心观点，不超过 15 句话。

## Round 3 — Opus 4.8

# 实现优先级

**先做方案 B，但拆成两步落地。**

1. **第一步（解你当前阻塞）**：搜索替换 exact match + `read_lines` + `search_in_file`。前两个 action 是你实验卡住的真正解药——不是 edit 缺失，是"定位+片段读"缺失。这步就能跑通你的实验。

2. **第二步（提良率）**：加空白/缩进模糊匹配 + 唯一性报错引导。这是弱模型从"偶尔成功"到"稳定成功"的关键，性价比最高。

**不要先做方案 C 的多处替换和 diff 预览**：多处替换对弱模型是风险源（误伤），diff 预览对 35B 收益有限（它看不太懂 diff）。等良率上来后再加。

# 从搜索替换到 Claude Code 水平，还差什么

3. **闭环验证能力**：编辑后自动跑 lint/parse/test，把结果喂回模型——让它"看到后果"并自我纠正。这是 Claude Code 最核心的差距，不是工具多，是**反馈回路**。

4. **任务规划与分解能力**：弱模型不会自发"先搜索→再读→再改"，需要把工作流固化进 prompt 或用脚手架强制编排。

5. **跨文件上下文管理**：知道改一处要连带改哪些引用——这依赖代码理解力，35B 上限明显，短期靠工具（grep 引用）补，长期靠模型本身。

**一句话总结**：工具补齐到方案 B 就够用，真正的天花板是**反馈闭环 + 编排脚手架**——用工程把弱模型的"判断力缺陷"兜住，而不是堆更多 action。
