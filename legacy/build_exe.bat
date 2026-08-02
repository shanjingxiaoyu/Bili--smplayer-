@echo off
REM ============================================================
REM  BiliYTPlayer — 打包为 Windows EXE
REM  用法: 在项目根目录下双击运行，或在终端中执行
REM  产物: dist\BiliYTPlayer.exe
REM  前提: 已创建 .venv 并安装依赖
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 未找到 .venv，正在创建虚拟环境...
    python -m venv .venv
)

echo [*] 检查 PyInstaller ...
.venv\Scripts\pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] PyInstaller 未安装，正在安装...
    .venv\Scripts\pip install pyinstaller
)

echo [*] 检查依赖 ...
.venv\Scripts\pip install -r requirements.txt >nul 2>&1

echo [*] 清理旧构建产物 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [*] 开始打包 ...
set SAFE_DELETE_DISABLE=1
.venv\Scripts\python.exe -m PyInstaller --noconfirm bili_yt_player.spec

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo [+] 打包完成！
    echo     输出: dist\BiliYTPlayer.exe
    for %%A in ("dist\BiliYTPlayer.exe") do echo     大小: %%~zA bytes
    echo.
    echo [*] 复制到根目录...
    copy /y dist\BiliYTPlayer.exe BiliYTPlayer.exe >nul
    echo [+] 根目录 BiliYTPlayer.exe 已更新
    echo ============================================================
) else (
    echo [!] 打包失败，请检查上方错误信息。
)

pause
