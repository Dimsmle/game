@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== Character models ====
call "%~dp0project_python.bat" -u main_desktop.py --list-models
echo.
echo ==== Backgrounds ====
call "%~dp0project_python.bat" -u main_desktop.py --list-backgrounds
pause
