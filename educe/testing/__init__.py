"""
Educe Integration Test Framework

分层深度测试：每步 action → observe → verify（格式+内容+美观+日志）
不硬编码：YAML 合同声明，引擎通用执行。

Usage:
    python -m educe.testing                    # 跑所有 contracts
    python -m educe.testing --layer logic      # 只跑逻辑层验证
    python -m educe.testing --scenario file_reference  # 单场景
    python -m educe.testing --full             # 全维度（含美观度 judge）
"""
