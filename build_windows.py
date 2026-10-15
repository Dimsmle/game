# -*- coding: utf-8 -*-
"""Build a Windows onedir EXE using the *current* PyCharm/Conda Python interpreter."""
from pathlib import Path
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parent

def main():
    if sys.platform!="win32":
        print("Windows EXE 必须在 Windows 中打包。请将工程复制到 Windows，启用 Conda 后运行。")
        return 2
    try:
        import PyInstaller
    except ImportError:
        print("未安装 PyInstaller。运行：python -m pip install -r requirements-build.txt")
        return 3
    try:
        import PIL
        import webview
    except ImportError as exc:
        print("缺少桌面版依赖：", exc)
        print("运行：python -m pip install -r requirements-build.txt")
        return 4
    web=ROOT/"studio"/"web"
    if not (web/"index.html").exists():
        print("程序前端文件丢失：",web)
        return 5
    cmd=[
        sys.executable,"-m","PyInstaller",
        "--noconfirm","--clean","--onedir","--windowed",
        "--name","CharacterStudio",
        "--add-data",str(web)+os.pathsep+"studio/web",
        "--add-data",str(ROOT/"studio"/"roleplay_plus"/"web")+os.pathsep+"studio/roleplay_plus/web",
        "--collect-all","webview",
        "--hidden-import","webview.platforms.winforms",
        str(ROOT/"main_desktop.py"),
    ]
    print("正在生成 Windows EXE，当前解释器：",sys.executable)
    print("需要 WebView2 Runtime；EXE 不会包含你电脑的游戏资源。")
    process=subprocess.run(cmd,cwd=ROOT)
    if process.returncode!=0:
        print("PyInstaller 构建失败，检查上方日志。")
        return process.returncode
    exe=ROOT/"dist"/"CharacterStudio"/"CharacterStudio.exe"
    if not exe.exists():
        print("未找到预期的 EXE：",exe)
        return 6
    print("构建完成。运行：",exe)
    print("请保留 dist/CharacterStudio 整个目录，不要只复制其中的 exe。")
    print("首次运行将从 G 盘读取游戏素材，渲染结果存回 G 盘的 character_exports。")
    return 0

if __name__=="__main__":
    sys.exit(main())
