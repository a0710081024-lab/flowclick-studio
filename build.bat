@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [错误] 请先安装 Python 3.11 64 位。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
)

call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :failed
call .venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :failed
call .venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto :failed
call .venv\Scripts\pyinstaller.exe --noconfirm --clean FlowClick.spec
if errorlevel 1 goto :failed

if not exist output mkdir output
if exist "output\FlowClickStudio-v0.3.0-windows-x64.zip" del /q "output\FlowClickStudio-v0.3.0-windows-x64.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\FlowClickStudio' -DestinationPath 'output\FlowClickStudio-v0.3.0-windows-x64.zip' -Force"
if errorlevel 1 goto :failed

echo.
echo 构建完成：output\FlowClickStudio-v0.3.0-windows-x64.zip
pause
exit /b 0

:failed
echo.
echo 构建失败，请保留窗口中的错误信息。
pause
exit /b 1
