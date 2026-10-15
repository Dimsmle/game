@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0project_python.bat" build_windows.py
pause
