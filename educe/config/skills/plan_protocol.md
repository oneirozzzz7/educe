# Plan 协议 — 多步任务时按需注入
# 触发条件：action loop 第 3 轮仍无 plan 时，通过 challenge 注入

你在一个多轮循环中工作。每轮工具结果会返回给你继续处理。
多步任务时，在 action 前输出 plan 块追踪进度：

<plan>
goal: 总目标
findings:
  - 已发现的关键信息（累积，不丢旧发现）
done: 已完成步骤
next: 下一步
status: working | done
</plan>

status=done 表示任务完成，循环结束。简单问题无需 plan，直接回答。

示例：
<plan>
goal: 找出项目入口文件
findings:
  - src/ 下有 main.py 和 utils.py
done: 列出了 src/ 目录
next: 读 main.py 确认入口
status: working
</plan>
<action type="read_file">src/main.py</action>
