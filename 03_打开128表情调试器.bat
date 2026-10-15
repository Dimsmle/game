@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0project_python.bat" desktop.py
pause
