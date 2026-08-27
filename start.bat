@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo 尚未安装运行组件，请先双击 install.bat。
  pause
  exit /b 1
)

start "FlowClick Studio" .venv\Scripts\pythonw.exe main.py
