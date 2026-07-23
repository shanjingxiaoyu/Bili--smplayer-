#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_yt_player.pyw — 剪贴板直连播放器 GUI

双击启动：首次输入 SESSDATA，之后最小化到后台，复制 B 站/YouTube 链接即播。
"""

import os
import sys
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime
import subprocess as sp
from dotenv import load_dotenv

# ---- subprocess helpers: hide console window on Windows (no flashing cmd) ----
def _popen_silent(*args, **kwargs):
    """Popen with hidden console on Windows."""
    if sys.platform == "win32":
        si = sp.STARTUPINFO()
        si.dwFlags |= sp.STARTF_USESHOWWINDOW
        si.wShowWindow = sp.SW_HIDE
        kwargs.setdefault("startupinfo", si)
        kwargs.setdefault("creationflags", sp.CREATE_NO_WINDOW)
    return sp.Popen(*args, **kwargs)

def _run_silent(*args, **kwargs):
    """subprocess.run with hidden console on Windows."""
    if sys.platform == "win32":
        si = sp.STARTUPINFO()
        si.dwFlags |= sp.STARTF_USESHOWWINDOW
        si.wShowWindow = sp.SW_HIDE
        kwargs.setdefault("startupinfo", si)
        kwargs.setdefault("creationflags", sp.CREATE_NO_WINDOW)
    return sp.run(*args, **kwargs)

# ---- PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，任何 print() 都会崩溃 ----
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# PyInstaller 打包后 __file__ 指向临时目录，改用 sys.executable
# 配置目录：优先使用 %APPDATA%，确保 exe 放在 Program Files 等受限目录时也有写权限
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
else:
    _exe_dir = Path(__file__).resolve().parent
_CONFIG_DIR = Path(os.environ.get("APPDATA", str(_exe_dir))) / "BiliYTPlayer"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = _CONFIG_DIR / ".env"
BV_RE = re.compile(r"(BV[a-zA-Z0-9]{10})")
YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})")


# =============================================================================
# 浏览器配置页（替代 tkinter 弹框）
# =============================================================================

_CONFIG_HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>配置 SESSDATA</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Microsoft YaHei",sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#fff;border-radius:12px;padding:32px 28px;width:420px;box-shadow:0 4px 24px rgba(0,0,0,.08)}
h2{font-size:18px;margin-bottom:6px;color:#1a1a1a}
.desc{font-size:13px;color:#666;line-height:1.8;margin-bottom:16px}
.desc b{color:#0078d4}
input{width:100%;padding:10px 12px;font-size:13px;border:1px solid #d0d5dd;border-radius:6px;outline:none;font-family:monospace}
input:focus{border-color:#0078d4;box-shadow:0 0 0 3px rgba(0,120,212,.1)}
.btn{width:100%;padding:10px;margin-top:12px;border:none;border-radius:6px;font-size:14px;font-weight:bold;cursor:pointer;color:#fff;background:#0078d4}
.btn:hover{background:#106ebe}
.msg{margin-top:10px;font-size:12px;text-align:center}
.msg.ok{color:#107c10}
.msg.err{color:#d83b01}
</style></head><body>
<div class="card">
<h2>首次配置 — B 站 SESSDATA</h2>
<div class="desc">
<b>浏览器登录 bilibili.com</b> → F12 → Application → Cookies → <br>
www.bilibili.com → 找到 <b>SESSDATA</b> → 双击 Value 复制 → 粘贴到下方
</div>
<input id="sd" type="password" placeholder="粘贴 SESSDATA 到这里…" autofocus>
<button class="btn" onclick="submit()">保存并启动</button>
<div id="msg" class="msg"></div>
</div>
<script>
async function submit(){
  const val=document.getElementById('sd').value.trim();
  if(!val){document.getElementById('msg').className='msg err';document.getElementById('msg').textContent='请粘贴 SESSDATA';return}
  try{
    const r=await fetch('/save?sessdata='+encodeURIComponent(val));
    if(r.ok){document.getElementById('msg').className='msg ok';document.getElementById('msg').textContent='已保存！窗口即将关闭…';setTimeout(()=>{window.close()},800)}
    else{const t=await r.text();document.getElementById('msg').className='msg err';document.getElementById('msg').textContent='失败: '+t}
  }catch(e){document.getElementById('msg').className='msg err';document.getElementById('msg').textContent='连接失败，请刷新重试'}
}
</script>
</body></html>"""


