# DeepForge 改进日志

## 改进方向：让弱模型通过框架超越Claude Agent

---

### v0.1 基础框架（commit 613afc2 - 59267c2）
- 7 Agent串行pipeline
- 问题：只能生成文字，不能验证

### v0.2 迭代回退（commit 59267c2 - 08f83de）  
- 审查不通过回退工程师修改
- 问题：审查也是LLM猜测，不是真正运行

### v0.3 工程师prompt优化（commit 51582f3 - 0d2d4e5）
- "编码机器"极简prompt，弱模型不再写规划
- 效果：4/4极限测试通过
- 问题：产出物能生成但不一定能用

### v0.4 意图路由（commit dc4fd51 - 864625d）
- LLM分类意图（code/content/chat）
- 问题：关键词穷举太脆弱

### v0.5 Claude Code风格重构（commit 0878979）
- 单入口run()，模型自己决定
- 删除意图分类层
- 问题：简单任务走7-Agent太慢

### v0.6 快速路径（commit d7c7339）
- simple code直接走工程师跳过PM/PD/Arch
- 效果：Round 1+2 20/20通过
- 问题：高难度任务超时

### v0.7 并行架构（commit bd5f263）
- PM+PD并行，Crowd+Memory并行
- EventBus事件系统
- 效果：Round 3+4 高难度全过
- 问题：产出物能跑但质量不如Claude Agent

### v0.8 Tool-Calling Builder（commit b52cd88）← 当前
- Builder Agent带工具循环（写代码→运行→修复）
- CodeVerifier真正执行代码验证
- 进化闭环：失败教训注入prompt
- 效果：Round 5测试中...
- 待验证：是否能超越Claude Agent

---

## 待办
- [ ] 严格区分工具/记忆/Skill三层体系
- [ ] Skill自动匹配——已验证模板直接复用
- [ ] 记忆质量清洗——514条中有多少真正有用
- [ ] Builder工具调用稳定性（模型不一定能正确输出tool格式）
- [ ] 前端对接Builder的工具调用过程展示

### v0.9 3-Agent架构 + 分层缓存（commit 2a70ad6 - 173c2b4）
- 3个Agent：Builder（构建）+ Tester（全维度测试）+ Planner（任务拆解）
- 分层缓存召回系统（L1编译/L2热/L3索引/L4全文）
- ngram分词：7/7中文召回精确度
- 回归测试：5/6通过（番茄钟因Tester打回3轮超时）
- 效果：架构从500行→200行，9个Agent→3个
- 问题：Tester阈值可能过严导致超时
