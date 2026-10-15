@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0project_python.bat" main_desktop.py --root "G:\开发游戏\Amakano3_AI" --model kan_10 --export-nod --probe-expression "笑顔Ａ"
pause
