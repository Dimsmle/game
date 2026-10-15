@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==== Character models ====
python -u main_desktop.py --list-models
echo.
echo ==== Backgrounds ====
python -u main_desktop.py --list-backgrounds
pause