def _web_sessdata_input(env_path: Path) -> str | None:
    """启动临时 HTTP 服务 → 浏览器打开配置页 → 等待用户提交 → 保存 .env → 返回 SESSDATA。"""
    import webbrowser
    import json
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    result = {"value": None, "done": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/" or path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_CONFIG_HTML.encode())
            elif path == "/save":
                qs = parse_qs(urlparse(self.path).query)
                sd = qs.get("sessdata", [""])[0].strip().strip("\"'")
                if sd:
                    env_path.write_text(f"# B 站登录态 Cookie\nSESSDATA={sd}\n", encoding="utf-8")
                    result["value"] = sd
                    result["done"] = True
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"empty")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass  # 静默 HTTP 日志

    server = HTTPServer(("127.0.0.1", 18921), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    webbrowser.open("http://127.0.0.1:18921")
    print("[*] 已打开浏览器配置页面，请在页面中粘贴 SESSDATA。", flush=True)

    # 轮询等待用户提交
    while not result["done"]:
        time.sleep(0.3)

    server.shutdown()
    print("[+] SESSDATA 已保存。", flush=True)
    return result["value"]


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("剪贴板直连播放器 — B站 / YouTube")
        self.root.geometry("480x420")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self.sessdata = None
        self.running = False
        self.paused = False
        self.history: list[str] = []

        if ENV_PATH.exists():
            load_dotenv(ENV_PATH)
            self.sessdata = os.getenv("SESSDATA", "").strip() or None

        self._build_ui()

        if not self.sessdata:
            # 无 SESSDATA → 浏览器弹 HTML 配置页
            self.sessdata = _web_sessdata_input(ENV_PATH)
            if not self.sessdata:
                self.root.destroy()
                sys.exit(0)

        self._show_status_page()
        self.start_monitor()

    # ---------- UI ----------
    def _build_ui(self):
        self.main_frame = ttk.Frame(self.root, padding=15)
        self.main_frame.pack(fill="both", expand=True)

        ttk.Label(
            self.main_frame, text="剪贴板直连播放器 — B站 / YouTube",
            font=("Microsoft YaHei", 12, "bold"),
        ).pack(pady=(0, 10))

        # ---- 状态日志 ----
        log_frame = ttk.LabelFrame(self.main_frame, text="状态", padding=6)
        log_frame.pack(fill="both", expand=True)

        self.status_text = tk.Text(
            log_frame, height=10, width=56, state="disabled",
            font=("Consolas", 9), bg="#fafafa", relief="flat", border=0,
        )
        self.status_text.pack(fill="both", expand=True)

        # ---- 播放历史 ----
        hist_frame = ttk.LabelFrame(self.main_frame, text="播放历史", padding=6)
        hist_frame.pack(fill="both", expand=True, pady=(8, 0))

        self.hist_text = tk.Text(
            hist_frame, height=4, width=56, state="disabled",
            font=("Consolas", 9), bg="#fafafa", relief="flat", border=0,
        )
        self.hist_text.pack(fill="both", expand=True)

        # ---- 按钮栏 ----
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(fill="x", pady=(10, 0))

        self.pause_btn = ttk.Button(btn_frame, text="暂停监听", command=self.toggle_pause)
        self.pause_btn.pack(side="left")

        ttk.Button(btn_frame, text="清空历史", command=self._clear_history).pack(side="left", padx=6)

        ttk.Button(btn_frame, text="退出", command=self._quit).pack(side="right")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.status_text.configure(state="normal")
        self.status_text.insert("end", f"[{ts}] {msg}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def _add_history(self, platform, vid, title, quality, audio):
        ts = datetime.now().strftime("%H:%M")
        line = f"[{ts}] {platform} {vid}  {title}  |  {quality}  {audio}"
        self.history.append(line)
        self.hist_text.configure(state="normal")
        self.hist_text.insert("end", line + "\n")
        self.hist_text.see("end")
        self.hist_text.configure(state="disabled")

    def _clear_history(self):
        self.history.clear()
        self.hist_text.configure(state="normal")
        self.hist_text.delete("1.0", "end")
        self.hist_text.configure(state="disabled")

    # ---------- SESSDATA 输入页 ----------
    def _show_sessdata_page(self):
        win = tk.Toplevel(self.root)
        win.title("首次配置")
        win.geometry("450x280")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", self._quit)

        ttk.Label(
            win, text="首次使用，请输入 B 站 SESSDATA",
            font=("Microsoft YaHei", 11, "bold"),
        ).pack(pady=(15, 5))

        ttk.Label(
            win,
            text=(
                "浏览器登录 bilibili.com\n"
                "按 F12 → Application → Cookies → www.bilibili.com\n"
                "找到 SESSDATA，复制 Value 粘贴到下方"
            ),
            justify="left",
        ).pack(pady=(0, 10))

        entry = ttk.Entry(win, width=50, show="*")
        entry.pack(pady=5)

        def save():
            val = entry.get().strip().strip("\"'")
            if not val:
                messagebox.showwarning("提示", "请输入 SESSDATA")
                return
            ENV_PATH.write_text(
                "# B 站登录态 Cookie\nSESSDATA=" + val + "\n",
                encoding="utf-8",
            )
            self.sessdata = val
            win.destroy()
            self._show_status_page()
            self.start_monitor()

        ttk.Button(win, text="保存并启动", command=save).pack(pady=(10, 5))
        ttk.Button(win, text="退出", command=self._quit).pack()

        self.root.withdraw()
        win.wait_window()
        self.root.deiconify()

    # ---------- 后端初始化 ----------
    def _show_status_page(self):
        self._log("正在初始化…")
        threading.Thread(target=self._init_backend, daemon=True).start()

    def _init_backend(self):
        from bili_clipboard_dolby import find_player, get_wbi_keys
        import requests

        player_path = find_player()
        if not player_path:
            self.root.after(0, lambda: self._log("[!] 未找到播放器"))
            player_path = filedialog.askopenfilename(
                title="请手动选择 smplayer.exe",
                filetypes=[("SMPlayer", "smplayer.exe"), ("所有文件", "*.*")],
            )
            if not player_path:
                self._log("[!] 未选择播放器，功能不可用。")
                self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))
                return

        self.player_path = player_path
        self._log(f"[+] 播放器: {player_path}")

        self.session = requests.Session()
        self.session.cookies.set("SESSDATA", self.sessdata, domain=".bilibili.com")

        try:
            self.img_key, self.sub_key = get_wbi_keys(self.session)
            self._log("[+] B 站鉴权就绪。")
        except Exception as e:
            self._log(f"[!] B 站鉴权失败: {e}")
            self.root.after(0, lambda: self.pause_btn.configure(state="disabled"))
            return

        try:
            import yt_dlp  # noqa
            self.yt_ok = True
            self._log("[+] YouTube 就绪 (yt-dlp)。")
        except ImportError:
            self.yt_ok = False
            self._log("[!] YouTube 不可用：需 pip install yt-dlp")

        self._log("[*] 监听中 — 复制 B 站 / YouTube 链接即可播放。")
        self.root.after(0, lambda: self.pause_btn.configure(text="暂停监听", state="normal"))
        self.root.after(0, self.start_monitor)

    # ---------- 监听控制 ----------
    def start_monitor(self):
        if self.running:
            return
        self.running = True
        self.paused = False
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.configure(text="恢复监听")
            self._log("[*] 已暂停监听。")
        else:
            self.pause_btn.configure(text="暂停监听")
            self._log("[*] 已恢复监听。")

    def _monitor_loop(self):
        last_vid = ""
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue

            text = _read_clipboard()
            m = BV_RE.search(text)
            if m:
                vid = m.group(1)
                if vid != last_vid:
                    last_vid = vid
                    self._log(f">> B 站: {vid}")
                    try:
                        self._play_bili(vid)
                    except Exception as e:
                        self._log(f"  [!] {e}")
                time.sleep(0.5)
                continue

            m = YT_RE.search(text)
            if m:
                vid = m.group(1)
                if vid != last_vid:
                    last_vid = vid
                    self._log(f">> YouTube: {vid}")
                    if not getattr(self, "yt_ok", False):
                        self._log("  [!] yt-dlp 未安装，跳过")
                    else:
                        self._play_yt(vid)
                time.sleep(0.5)
                continue

            time.sleep(0.5)

    # ---------- 播放 ----------
    def _play_bili(self, bvid):
        from bili_clipboard_dolby import get_cid, get_playurl, pick_dolby_streams, launch_player
        cid, title = get_cid(self.session, bvid)
        data = get_playurl(self.session, bvid, cid, self.img_key, self.sub_key)
        dash = data.get("dash")
        if not dash:
            self._log("  [!] 无 DASH 数据")
            return
        vurl, aurl, vd, ad = pick_dolby_streams(dash)
        self._add_history("B站", bvid, title, vd, ad or "普通音频")
        launch_player(self.player_path, vurl, title, audio_url=aurl, sessdata=self.sessdata)

    def _play_yt(self, ytid):
        from bili_clipboard_dolby import launch_player
        url = f"https://www.youtube.com/watch?v={ytid}"
        launch_player(self.player_path, url, url)
        self._add_history("YT", ytid, url, "—", "—")

    # ---------- 退出 ----------
    def _quit(self):
        self.running = False
        self.root.destroy()
        sys.exit(0)


def _read_clipboard() -> str:
    try:
        r = _run_silent(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    try:
        App()
        tk.mainloop()
    except Exception:
        import traceback
        _log_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "BiliYTPlayer"
        _log_dir.mkdir(parents=True, exist_ok=True)
        log_path = _log_dir / "BiliYTPlayer_error.log"
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        try:
            import tkinter.messagebox as mb
            mb.showerror("启动失败", f"程序启动失败，错误日志已保存到：\n{log_path}")
        except Exception:
            pass
