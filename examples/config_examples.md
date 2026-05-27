# DeepForge 配置示例

## 单模型配置（最简）
default_model:
  model: "deepseek-chat"
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com/v1"

## 多模型配置（按Agent分配）

下面的配置让不同Agent使用不同模型，优化成本和效果：

```yaml
# 简单任务用便宜模型
default_model:
  model: "glm-4-flash"
  api_key: "xxx"
  base_url: "https://open.bigmodel.cn/api/paas/v4"

# 复杂任务用强模型
models:
  strong:
    model: "deepseek-chat"
    api_key: "sk-xxx"
    base_url: "https://api.deepseek.com/v1"

# 关键Agent使用强模型
agents:
  project_manager:
    model: "strong"
  architect:
    model: "strong"
  engineer:
    model: "strong"
```

## Ollama本地模型

```yaml
default_model:
  model: "qwen2.5:7b"
  api_key: "ollama"
  base_url: "http://localhost:11434/v1"
```
