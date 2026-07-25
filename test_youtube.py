#!/usr/bin/env python3
"""BiliYTPlayer YouTube 端到端测试"""

import sys
import re
import subprocess
import time

# ── 模拟 bili_yt_player.pyw 的 URL 检测逻辑 ──────────────────────────
YT_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})")

TEST_URLS = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True, "标准 watch URL"),
    ("https://youtu.be/dQw4w9WgXcQ", True, "短链接 youtu.be"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", True, "Shorts URL"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", True, "Shorts www URL"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", True, "移动端 URL"),
    ("https://www.bilibili.com/video/BV1GJ411x7h7", False, "B站 URL（不应匹配）"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf", True, "带播放列表"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30", True, "带时间戳"),
]

print("=" * 60)
print("测试 1: URL 正则匹配")
print("=" * 60)
all_regex_ok = True
for url, should_match, desc in TEST_URLS:
    m = YT_RE.search(url)
    matched = m is not None
    status = "✅" if matched == should_match else "❌"
    if matched:
        vid = m.group(1)
        print(f"{status} {desc}: {vid}")
    else:
        print(f"{status} {desc}: 未匹配")
    if matched != should_match:
        all_regex_ok = False

print()
print(f"正则测试结果: {'全部通过 ✅' if all_regex_ok else '有失败 ❌'}")

# ── 模拟 _read_clipboard() ──────────────────────────────────────────
print()
print("=" * 60)
print("测试 2: 剪贴板读取")
print("=" * 60)
try:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
        capture_output=True, text=True, timeout=3,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if r.returncode == 0 and r.stdout:
        clip = r.stdout.strip()
        print(f"✅ 当前剪贴板: {clip[:80]}...")
    else:
        print(f"⚠️ 剪贴板为空或读取失败 (exit={r.returncode})")
except Exception as e:
    print(f"⚠️ PowerShell 剪贴板读取失败: {e}")
    try:
        import pyperclip
        clip = pyperclip.paste()
        print(f"✅ pyperclip: {clip[:80]}...")
    except Exception:
        print("❌ pyperclip 也不可用")

# ── 测试 mpv 能直接播 YouTube ─────────────────────────────────────
print()
print("=" * 60)
print("测试 3: mpv + yt-dlp 播放 YouTube（audio only, 3秒）")
print("=" * 60)

import pathlib
exe_dir = pathlib.Path(__file__).resolve().parent if not getattr(sys, 'frozen', False) else pathlib.Path(sys.executable).resolve().parent
mpv_exe = str(exe_dir / "mpv-portable" / "mpv.exe")
ytdlp_exe = str(exe_dir / "mpv-portable" / "yt-dlp.exe")
conf_dir = str(exe_dir / "mpv-portable" / "portable_config")

if not pathlib.Path(mpv_exe).exists():
    print(f"❌ mpv 不存在: {mpv_exe}")
    sys.exit(1)
if not pathlib.Path(ytdlp_exe).exists():
    print(f"❌ yt-dlp 不存在: {ytdlp_exe}")
    sys.exit(1)

cmd = [
    mpv_exe,
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    f"--config-dir={conf_dir}",
    f"--script-opts=ytdl_hook-ytdl_path={ytdlp_exe}",
    "--no-video",
    "--length=3",
    "--really-quiet",
    "--term-status-msg=",
]

print(f"mpv: {mpv_exe}")
print(f"yt-dlp: {ytdlp_exe}")
print(f"配置: {conf_dir}")
print("启动 mpv (3秒后自动退出)...")

try:
    start = time.time()
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    stderr_lines = []
    while proc.poll() is None and time.time() - start < 10:
        try:
            stderr_lines.append(proc.stderr.readline())
        except Exception:
            break
    proc.kill()
    proc.wait()

    stderr_text = "".join(stderr_lines)
    if "ytdl_hook" in stderr_text and "failed" in stderr_text:
        print("❌ ytdl_hook 失败")
        for line in stderr_lines[-5:]:
            print(f"  {line.strip()}")
    elif "AO:" in stderr_text or "Audio" in stderr_text:
        print("✅ mpv + yt-dlp 播放成功！")
    else:
        print("⚠️ 无法确定播放状态")
        for line in stderr_lines[:10]:
            print(f"  {line.strip()}")
except Exception as e:
    print(f"❌ 测试异常: {e}")

print()
print("=" * 60)
print("测试完成。如果所有测试通过，YouTube 播放应该正常。")
print("=" * 60)
