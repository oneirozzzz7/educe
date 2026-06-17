"""
产出物管理器
负责：文件保存、类型检测、预览启动、打包下载
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import webbrowser
import zipfile
from pathlib import Path
from typing import Any


class ArtifactManager:
    def __init__(self, work_dir: str = ".educe/output"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._server_proc: subprocess.Popen | None = None
        self._port = 8899

    def save_files(self, files: dict[str, str]) -> list[Path]:
        """保存生成的文件到输出目录"""
        saved = []
        for filepath, content in files.items():
            full = self.work_dir / filepath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            saved.append(full)
        return saved

    def detect_project_type(self, files: dict[str, str]) -> str:
        """检测项目类型"""
        names = set(files.keys())
        extensions = {Path(f).suffix for f in names}

        if any(f.endswith("manifest.json") for f in names):
            return "chrome_extension"
        if "package.json" in names:
            return "node"
        if any(f.endswith(".html") for f in names) and len(names) <= 3:
            return "static_html"
        if "requirements.txt" in names or "pyproject.toml" in names:
            return "python"
        if ".py" in extensions and len(names) == 1:
            return "python_script"
        if ".html" in extensions:
            return "static_html"
        return "files"

    async def preview(self, files: dict[str, str], auto_open: bool = True) -> dict[str, Any]:
        """根据项目类型启动预览"""
        project_type = self.detect_project_type(files)
        saved = self.save_files(files)

        if project_type == "static_html":
            return await self._preview_html(files, auto_open)
        elif project_type == "python_script":
            return await self._run_python(files)
        elif project_type == "python":
            return self._report_python_project(files)
        elif project_type == "chrome_extension":
            return self._report_chrome_extension(files)
        elif project_type == "node":
            return self._report_node_project(files)
        else:
            return {"type": project_type, "files": [str(p) for p in saved], "dir": str(self.work_dir)}

    async def _preview_html(self, files: dict[str, str], auto_open: bool) -> dict[str, Any]:
        self.stop_server()

        html_file = next((f for f in files if f.endswith(".html")), None)
        if not html_file:
            return {"type": "static_html", "error": "no html file"}

        self._server_proc = subprocess.Popen(
            ["python", "-m", "http.server", str(self._port), "--directory", str(self.work_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)

        url = f"http://localhost:{self._port}/{html_file}"
        if auto_open:
            webbrowser.open(url)

        return {"type": "static_html", "url": url, "file": html_file}

    async def _run_python(self, files: dict[str, str]) -> dict[str, Any]:
        py_file = next((f for f in files if f.endswith(".py")), None)
        if not py_file:
            return {"type": "python_script", "error": "no py file"}

        full_path = self.work_dir / py_file
        try:
            result = subprocess.run(
                ["python", str(full_path)],
                capture_output=True, text=True, timeout=15, cwd=str(self.work_dir),
            )
            return {
                "type": "python_script",
                "file": py_file,
                "stdout": result.stdout[:3000],
                "stderr": result.stderr[:1000],
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"type": "python_script", "file": py_file, "error": "timeout"}

    def _report_python_project(self, files: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "python",
            "files": list(files.keys()),
            "dir": str(self.work_dir),
            "instructions": f"cd {self.work_dir} && pip install -e . && python main.py",
        }

    def _report_chrome_extension(self, files: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "chrome_extension",
            "files": list(files.keys()),
            "dir": str(self.work_dir),
            "instructions": f"打开 chrome://extensions → 开启开发者模式 → 加载已解压的扩展 → 选择 {self.work_dir}",
        }

    def _report_node_project(self, files: dict[str, str]) -> dict[str, Any]:
        return {
            "type": "node",
            "files": list(files.keys()),
            "dir": str(self.work_dir),
            "instructions": f"cd {self.work_dir} && npm install && npm start",
        }

    def package_zip(self) -> Path:
        """打包所有产出物为zip"""
        zip_path = self.work_dir.parent / f"{self.work_dir.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in self.work_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(self.work_dir))
        return zip_path

    def stop_server(self):
        if self._server_proc:
            self._server_proc.terminate()
            self._server_proc = None

    def cleanup(self):
        self.stop_server()
        import shutil
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
