"""
产出物预览服务
工程师Agent生成代码后，自动启动预览让用户立刻看到成果
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

from deepforge.tools.toolbox import ToolBox


class PreviewServer:
    def __init__(self, work_dir: str = ".educe/preview"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._process: subprocess.Popen | None = None
        self._port: int = 8899

    @property
    def preview_url(self) -> str:
        return f"http://localhost:{self._port}"

    async def preview_artifacts(self, files: dict[str, str], auto_open: bool = True) -> dict[str, Any]:
        """根据文件类型自动选择预览方式"""
        if not files:
            return {"status": "no_files", "url": ""}

        for filepath, content in files.items():
            full_path = self.work_dir / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

        html_files = [f for f in files if f.endswith(".html")]
        py_files = [f for f in files if f.endswith(".py")]
        has_package_json = any("package.json" in f for f in files)

        if html_files:
            return await self._preview_html(html_files[0], auto_open)
        elif py_files and any("app" in f or "server" in f or "main" in f for f in py_files):
            return await self._preview_python(py_files, auto_open)
        elif has_package_json:
            return await self._preview_node(auto_open)
        else:
            return await self._preview_static(files, auto_open)

    async def _preview_html(self, html_file: str, auto_open: bool) -> dict[str, Any]:
        """HTML文件直接启动静态服务器预览"""
        self.stop()

        serve_dir = str(self.work_dir)
        self._process = subprocess.Popen(
            ["python", "-m", "http.server", str(self._port), "--directory", serve_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        await asyncio.sleep(0.5)
        url = f"{self.preview_url}/{html_file}"

        if auto_open:
            webbrowser.open(url)

        return {
            "status": "running",
            "type": "html",
            "url": url,
            "file": html_file,
            "message": f"预览已启动: {url}",
        }

    async def _preview_python(self, py_files: list[str], auto_open: bool) -> dict[str, Any]:
        """Python文件尝试运行"""
        main_file = None
        for f in py_files:
            if "main" in f or "app" in f or "server" in f:
                main_file = f
                break
        if not main_file:
            main_file = py_files[0]

        full_path = self.work_dir / main_file

        try:
            result = subprocess.run(
                ["python", str(full_path)],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self.work_dir),
            )
            return {
                "status": "completed",
                "type": "python",
                "file": main_file,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:500],
                "returncode": result.returncode,
                "message": f"Python脚本执行完成 (exit={result.returncode})",
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "type": "python",
                "file": main_file,
                "message": "脚本执行超时（可能是服务类程序，需要手动运行）",
            }
        except Exception as e:
            return {"status": "error", "type": "python", "message": str(e)}

    async def _preview_node(self, auto_open: bool) -> dict[str, Any]:
        """Node.js项目"""
        return {
            "status": "manual",
            "type": "node",
            "message": "Node.js项目已生成，请运行: cd .educe/preview && npm install && npm start",
            "dir": str(self.work_dir),
        }

    async def _preview_static(self, files: dict[str, str], auto_open: bool) -> dict[str, Any]:
        """静态文件生成一个入口页面"""
        index_content = self._generate_index_page(files)
        index_path = self.work_dir / "index.html"
        index_path.write_text(index_content, encoding="utf-8")

        return await self._preview_html("index.html", auto_open)

    def _generate_index_page(self, files: dict[str, str]) -> str:
        """为非HTML产出物生成一个展示页面"""
        file_list = "\n".join(
            f'<li><a href="{f}" target="_blank">{f}</a> ({len(c)} chars)</li>'
            for f, c in files.items()
        )
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Educe 产出物</title>
<style>
body{{font-family:system-ui;background:#0a0e14;color:#e6edf3;padding:40px;max-width:800px;margin:0 auto}}
h1{{background:linear-gradient(135deg,#39d2c0,#58a6ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
ul{{list-style:none;padding:0}}
li{{padding:8px 12px;margin:4px 0;background:#161b22;border:1px solid #30363d;border-radius:6px}}
a{{color:#58a6ff;text-decoration:none}}
a:hover{{text-decoration:underline}}
</style></head>
<body>
<h1>DeepForge 产出物</h1>
<p>以下文件已生成：</p>
<ul>{file_list}</ul>
</body></html>"""

    def stop(self) -> None:
        if self._process:
            self._process.terminate()
            self._process = None

    def __del__(self):
        self.stop()


preview_server = PreviewServer()
