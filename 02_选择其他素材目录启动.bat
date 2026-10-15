@echo off
chcp 65001 >nul
cd /d "%~dp0"
python main_desktop.py --choose-root
pause
