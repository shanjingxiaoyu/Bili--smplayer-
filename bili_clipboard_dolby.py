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

# ---- subprocess helpers: hide console window on Windows (no flashing cmd) ----
def _popen_silent(*args, **kwargs):
    """Popen with hidden console on Windows."""
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", si)
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.Popen(*args, **kwargs)

def _run_silent(*args, **kwargs):
    """subprocess.run with hidden console on Windows."""
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", si)
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(*args, **kwargs)

# ---- PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，任何 print() 都会崩溃 ----
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 强制 UTF-8 编码,避免标题中的特殊字符(如 ®)触发 GBK 编码崩溃
for _fh in (sys.stdout, sys.stderr):
    try:
        _fh.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

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
        _run_silent(
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
EP_RE = re.compile(r"/ep(\d+)")
SS_RE = re.compile(r"/ss(\d+)")
BANGUMI_MD_RE = re.compile(r"/md(\d+)")



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
    """多级探测 mpv。优先级: 自带便携版 > 独立安装版 > SMPlayer 自带 > PATH > 注册表 > 广搜。
       返回 mpv.exe 绝对路径,找不到返 None。
    """
    drives = ["C:", "D:", "E:"]

    # ---- 0. 最高优先: 自带便携版 mpv (开箱即用) ----
    bundled = _exe_dir / "mpv-portable" / "mpv.exe"
    if bundled.is_file():
        return str(bundled)

    # ---- 1. 独立安装的 mpv（最新稳定版） ----
    # winget 安装路径
    standalone_mpv_paths = [
        os.path.join(d + os.sep, "Program Files", "MPV Player", "mpv.exe")
        for d in drives
    ] + [
        os.path.join(d + os.sep, "Program Files (x86)", "MPV Player", "mpv.exe")
        for d in drives
    ] + [
        os.path.join(d + os.sep, "Program Files", "mpv", "mpv.exe")
        for d in drives
    ]
    for p in standalone_mpv_paths:
        if os.path.isfile(p):
            return p

    # PATH 中的 mpv（可能是 winget/scoop/choco 安装的）
    mpv_in_path = which("mpv")
    if mpv_in_path and os.path.isfile(mpv_in_path):
        # 确保不是 SMPlayer 目录下的 mpv.com（那是 mplayer 兼容层）
        if os.path.basename(mpv_in_path).lower() == "mpv.exe":
            return mpv_in_path

    def _mpv_near(sm_path):
        """从 smplayer.exe 路径推导它自带的 mpv.exe"""
        mpv_try = os.path.join(os.path.dirname(sm_path), "mpv", "mpv.exe")
        if os.path.isfile(mpv_try):
            return mpv_try
        return None

    # ---- 1. SMPlayer 固定路径（备用） ----
    for d in drives:
        for sub in ["Program Files", "Program Files (x86)", "MSplayer"]:
            sm = os.path.join(d + os.sep, sub, "SMPlayer", "smplayer.exe")
            if os.path.isfile(sm):
                mpv = _mpv_near(sm) or sm  # 没自带 mpv 就回退到 smplayer
                return mpv

    # ---- 2. PATH ----
    p = which("smplayer")
    if p:
        return _mpv_near(p) or p

    # ---- 3. 注册表 ----
    loc = _search_registry_install_path("smplayer")
    if loc:
        sm_try = os.path.join(loc, "smplayer.exe")
        if os.path.isfile(sm_try):
            return _mpv_near(sm_try) or sm_try

    # ---- 4. 广搜 Program Files ----
    for d in drives:
        for sub in ["Program Files", "Program Files (x86)"]:
            base = os.path.join(d + os.sep, sub)
            if not os.path.isdir(base):
                continue
            for root, dirs, _ in os.walk(base):
                depth = root.replace(base, "").count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                sm_try = os.path.join(root, "smplayer.exe")
                if os.path.isfile(sm_try):
                    return _mpv_near(sm_try) or sm_try

    # ---- 5. .lnk 快捷方式 ----
    for p in [
        r"C:\Users\Public\Desktop\SMPlayer.lnk",
        os.path.join(os.path.expanduser("~"), "Desktop", "SMPlayer.lnk"),
    ]:
        if os.path.isfile(p):
            return p  # .lnk 没法推导 mpv，直接返回

    return None


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


def validate_sessdata(sessdata: str) -> bool:
    """检查 SESSDATA 是否有效。返回 True=有效, False=过期。"""
    try:
        s = requests.Session()
        s.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")
        r = s.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=COMMON_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        j = r.json()
        # code=0 表示登录有效, -101 表示未登录/过期
        return j.get("code") == 0
    except Exception:
        return False


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

def resolve_episode(session: requests.Session, ep_id: int) -> tuple[str, int, str]:
    """通过 EP(番剧/电影) ID 获取 bvid, cid, title。
       返回 (bvid, cid, full_title)。
    """
    resp = session.get(
        "https://api.bilibili.com/pgc/view/web/season",
        params={"ep_id": ep_id},
        headers=COMMON_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    j = resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"获取番剧信息失败: {j.get('message')}")
    result = j["result"]
    season_title = result.get("season_title", "") or result.get("title", "")
    for ep in result.get("episodes", []):
        if ep.get("id") == ep_id:
            bvid = ep["bvid"]
            cid = ep["cid"]
            ep_title = ep.get("long_title") or ep.get("share_copy", "") or f"第{ep.get('title','?')}集"
            full_title = f"{season_title} - {ep_title}" if season_title else ep_title
            return bvid, int(cid), full_title
    raise RuntimeError(f"未找到 EP {ep_id}")

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
    """提取视频/音频流。
       优先普通最高清流(兼容性最好),杜比视界仅作备选(易黑屏)。
       返回 (video_url, audio_url, vdesc, adesc)。
    """
    video_url = audio_url = None
    vdesc = adesc = ""

    dolby = dash.get("dolby") or {}

    # ── 第一优先: 普通最高清视频(兼容性最好,不会黑屏) ──
    vids = dash.get("video") or []
    if vids:
        best = sorted(vids, key=lambda x: (x.get("id", 0), x.get("bandwidth", 0)))[-1]
        video_url = best.get("base_url") or (best.get("backup_url") or [None])[0]
        vdesc = f"普通视频 id={best.get('id')} codec={best.get('codecs', '?')}"

    # ── 普通最高码率音频 ──
    auds = dash.get("audio") or []
    if auds:
        best = sorted(auds, key=lambda x: x.get("bandwidth", 0))[-1]
        audio_url = best.get("base_url") or (best.get("backup_url") or [None])[0]
        adesc = f"普通音频 id={best.get('id')}"

    # ── FLAC 无损音频(如果可用,覆盖普通音频) ──
    flac = dash.get("flac") or {}
    fa = flac.get("audio")
    if fa:
        audio_url = fa.get("base_url") or (fa.get("backup_url") or [None])[0]
        adesc = "FLAC 无损"

    # ── 杜比全景声(如果可用,覆盖 FLAC) ──
    da = dolby.get("audio")
    if da:
        a = da[0]
        audio_url = a.get("base_url") or (a.get("backupUrl") or [None])[0]
        adesc = "杜比全景声(Dolby Atmos/E-AC-3)"

    # ── 杜比视界仅作为备选(易导致黑屏,不推荐自动使用) ──
    dv = dolby.get("video")
    if dv and not video_url:
        # 只有找不到普通流时才用杜比视界
        v = dv[0]
        video_url = v.get("base_url") or (v.get("backupUrl") or [None])[0]
        vdesc = "杜比视界(Dolby Vision) [兼容性警告]"

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


def launch_player(player_path, video_url, title, audio_url=None, sessdata=None):
    """直接唤起 mpv 播放（从 SMPlayer 目录取的自带 mpv）。
       不走 SMPlayer 中间层，参数原样生效。
    """
    import tempfile

    # 基础命令：兼容性优先，避免 HDR 参数导致 SDR 显示器黑屏
    cmd = [
        player_path,
        video_url,
        f"--force-media-title={title}",
        "--no-config",              # 跳过 SMPlayer 记忆的 mpv.conf 和每文件设置
        "--load-scripts=no",        # 跳过外部脚本，避免干扰
        "--audio-exclusive=no",     # 共享模式，防止独占模式下 E-AC-3 崩溃
        "--ao=wasapi",              # 显式强制 WASAPI，避免降级到 dsound
        "--vo=gpu-next",            # 使用 libplacebo 渲染
        "--gpu-context=d3d11",      # 强制 D3D11 后端，绕过虚拟显示器干扰
        "--log-file=" + str(_CONFIG_DIR / "mpv.log"),  # 诊断日志
    ]

    # B 站：CDN 直链，音视频分离 + cookie 鉴权
    if sessdata:
        cookie_fd, cookie_path = tempfile.mkstemp(
            suffix=".txt", prefix="bili_cookies_", text=True
        )
        with os.fdopen(cookie_fd, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write(".bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\t" + sessdata + "\n")
        atexit.register(lambda p=cookie_path: os.unlink(p) if os.path.exists(p) else None)
        cmd += [
            "--cookies-file=" + cookie_path,
            "--http-header-fields=Referer: " + REFERER,
            "--user-agent=" + UA,
        ]
        if audio_url:
            cmd += [
                f"--audio-file={audio_url}",
                "--audio-demuxer=lavf",            # 显式用 lavf 解复用 .m4s 音频流
                "--demuxer-lavf-probescore=100",   # 提高 m4s 格式探测精度
            ]

    # YouTube：Python 预处理 URL，不需要外部 yt-dlp
    # （URL 已由 process_youtube 通过 yt-dlp extract_info 预处理为直链）

    print(f"    唤起 mpv: {title}")
    # 启动 mpv: 只需抑制控制台弹窗(CREATE_NO_WINDOW), 不能用 SW_HIDE(会隐藏 mpv 主窗口!)
    popen_kw = {}
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, **popen_kw)

    # mpv 读入内存后可删 cookie 文件
    if sessdata:
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


# ============================================================================
# 7. 剪贴板读取 + 全链路
# ============================================================================

def read_clipboard() -> str:
    """读取 Windows 剪贴板文本。
       优先用 PowerShell 原生 API（最可靠），失败则回退 pyperclip。
    """
    # 方式 1: PowerShell Get-Clipboard（用户终端会话下最稳）
    try:
        r = _run_silent(
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

def process_bvid(session, bvid, img_key, sub_key, player_path, sessdata):
    """B 站：CDN 直链 + SMPlayer 透传 mpv 参数。"""
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

    launch_player(player_path, video_url, title, audio_url=audio_url, sessdata=sessdata)


def process_youtube(player_path, ytid):
    """YouTube：Python yt-dlp 提取直链 → mpv 播放（不依赖外部 yt-dlp）。"""
    url = f"https://www.youtube.com/watch?v={ytid}"
    stream_url = url  # 默认回退到原始 URL

    try:
        import yt_dlp
        ydl_opts = {"quiet": True, "no_warnings": True, "format": "best"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            fmt = info.get("url") or ""
            if fmt:
                stream_url = fmt
    except Exception as e:
        print(f"    [!] yt-dlp 预处理失败({e})，回退原始 URL。")

    print(f"    唤起 mpv (YouTube): {url}")
    launch_player(player_path, stream_url, url)
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

    # 检查 SESSDATA 是否有效,过期则清除 .env 并重新询问
    if not validate_sessdata(sessdata):
        print("[!] SESSDATA 已过期,请重新输入。", flush=True)
        ENV_PATH.unlink(missing_ok=True)
        sessdata = load_sessdata()

    player_path = find_player()
    if not player_path:
        print("[!] 未检测到 SMPlayer/mpv，请先安装 SMPlayer。", flush=True)
        sys.exit(1)
    print(f"[+] 播放器: {player_path}", flush=True)

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
                                 player_path, sessdata)
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
                    process_youtube(player_path, ytid)
                except Exception as e:
                    print(f"  [!] 播放失败: {e}", flush=True)
            time.sleep(0.5)
            continue

        # ---- 番剧/电影 (EP/SS) ----
        m = EP_RE.search(text)
        if m:
            ep_id = m.group(1)
            vid_key = f"ep{ep_id}"
            if vid_key != last_vid:
                last_vid = vid_key
                print(f"\n>> 检测到番剧/电影 EP: {ep_id}", flush=True)
                try:
                    bvid, cid, full_title = resolve_episode(session, int(ep_id))
                    print(f"  [+] {full_title} (BV={bvid})", flush=True)
                    data = get_playurl(session, bvid, cid, img_key, sub_key)
                    dash = data.get("dash")
                    if not dash:
                        print("  [!] 未返回 DASH 数据，跳过。", flush=True)
                    else:
                        video_url, audio_url, vdesc, adesc = pick_dolby_streams(dash)
                        if video_url:
                            print(f"  [+] 画质: {vdesc}", flush=True)
                            print(f"  [+] 音轨: {adesc if audio_url else '无'}", flush=True)
                            launch_player(player_path, video_url, full_title, audio_url=audio_url, sessdata=sessdata)
                        else:
                            print("  [!] 未能提取可播放的视频流。", flush=True)
                except Exception as e:
                    print(f"  [!] 播放失败: {e}", flush=True)
            time.sleep(0.5)
            continue

        time.sleep(0.5)


if __name__ == "__main__":
    main()
