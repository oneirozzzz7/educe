"""
内置Skill模板库
覆盖用户最常用的产品类型
"""

BUILTIN_SKILLS = [
    {
        "name": "static_website",
        "description": "创建静态网站/个人主页/Landing Page",
        "tags": ["web", "html", "website", "网站", "主页", "landing", "portfolio", "博客"],
        "pipeline": ["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user"],
        "prompt_template": "做一个{description}，要求：单HTML文件、响应式设计、暗色/亮色主题、现代简约风格",
    },
    {
        "name": "data_dashboard",
        "description": "数据可视化看板/分析报告页面",
        "tags": ["data", "dashboard", "chart", "数据", "图表", "看板", "visualization", "analytics"],
        "pipeline": ["project_manager", "architect", "engineer", "reviewer"],
        "prompt_template": "做一个{description}数据看板，要求：单HTML文件、内置示例数据、支持图表（用Canvas或SVG绘制，不依赖外部库）、暗色主题",
    },
    {
        "name": "form_tool",
        "description": "表单工具/问卷/计算器",
        "tags": ["form", "calculator", "计算器", "表单", "问卷", "survey", "tool", "工具"],
        "pipeline": ["project_manager", "engineer", "reviewer"],
        "prompt_template": "做一个{description}，要求：单HTML文件、输入验证、结果实时计算显示、支持导出",
    },
    {
        "name": "text_processor",
        "description": "文本处理工具（JSON/Markdown/CSV格式化、编码转换等）",
        "tags": ["text", "json", "markdown", "csv", "format", "格式化", "转换", "编辑器", "converter"],
        "pipeline": ["project_manager", "engineer", "reviewer"],
        "prompt_template": "做一个{description}，要求：单HTML文件、左右分栏（输入/输出）、实时处理、支持复制结果、暗色主题",
    },
    {
        "name": "mini_game",
        "description": "网页小游戏（贪吃蛇/俄罗斯方块/打砖块等）",
        "tags": ["game", "游戏", "canvas", "贪吃蛇", "俄罗斯方块", "打砖块"],
        "pipeline": ["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user"],
        "prompt_template": "做一个{description}网页游戏，要求：单HTML文件、Canvas绘制、键盘控制、计分系统、60fps流畅、暗色风格",
    },
    {
        "name": "chrome_extension",
        "description": "Chrome浏览器扩展",
        "tags": ["chrome", "extension", "扩展", "插件", "browser", "plugin"],
        "pipeline": ["project_manager", "product_manager", "architect", "engineer", "reviewer", "crowd_user"],
        "prompt_template": "做一个{description}Chrome浏览器扩展，要求：Manifest V3、零外部依赖、popup交互界面",
    },
    {
        "name": "api_client",
        "description": "API调试/测试工具",
        "tags": ["api", "http", "rest", "debug", "postman"],
        "pipeline": ["project_manager", "architect", "engineer", "reviewer"],
        "prompt_template": "做一个{description}，要求：单HTML文件、支持GET/POST/PUT/DELETE、请求头编辑、JSON响应格式化、历史记录",
    },
    {
        "name": "python_cli",
        "description": "Python命令行工具",
        "tags": ["python", "cli", "命令行", "脚本", "script", "automation"],
        "pipeline": ["project_manager", "architect", "engineer", "reviewer"],
        "prompt_template": "做一个{description}Python命令行工具，要求：单py文件、click/argparse参数解析、彩色输出、错误处理完善",
    },
    {
        "name": "python_data_analysis",
        "description": "Python数据分析脚本",
        "tags": ["python", "data", "pandas", "analysis", "report"],
        "pipeline": ["project_manager", "architect", "engineer", "reviewer"],
        "prompt_template": "做一个{description}数据分析脚本，要求：读取CSV/Excel、pandas处理、生成统计图表（matplotlib/plotly）、输出HTML报告",
    },
    {
        "name": "documentation",
        "description": "项目文档/使用手册/API文档生成",
        "tags": ["docs", "readme", "manual", "documentation"],
        "pipeline": ["project_manager", "product_manager", "engineer", "reviewer"],
        "prompt_template": "为{description}生成完整文档，包含：概述、快速开始、API参考、常见问题、架构说明",
    },
]


def match_skill(user_input: str) -> dict | None:
    """根据用户输入匹配最合适的Skill模板"""
    input_lower = user_input.lower()
    best_match = None
    best_score = 0

    for skill in BUILTIN_SKILLS:
        score = 0
        for tag in skill["tags"]:
            if tag in input_lower:
                score += 2
        for word in skill["description"]:
            if word in input_lower:
                score += 0.1
        if skill["name"].replace("_", " ") in input_lower:
            score += 5

        if score > best_score:
            best_score = score
            best_match = skill

    return best_match if best_score >= 2 else None
