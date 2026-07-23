@echo off
REM ============================================================
REM  BiliYTPlayer — 打包为 Windows EXE
REM  用法: 双击运行此脚本，或在终端中执行
REM  产物: dist\BiliYTPlayer.exe
REM ============================================================
cd /d "%~dp0"

echo [*] 检查 PyInstaller ...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] PyInstaller 未安装，正在安装...
    pip install pyinstaller
)

echo [*] 检查依赖 ...
pip install -r requirements.txt >nul 2>&1

echo [*] 开始打包 ...
pyinstaller --clean --noconfirm bili_yt_player.spec

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo [+] 打包完成！
    echo     输出: dist\BiliYTPlayer.exe
    echo     大小:
    for %%A in ("dist\BiliYTPlayer.exe") do echo %%~zA bytes
    echo ============================================================
) else (
    echo [!] 打包失败，请检查上方错误信息。
)

pause
