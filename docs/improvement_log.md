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

### v1.0 四项优化 + 完整对比测试（commit b4d78c5）
- Tester轻量化：工具快速检查替代LLM全维度审查
- Tester打回上限1次：避免无限循环超时
- Builder输出稳定性：强制完整代码文件
- Builder超时150s
- 测试结果：10/10 (100%)，avg 83s（从142s降41%）
- 对比Claude Agent：通过率持平，速度差3x，产出物更大，成本低10x
- 关键洞察：DeepForge的价值不是"比Claude快"，而是"用弱模型+低成本达到同等效果"

### v1.1 CSS变量+动画prompt + 四项优化效果验证（commit 2c4e477）
- CSS变量：0 → 12-15个（:root变量系统生效）
- CSS动画：0 → 4个@keyframes（动效生效）
- 速度：avg 48s（从142s降66%，从83s再降42%）
- 原因：工具快速检查通过直接跳过LLM Tester
- 评分：达到Claude Agent代码级水平（18-20/20）
- 仍存在UI问题：布局靠下、无中间过程、无预览、无时间戳（记入待办33）

### v1.2 品牌级UI重设计完成（commit 775c535 - 4a8ea9a）
- 6个React组件拆分（ThemeProvider/Sidebar/TopBar/WorkCard/SettingsModal/Logo）
- 双主题CSS变量系统（浅色/暗色切换，localStorage持久化）
- 品牌Logo SVG（淬炼晶体概念）
- 侧栏：任务历史+新建+主题切换
- WorkCard：进度步骤+耗时+预览iframe+代码查看
- 时间戳、消息布局、输入框品牌样式
- 2048游戏端到端验证：生成+预览+可玩

### v1.3 自进化引擎v2——五层闭环
- 五层架构：检测(弱模型)→诊断(规则)→修复(知识追加)→验证(A/B对比)→沉淀(L1编译)
- 检测层：14种测试任务×8维度评分（doctype/closing/css_vars/animation/responsive/error_handling/size）
- 诊断层：规则引擎分类（timeout/no_output/truncated/quality_gap/all_good）
- 修复层：安全约束——只追加知识不修改代码（append-only）
- 验证层：A/B对比，修复前后同任务重跑对比分数
- 沉淀层：改进确认后编译进L1热知识
- 记忆裁剪：LayeredCache.prune()按价值排序保留top-N，merge_duplicates()合并相似条目
- 进化统计API：/api/evolution 端点返回实时进化数据
- 安全：不修改框架核心代码，只通过知识追加影响模型行为

### v1.4 自进化嵌入框架——用户侧无感知
- 进化触发：每次任务完成后 asyncio.create_task() 后台静默执行
- 用户无感知：不弹窗、不阻塞、不额外交互
- 数据隔离：所有进化数据存用户本地 .deepforge/（知识库+日志）
- 可开关：config.evolution.enabled（默认开启），settings-modal开关切换
- 配置持久化：.env DEEPFORGE_EVOLUTION=true/false
- 核心逻辑抽离：deepforge/core/evolution.py 纯函数式，不依赖Orchestrator
- 记忆防膨胀：知识>1000条时自动裁剪+去重

### v1.5 UI体验打磨（18项全部完成）
- **渲染引擎**：react-markdown全格式支持(标题/粗体/列表/代码块/表格/引用/链接)
  - ```filepath:xxx 自动转换为标准语言标签
  - 代码块独立复制按钮+语言标签
  - try/catch兜底：任何格式永不渲染崩溃，降级为纯文本
  - 内嵌HTML自动检测+预览iframe
- **复制按钮**：hover显示一键复制全文（助手消息+WorkCard代码）
- **长内容滚动**：>500字符限高600px+可滚动
- **WorkCard升级**：
  - Agent图标+实时耗时+文件大小
  - 预览/代码/复制/下载四按钮，选中态品牌色高亮
  - 新窗口按钮醒目化（品牌色背景）
  - 代码完整展示（不限5000字）
  - iframe sandbox安全属性
- **品牌Logo v2**：晶体纹理+发光滤镜+火花渐变+SVG Favicon
- **Sidebar升级**：
  - 历史任务回看产出物（加载engineer_output+代码预览）
  - 任务时间戳+刷新按钮+loading态
  - 展示20条历史
- **稳定性**：智能滚动、移动端响应式、iframe键盘聚焦
- **HTML提取修复**：```html/```htm代码块格式支持
