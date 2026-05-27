# PRD  
DeepForge 可量化成功指标系统 v0.1  
（仅供内部验证“7 弱 >1 强”实验使用）

---

## 1. 产品概述
- **是什么**：一套内嵌在 DeepForge 实验流程中的「可量化成功指标」模块，负责自动采集、计算、判定并可视化核心指标，确保实验结果可信、可复现、可 Gate。
- **解决什么问题**：
  1. 实验同学手动统计耗时且口径不一致；
  2. 没有统一 Gate 标准，导致结论争议；
  3. 无法实时看到“7 弱 vs 1 强”差距，拖慢决策。
- **目标用户**：
  - 主用户：DeepForge 实验团队（架构师/工程师/审查专家）
  - 次要：社区贡献者、投资人 Demo 观众

---

## 2. 核心功能列表（MoSCoW→P0/P1/P2）

| 优先级 | 功能名称 | 功能描述（一句话） | 用户价值 |
|--------|----------|--------------------|----------|
| P0 | 指标元数据管理 | 在代码仓集中定义所有指标公式、目标值、Gate 标志；支持版本控制 | 保证口径一致，可审计 |
| P0 | 自动采样&计算 | 实验跑完后自动读取 `evaluation/*.json` → 输出 `metrics.json` | 0 手工统计，防作弊 |
| P0 | Gate 判定 | 若任一 Gate 指标未达标，CI 立即 fail，并comment 到 PR | 结论可信，阻塞 premature release |
| P0 | 实时看板 | 本地启动 `deepforge dashboard` → 浏览器看「7 弱 vs 1 强」差距 | 实验同学秒级决策 |
| P1 | 成本-效果散点图 | 展示「准确率↑成本→」二维图，支持拖动阈值 | 一眼锁定帕累托最优 |
| P1 | 指标导出CSV | 一键下载全部原始指标，方便 Excel/Jupyter 二次分析 | 审查专家做显著性检验 |
| P2 | 指标告警Webhook | 指标异常时飞书/Slack 通知 | 异步协作，无需盯盘 |

---

## 3. 用户故事（精选）

1. 作为**实验工程师**，我想要跑完脚本后 10 秒内看到 Gate 结果，以便不过度占用 GPU 机时。
2. 作为**审查专家**，我想要自动导出的 CSV 包含每条样本的 pred/gold/evidence，以便我直接跑显著性检验。
3. 作为**产品经理**，我想要在 README 中贴一张「成本-效果散点图」GIF，以便向社区证明 7 弱模型优势。
4. 作为**社区贡献者**，我想要在提交 PR 时立即看到指标 Gate 状态，以便我知道是否破坏 baseline。
5. 作为**投资人**，我想要 2 分钟一键安装后看到实时看板，以便快速决策是否跟进投资。

---

## 4. 界面/交互设计

### 4.1 CLI 命令结构
```bash
deepforge metrics init          # 生成指标定义模板 eval/metrics_config.yaml
deepforge metrics eval <gold.jsonl> <pred.jsonl>   # 计算并写 metrics.json
deepforge metrics gate          # 返回 0/1，供 CI 调用
deepforge dashboard             # 本地启动 8080 端口可视化
```

### 4.2 关键交互流程（正常流）
1. 工程师跑完 `python run_7agent.py` → 产出 `pred.jsonl`
2. 系统自动触发 `deepforge metrics eval` → 生成 `metrics.json`
3. CI 调用 `deepforge metrics gate`
   - 全部 Gate 通过 → 绿灯合并
   - 任一 Gate 失败 → PR comment 明细+阻塞合并
4. 本地调试时执行 `deepforge dashboard` → 浏览器打开 `http://localhost:8080`

### 4.3 看板页面结构（单页应用）
- 顶部横幅：实验名称 + 时间戳 + Pass/Fail 徽章
- 指标卡片区（两栏）
  - 左：准确性相关（准确率、过度标注率、漏标率...）
  - 右：效率相关（token、耗时、USD 成本）
