#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_clipboard_dolby.py

后台剪贴板监听：复制 B 站链接或 BV 号 →
  自动解析杜比视界(Dolby Vision) / 杜比全景声(Dolby Atmos) →
  唤起本地 mpv/SMPlayer 播放。

不挑终端——UWP 客户端、Edge/Chrome 网页、微信/QQ 别人发的链接，复制即播。
"""

import os
import sys
import re
import time
import json
import atexit
import hashlib
import subprocess
import urllib.parse
from functools import reduce
from pathlib import Path
from shutil import which

# ---- PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，任何 print() 都会崩溃 ----
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# ============================================================================
# 0. 自检 & 自动安装依赖
# ============================================================================

# 配置目录：优先使用 %APPDATA%，确保 exe 放在 Program Files 等受限目录时也有写权限
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
else:
    _exe_dir = Path(__file__).resolve().parent
_CONFIG_DIR = Path(os.environ.get("APPDATA", str(_exe_dir))) / "BiliYTPlayer"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = _CONFIG_DIR / ".env"


def _install(pkg, imp=None):
    if imp is None:
        imp = pkg
    try:
        __import__(imp.replace("-", "_"))
    except ImportError:
        print(f"[*] 安装缺失依赖: {pkg} …")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[+] {pkg} 安装完成。")


# PyInstaller 打包后依赖已随 exe bundle，无需（也无法）pip install
if not getattr(sys, "frozen", False):
    _install("requests")
    _install("python-dotenv", "dotenv")
    _install("pyperclip")


import requests                  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import pyperclip                # noqa: E402


# ============================================================================
# 1. 常量 / 配置
# ============================================================================

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REFERER = "https://www.bilibili.com"
COMMON_HEADERS = {
    "User-Agent": UA,
    "Referer": REFERER,
    "Origin": "https://www.bilibili.com",
}

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

BV_RE = re.compile(r"(BV[a-zA-Z0-9]{10})")
YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})")



# ============================================================================
# 2. SESSDATA 读取（首次弹框输入，后续从 .env 读取）
# ============================================================================

def load_sessdata() -> str:
    # 已配置过 → 直接读
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
        sessdata = os.getenv("SESSDATA", "").strip()
        if sessdata:
            return sessdata

    # 首次运行 → 弹输入框
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    sessdata = simpledialog.askstring(
        "B 站 SESSDATA",
        "首次使用，请粘贴 B 站 SESSDATA Cookie 值：\n\n"
        "获取方法：浏览器登录 bilibili.com → F12\n"
        "→ Application → Cookies → www.bilibili.com\n"
        "→ 复制 SESSDATA 的 Value  → 粘贴到此框",
        parent=root,
    )
    root.destroy()

    if not sessdata or not sessdata.strip():
        print("[!] 未输入 SESSDATA，已取消。", flush=True)
        sys.exit(0)

    sessdata = sessdata.strip().strip("\"'")
    ENV_PATH.write_text(
        "# B 站登录态 Cookie — 自动保存，请勿分享。\n"
        "SESSDATA=" + sessdata + "\n",
        encoding="utf-8",
    )
    print("[+] SESSDATA 已保存到 .env，下次运行不再询问。", flush=True)
    return sessdata


# ============================================================================
# 3. 播放器检测（mpv > smplayer.exe > smplayer.lnk）
# ============================================================================

def _search_registry_install_path(keyword: str) -> str | None:
    """搜 Windows 注册表卸载信息，找 mpv/SMPlayer 安装路径。"""
    try:
        import winreg
    except ImportError:
        return None
    roots = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    subkeys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for root in roots:
        for sk in subkeys:
            try:
                with winreg.OpenKey(root, sk) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, name) as sub:
                                disp, _ = winreg.QueryValueEx(sub, "DisplayName")
                                if keyword.lower() in str(disp).lower():
                                    loc, _ = winreg.QueryValueEx(sub, "InstallLocation")
                                    if loc:
                                        return str(loc)
                        except OSError:
                            continue
            except OSError:
                continue
    return None


def find_player():
    """返回 (player_path, kind)，kind 为 "mpv" 或 "smplayer"。
       优先 mpv，找不到再 smplayer。多级探测：固定路径 → PATH → 注册表 → 广搜。
    """
    # ---- 1. 固定路径 ----
    drives = ["C:", "D:", "E:"]
    mpv_candidates = set()
    for d in drives:
        for sub in ["Program Files", "Program Files (x86)", "MSplayer", "mpv", ""]:
            base = os.path.join(d + os.sep, sub) if sub else d + os.sep
            mpv_candidates.add(os.path.join(base, "SMPlayer", "mpv", "mpv.exe"))
            mpv_candidates.add(os.path.join(base, "mpv", "mpv.exe"))
            mpv_candidates.add(os.path.join(base, "mpv.net", "mpvnet.exe"))
    for p in sorted(mpv_candidates):
        if os.path.isfile(p):
            return p, "mpv"

    # ---- 2. PATH ----
    p = which("mpv")
    if p:
        return p, "mpv"

    # ---- 3. 注册表 ----
    for kw in ["smplayer", "mpv"]:
        loc = _search_registry_install_path(kw)
        if loc:
            mpv_try = os.path.join(loc, "mpv", "mpv.exe")
            if os.path.isfile(mpv_try):
                return mpv_try, "mpv"
            sm_try = os.path.join(loc, "smplayer.exe")
            if os.path.isfile(sm_try):
                return sm_try, "smplayer"

    # ---- 4. smplayer .exe 广搜 + 近邻 mpv ----
    for d in drives:
        for sub in ["Program Files", "Program Files (x86)", "MSplayer"]:
            base = os.path.join(d + os.sep, sub, "SMPlayer", "smplayer.exe")
            if os.path.isfile(base):
                mpv_nearby = os.path.join(os.path.dirname(base), "mpv", "mpv.exe")
                if os.path.isfile(mpv_nearby):
                    return mpv_nearby, "mpv"
                return base, "smplayer"

    # ---- 5. .lnk 快捷方式 ----
    for p in [
        r"C:\Users\Public\Desktop\SMPlayer.lnk",
        os.path.join(os.path.expanduser("~"), "Desktop", "SMPlayer.lnk"),
    ]:
        if os.path.isfile(p):
            return p, "smplayer"

    p = which("smplayer")
    if p:
        return p, "smplayer"

    return None, None


# ============================================================================
# 4. WBI 动态签名
# ============================================================================

def _mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def get_wbi_keys(session: requests.Session):
    resp = session.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=COMMON_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    d = resp.json()["data"]["wbi_img"]
    img_key = d["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub_key = d["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    mixin = _mixin_key(img_key + sub_key)
    params = dict(params)
    params["wts"] = str(int(time.time()))
    params = dict(sorted(params.items()))
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    qs = urllib.parse.urlencode(params)
    w_rid = hashlib.md5((qs + mixin).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


# ============================================================================
# 5. 视频信息 & playurl 解析
# ============================================================================

def get_cid(session: requests.Session, bvid: str):
    resp = session.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers=COMMON_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    j = resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"获取视频信息失败: {j.get('message')}")
    return j["data"]["cid"], j["data"]["title"]


def get_playurl(session: requests.Session, bvid: str, cid: int,
                img_key: str, sub_key: str) -> dict:
    params = {
        "bvid": bvid, "cid": cid,
        "qn": 126, "fnver": 0, "fnval": 4048, "fourk": 1,
    }
    signed = enc_wbi(params, img_key, sub_key)
    resp = session.get(
        "https://api.bilibili.com/x/player/wbi/playurl",
        params=signed,
        headers=COMMON_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    j = resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"playurl 失败: {j.get('message')} (code={j.get('code')})")
    data = j.get("data")
    if not data:
        raise RuntimeError("playurl data 为空，该视频不支持杜比品质或需大会员")
    return data


def pick_dolby_streams(dash: dict):
    """提取杜比优先流，找不到则回退最高清普通流。"""
    video_url = audio_url = None
    vdesc = adesc = ""

    dolby = dash.get("dolby") or {}

    # 杜比视界
    dv = dolby.get("video")
    if dv:
        v = dv[0]
        video_url = v.get("base_url") or (v.get("backupUrl") or [None])[0]
        vdesc = "杜比视界(Dolby Vision)"

    # 杜比全景声
    da = dolby.get("audio")
    if da:
        a = da[0]
        audio_url = a.get("base_url") or (a.get("backupUrl") or [None])[0]
        adesc = "杜比全景声(Dolby Atmos/E-AC-3)"

    # 回退：普通最高清视频
    if not video_url:
        vids = dash.get("video") or []
        if vids:
            best = sorted(vids, key=lambda x: (x.get("id", 0), x.get("bandwidth", 0)))[-1]
            video_url = best.get("base_url") or (best.get("backup_url") or [None])[0]
            vdesc = f"普通视频 qn={best.get('id')}"

    # 回退：FLAC / 普通最高码率音频
    if not audio_url:
        flac = (dash.get("flac") or {}).get("audio")
        if flac:
            audio_url = flac.get("base_url") or (flac.get("backup_url") or [None])[0]
            adesc = "FLAC 无损"
        else:
            auds = dash.get("audio") or []
            if auds:
                best = sorted(auds, key=lambda x: x.get("bandwidth", 0))[-1]
                audio_url = best.get("base_url") or (best.get("backup_url") or [None])[0]
                adesc = f"普通音频 id={best.get('id')}"

    return video_url, audio_url, vdesc, adesc


# ============================================================================
# 6. 唤起播放器
# ============================================================================

def build_http_header_arg(sessdata: str) -> str:
    return ",".join([
        f"Referer: {REFERER}",
        f"User-Agent: {UA}",
        f"Cookie: SESSDATA={sessdata}",
    ])


def launch_mpv(mpv_path, video_url, audio_url, title, sessdata):
    """唤起 mpv。
       Cookie 必须通过 mpv 原生 cookies 文件传入，不可用 --http-header-fields
       （ffmpeg HTTP 层会拒绝 Cookie/Origin 头，导致 CDN 403）。
    """
    import tempfile

    # 写临时 cookies 文件（Netscape 格式）
    cookie_fd, cookie_path = tempfile.mkstemp(
        suffix=".txt", prefix="bili_cookies_", text=True
    )
    with os.fdopen(cookie_fd, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\t" + sessdata + "\n")

    # 注册 atexit 兜底清理，防止程序异常退出时 SESSDATA 残留在 %TEMP%
    atexit.register(lambda p=cookie_path: os.unlink(p) if os.path.exists(p) else None)

    cmd = [
        mpv_path,
        video_url,
        "--cookies-file=" + cookie_path,
        "--http-header-fields=Referer: " + REFERER,
        "--user-agent=" + UA,
        f"--force-media-title={title}",
        "--vo=gpu-next",
        "--ao=wasapi",
        "--audio-exclusive=yes",
        "--audio-spdif=eac3",
        "--target-colorspace-hint=yes",
    ]
    if audio_url:
        cmd += [f"--audio-file={audio_url}"]

    print(f"    唤起 mpv: {title}")
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)

    # 等 mpv 拿到流后即可删 cookie 文件（mpv 已读入内存）
    time.sleep(2)
    try:
        os.unlink(cookie_path)
    except OSError:
        pass

    # 快速检查 mpv 是否秒退
    time.sleep(0.3)
    code = proc.poll()
    if code is not None and code != 0:
        err = proc.stderr.read()[:500] if proc.stderr else ""
        print(f"    [!] mpv 异常退出 (code={code})。")
        if err:
            print(f"    [!] {err.strip()}")
    elif code is None:
        print(f"    [+] mpv 正在播放: {title}")


def launch_smplayer(smplayer_path, video_url, title):
    """SMPlayer 唤起，.lnk 用 ShellExecute，exe 用 Popen。"""
    if smplayer_path.lower().endswith(".lnk"):
        try:
            os.startfile(smplayer_path, arguments=video_url)
            print(f"    唤起 SMPlayer: {title}")
            return
        except Exception as e:
            print(f"    [!] 快捷方式唤起失败({e})，回退。")
    print(f"    唤起 SMPlayer: {title}")
    subprocess.Popen([smplayer_path, video_url])


# ============================================================================
# 7. 剪贴板读取 + 全链路
# ============================================================================

def read_clipboard() -> str:
    """读取 Windows 剪贴板文本。
       优先用 PowerShell 原生 API（最可靠），失败则回退 pyperclip。
    """
    # 方式 1: PowerShell Get-Clipboard（用户终端会话下最稳）
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass

    # 方式 2: pyperclip（备选）
    try:
        return pyperclip.paste()
    except Exception:
        pass

    return ""

def process_bvid(session, bvid, img_key, sub_key, player_path, kind, sessdata):
    print(f"  [*] 开始解析 {bvid} …")
    cid, title = get_cid(session, bvid)
    print(f"  [+] 标题: {title}")

    data = get_playurl(session, bvid, cid, img_key, sub_key)
    dash = data.get("dash")
    if not dash:
        print("  [!] 未返回 DASH 数据，跳过。")
        return

    video_url, audio_url, vdesc, adesc = pick_dolby_streams(dash)
    if not video_url:
        print("  [!] 未能提取可播放的视频流。")
        return

    print(f"  [+] 画质: {vdesc}")
    print(f"  [+] 音轨: {adesc if audio_url else '无'}")

    if kind == "mpv":
        launch_mpv(player_path, video_url, audio_url, title, sessdata)
    else:
        launch_smplayer(player_path, video_url, title)


def process_youtube(player_path, kind, ytid):
    """YouTube：mpv + yt-dlp 直接解析最高画质，无需任何鉴权。"""
    url = f"https://www.youtube.com/watch?v={ytid}"
    print(f"    唤起 mpv (YouTube): {url}")

    if kind == "mpv":
        subprocess.Popen([
            player_path, url,
            "--vo=gpu-next",
            "--ytdl-format=bestvideo+bestaudio/best",
        ])
    else:
        subprocess.Popen([player_path, url])
    print(f"    [+] mpv 正在播放: {url}")


# ============================================================================
# 主循环
# ============================================================================

def main():
    # 无缓冲输出，确保终端实时看到日志
    # --windowed 模式下 stdout 可能是 devnull 文件，无 reconfigure 方法，忽略即可
    for _fh in (sys.stdout, sys.stderr):
        try:
            _fh.reconfigure(line_buffering=True)
        except (AttributeError, OSError):
            pass

    print("=" * 56, flush=True)
    print(" B 站 / YouTube 剪贴板直连播放器", flush=True)
    print("=" * 56, flush=True)

    sessdata = load_sessdata()

    player_path, kind = find_player()
    if not player_path:
        print("[!] 未检测到 SMPlayer/mpv，请先安装。", flush=True)
        sys.exit(1)
    print(f"[+] 播放器: {player_path}  ({kind})", flush=True)

    session = requests.Session()
    session.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")

    try:
        img_key, sub_key = get_wbi_keys(session)
    except Exception as e:
        print(f"[!] 获取 WBI 签名密钥失败: {e}", flush=True)
        sys.exit(1)
    print("[+] WBI 签名密钥就绪。", flush=True)
    print("\n[*] 开始监听剪贴板（Ctrl+C 停止）…", flush=True)
    print("[*] 复制 B 站 / YouTube 链接即可播放。\n", flush=True)

    last_vid: str = ""
    heartbeat = 0

    while True:
        text = read_clipboard()

        heartbeat += 1
        if heartbeat >= 6:
            heartbeat = 0
            print(".", end="", flush=True)

        # ---- B 站 ----
        m = BV_RE.search(text)
        if m:
            bvid = m.group(1)
            if bvid != last_vid:
                last_vid = bvid
                print(f"\n>> 检测到 B 站链接: {bvid}", flush=True)
                try:
                    process_bvid(session, bvid, img_key, sub_key,
                                 player_path, kind, sessdata)
                except Exception as e:
                    print(f"  [!] 播放失败: {e}", flush=True)
            time.sleep(0.5)
            continue

        # ---- YouTube ----
        m = YT_RE.search(text)
        if m:
            ytid = m.group(1)
            if ytid != last_vid:
                last_vid = ytid
                print(f"\n>> 检测到 YouTube 链接: {ytid}", flush=True)
                try:
                    process_youtube(player_path, kind, ytid)
                except Exception as e:
                    print(f"  [!] 播放失败: {e}", flush=True)
            time.sleep(0.5)
            continue

        time.sleep(0.5)


if __name__ == "__main__":
    main()
