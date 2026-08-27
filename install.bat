@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有检测到 Python Launcher。
  echo 请安装 Python 3.11 64 位，并勾选 Add Python to PATH。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 正在创建独立运行环境...
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
)

echo 正在安装运行组件，文字识别组件体积较大，请耐心等待...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :failed
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo 安装完成。以后双击 start.bat 即可从源码运行。
pause
exit /b 0

:failed
echo.
echo 安装失败，请保留窗口中的错误信息。
pause
exit /b 1
