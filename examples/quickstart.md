# DeepForge 快速开始

## 最快方式（3步）

### 1. 安装
```bash
cd /path/to/auto-agent
pip install -e .
```

### 2. 配置API Key
```bash
# DeepSeek（推荐，便宜好用）
export DEEPSEEK_API_KEY=sk-xxx

# 或者其他模型
export QWEN_API_KEY=sk-xxx
export GLM_API_KEY=xxx
export KIMI_API_KEY=sk-xxx
```

### 3. 使用
```bash
# 开发者用CLI
deepforge chat

# 小白用Web
pip install -e ".[web]"
deepforge web
# 浏览器打开 http://localhost:7860
```

## 配置文件方式

```bash
deepforge init
# 编辑 deepforge.yaml 填入API Key
deepforge chat
```

## 使用Ollama本地模型（免费）

```bash
# 先安装Ollama并下载模型
ollama pull qwen2.5:7b

# 修改配置
export DEEPFORGE_BASE_URL=http://localhost:11434/v1
export DEEPFORGE_MODEL=qwen2.5:7b
export DEEPFORGE_API_KEY=ollama

deepforge chat
```
