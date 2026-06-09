# 统一知识系统 — 端到端测试用例

## 环境

- 后端: `http://localhost:7860` (python -m deepforge.web.server)
- 前端: `http://localhost:3001` (cd web && npm run dev)
- 模型: Qwen3.5-397B-A17B 或 DeepSeek-V4-Flash

## 测试用例

### T1: 写入知识（memorize add）

**输入**: `记住以后做页面背景都用深色，主色用 #1e1e2e`

**预期结果**:
- [ ] 聊天气泡显示确认消息（如 "已记住：页面背景用深色，主色 #1e1e2e"）
- [ ] thinking 指示器消失，输入框恢复可用
- [ ] 磁盘写入：`.deepforge/unified/entries/` 下新增 k_*.json 文件
- [ ] catalog.json 中 entries 数组新增一条

**验证命令**:
```bash
ls .deepforge/unified/entries/
cat .deepforge/unified/catalog.json | python -m json.tool | grep preview
```

---

### T2: 列出知识（memorize list）

**输入**: `列出我的记忆`

**预期结果**:
- [ ] 聊天气泡显示 "已记录 1 条知识：\n• 页面背景用深色..." 或类似
- [ ] 列表内容与 T1 写入的一致

---

### T3: 构建 + 知识召回

**输入**: `做一个简单的登录页面`

**预期结果**:
- [ ] Transcript 面板出现 "应用已有知识：页面背景用深色..." 条目
- [ ] 构建正常完成，右侧出现代码/预览
- [ ] 生成的 HTML 中背景为深色（#1e1e2e 或深色系）
- [ ] `.deepforge/signals/` 下出现 JSONL 文件，含 knowledge_used 字段

**验证命令**:
```bash
find .deepforge/signals -name "*.jsonl" -exec cat {} \;
```

---

### T4: 正面反馈 → stats 更新

**操作**: T3 构建完成后输入 `完美` 或 `太好了`

**预期结果**:
- [ ] 知识条目的 usage_count +1, success_count +1
- [ ] streak +1
- [ ] signals/ 下出现 type=user_feedback 的记录

**验证命令**:
```bash
cat .deepforge/unified/entries/k_*.json | python -m json.tool | grep -A5 stats
find .deepforge/signals -name "*.jsonl" -exec grep user_feedback {} \;
```

---

### T5: 负面反馈 → stats 更新

**操作**: 做一次构建后输入 `不对，这不是我要的` 或 `背景太亮了`

**预期结果**:
- [ ] 如果有 recalled knowledge，其 failure_count +1, streak 归零
- [ ] signals/ 下出现 signal=error 或 signal=unsatisfied 的记录

---

### T6: 删除知识

**输入**: `删掉关于深色的记忆`

**预期结果**:
- [ ] 聊天气泡显示 "已删除包含「深色」的知识。"
- [ ] entries/ 下对应文件消失
- [ ] catalog.json entries 数组变空

**验证命令**:
```bash
ls .deepforge/unified/entries/
cat .deepforge/unified/catalog.json | python -c "import json,sys; d=json.load(sys.stdin); print(f'entries: {len(d[\"entries\"])}')"
```

---

### T7: 空知识库构建

**前提**: T6 删除后知识库为空

**输入**: `做一个计算器`

**预期结果**:
- [ ] Transcript 中不出现 "应用已有知识" 条目
- [ ] 构建正常完成
- [ ] signals/ 中 knowledge_used 为空数组 []

---

### T8: Seed 使用计数

**验证**（任意构建完成后）:

```bash
cat .deepforge/unified/seeds/seed_build_general.json | python -c "
import json,sys
d=json.load(sys.stdin)
print(f'seed uses: {d[\"current\"][\"performance\"][\"uses\"]}')
print(f'seed text: {d[\"current\"][\"text\"][:50]}')
"
```

**预期**: uses > 0

---

### T9: 自动经验提炼

**验证**（构建完成后等待 5 秒）:

```bash
cat .deepforge/unified/catalog.json | python -c "
import json,sys
d=json.load(sys.stdin)
auto = [e for e in d['entries'] if e['source'] == 'auto']
print(f'auto entries: {len(auto)}')
for e in auto:
    print(f'  [{e[\"maturity\"]}] {e[\"preview\"]}')
"
```

**预期**: 如果模型判断有可提炼经验，出现 source=auto, maturity=observation 的条目。如果没有则 auto entries: 0（也是正确行为）。

---

### T10: 成熟度升级

**前提**: 某条知识被多次成功使用（需要多轮构建+正面反馈）

**验证**:
```bash
cat .deepforge/unified/entries/k_*.json | python -c "
import json,sys
for line in sys.stdin:
    pass  # read all
# 直接检查文件
import os
for f in os.listdir('.deepforge/unified/entries'):
    d = json.load(open(f'.deepforge/unified/entries/{f}'))
    print(f'{d[\"id\"]}: maturity={d[\"maturity\"]}, usage={d[\"stats\"][\"usage_count\"]}, success_rate={d[\"stats\"][\"success_count\"]/max(d[\"stats\"][\"usage_count\"],1):.2f}')
"
```

**预期**: 当 usage_count >= 3 且 success_rate > 0.6 时，observation 升级为 experience。当 usage_count >= 8 且 success_rate > 0.8 且 streak >= 3 时，升级为 pattern。

---

## 模型切换命令

```bash
# DeepSeek-V4-Flash
curl -s -X POST http://localhost:7860/api/settings \
  -H "Content-Type: application/json" \
  -d '{"model": "DeepSeek-V4-Flash", "api_key": "<YOUR_KEY>", "base_url": "http://api.example.com/v1"}'

# Qwen3.5-397B
curl -s -X POST http://localhost:7860/api/settings \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen3.5-397B-A17B", "api_key": "<YOUR_KEY>", "base_url": "<QWEN_ENDPOINT>"}'
```