- 成本-效果散点图（可拖动横竖线设定阈值）
- 样本抽查表格（随机 20 条，支持 search & evidence 弹窗）

---

## 5. 验收标准（可测试）

| 功能 | 验收条件（必须全部可自动化） |
|------|------------------------------|
| 指标元数据管理 | 新增指标只需改 `eval/metrics_config.yaml`，单测覆盖 100% |
| 自动采样&计算 | 1000 条样本 ≤5 秒输出完整 metrics.json；与手工计算 diff <1e-4 |
| Gate 判定 | 在 GitHub Actions 中，fail 时 PR 出现 `/gate-failed` comment 并 block merge |
| 实时看板 | 本地 `deepforge dashboard` 启动 ≤3 秒；所有指标与 `metrics.json` 数值一致 |
| 成本-效果散点图 | 拖动阈值后，图表刷新 ≤200 ms；支持导出 PNG |
| CSV 导出 | 字段顺序与审查专家模板 1:1 对应；打开无乱码 |
| 告警 Webhook | 飞书群 5 秒内收到消息；消息包含超链接直达看板 |

---

## 6. 非功能性需求

| 维度 | 要求 |
|------|------|
| 性能 | 单条样本指标计算 ≤5 ms；看板首屏加载 ≤1 s（1000 条样本） |
| 兼容 | 支持 Python 3.8-3.12；无系统级依赖（纯 Python+Node 可选） |
| 安全 | 仅读取实验输出目录，不写系统其他路径；前端 CSP 禁止内联脚本 |
| 可维护 | 指标公式与代码分离（YAML），新增指标代码改动 ≤5 行 |
| 开源合规 | 依赖包全部 OSI 认可许可证；附 `LICENSE-3rdparty.csv` |

---

## 7. 附录 A：指标定义表（可直接粘贴到文档）

| 指标 | 定义 | 计算公式 | 目标值 | Gate? | 测量方法 |
|------|------|----------|--------|-------|----------|
| 归因准确率 | 预测归因标签与人工 gold 完全一致的比例 | correct / total | ≥75 % | 是 | 自动，eval.py |
| 过度标注率 | gold 无标签但预测有标签的比例 | fp / (tn+fp) | ≤10 % | 是 | 同上 |
| 漏标率 | gold 有标签但预测无标签的比例 | fn / (tp+fn) | ≤15 % | 是 | 同上 |
| 万金油归因率 | 预测为「其他/未知」的比例 | other / total | ≤20 % | 否 | 同上 |
| evidence 完整率 | 预测给出可点击原文片段且能定位的比例 | valid_evidence / total | ≥90 % | 否 | 同上 |
| 平均 token 消耗 | 单样本 7-Agent 总 token 数 | sum(tokens) / n | ≤1.5× 单 Agent | 是 | 自动，meter.py |
| 平均耗时 | 单样本 wall time | sum(time) / n | ≤60 s | 否 | 同上 |
| 一键安装时长 | `pip install deepforge && deepforge demo` 到看板出现 | stopwatch | ≤120 s | 是 | 手工+录屏 |
| 新手上手时间 | 未接触用户按 README 跑通 10 条样本所需时间 | 问卷自报 | ≤15 min | 否 | 问卷 |

---

## 8. 需要其他 Agent 协助

1. **架构师** ➜ 在 `eval/` 目录预留钩子，确保跑 7-Agent/1-Agent 都能统一输出 `pred.jsonl` 格式。
2. **工程师** ➜ 实现 `deepforge metrics*` CLI 与看板前端；CI 里集成 Gate 脚本。
3. **审查专家** ➜ 提供 gold 数据集 100 条并 double check 指标公式。
4. **记忆守护者** ➜ 把本 PRD 归档至 `docs/prd/` 并建立版本记录。

—— 结束 ——