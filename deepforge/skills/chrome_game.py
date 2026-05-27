from __future__ import annotations

"""
Chrome小游戏扩展 Demo Skill
一键生成可玩的Chrome小游戏扩展——DeepForge的标志性Demo

用法：
  deepforge run "做一个像素风跑酷小游戏"
  deepforge run "做一个贪吃蛇游戏Chrome扩展"
"""

SKILL_CONFIG = {
    "name": "chrome_game_extension",
    "description": "一句话生成可玩的Chrome小游戏扩展（DeepForge标志性Demo）",
    "version": "1.0.0",
    "tags": ["chrome", "extension", "game", "demo", "showcase"],
    "pipeline": [
        "project_manager",
        "product_manager",
        "architect",
        "engineer",
        "reviewer",
        "crowd_user",
        "memory_keeper",
    ],
    "prompt_template": "帮我做一个Chrome浏览器扩展小游戏：{description}，要求可以直接加载到Chrome使用",
}


GAME_DESIGN_PROMPT = """你是游戏设计专家。用户想要一个Chrome扩展小游戏。

请设计：
1. 游戏核心机制（2-3个核心玩法）
2. 操作方式（键盘/鼠标）
3. 计分规则
4. 游戏结束条件
5. 视觉风格建议

游戏必须：
- 单HTML文件内完成（Canvas或DOM）
- 无外部依赖
- 60fps流畅运行
- 适合在浏览器扩展popup中玩（400x600尺寸）"""


EXTENSION_ARCHITECTURE = """Chrome扩展项目结构：

```
game-extension/
├── manifest.json          # Chrome扩展配置（Manifest V3）
├── popup.html             # 游戏主页面
├── popup.js               # 游戏逻辑（纯JS，无框架）
├── popup.css              # 样式
├── icons/
│   ├── icon16.png         # 16x16图标（可用emoji替代）
│   ├── icon48.png
│   └── icon128.png
└── README.md              # 安装说明
```

manifest.json 模板：
```json
{
  "manifest_version": 3,
  "name": "游戏名称",
  "version": "1.0",
  "description": "游戏描述",
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "permissions": []
}
```

技术约束：
- Manifest V3（Chrome最新标准）
- 零外部依赖
- 单文件游戏逻辑（popup.js）
- Canvas 2D绘图
- 本地存储高分（chrome.storage.local）"""
