@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo [Character Studio] Starting native desktop application...
echo Python interpreter:
where python
call "%~dp0project_python.bat" main_desktop.py %*
if errorlevel 1 (
  echo.
  echo The application did not start. Copy the error shown above.
)
pause
