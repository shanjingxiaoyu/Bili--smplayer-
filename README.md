# BiliYTPlayer — B 站 / YouTube 剪贴板直连播放器

> 复制链接即播。绕过网页播放器，走 CDN 直链，画质不降级，隐私不追踪。

双击启动 → 首次弹框粘贴 SESSDATA → 复制链接 1 秒内 mpv 弹出播放。**内置 mpv，开箱即用。**

---

## 支持的链接格式

| 格式 | 示例 | 来源 |
|------|------|------|
| `BV` | `BV1GJ411x7h7` 或任意含 BV 号的 URL | 普通视频 |
| `EP` | `bilibili.com/bangumi/play/ep780621` | 番剧/电影/纪录片 |
| `YouTube` | `youtube.com/watch?v=xxx` 或 `youtu.be/xxx` | YouTube |

---

## 功能

- **B 站**：WBI 动态签名 + CDN 直链，4K HDR / 杜比全景声优先，自动降级
- **番剧/电影**：EP 链接自动解析 → bvid + cid → 走同一条 DASH 管道
- **YouTube**：yt-dlp 自动解析最高画质 VP9 + Opus
- **画质**：普通高清流优先（兼容性最好），Dolby Vision 仅作备选
- **音频**：显式 WASAPI 输出，支持 5.1 杜比全景声
- **全终端通用**：UWP 客户端、Edge/Chrome、微信、QQ——复制即播
- **零遥测**：mpv 不向 B 站/Google 上报任何观看数据
- **弹框配置**：首次运行浏览器弹 HTML 表单粘贴 SESSDATA，体验优于 tkinter 弹框

---

## 安装

### 开箱即用（推荐）

下载 [Release](https://github.com/shanjingxiaoyu/Bili--smplayer-/releases) 中的 `BiliYTPlayer_release.zip`，解压后双击 `BiliYTPlayer.exe`。**不需要安装 Python、不需要安装 mpv。**

### 从源码运行

```bash
git clone https://github.com/shanjingxiaoyu/Bili--smplayer-.git
cd Bili--smplayer-
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe bili_yt_player.pyw
```

安装播放器（如果不用自带便携版）：

- [mpv](https://mpv.io/installation/)（推荐）或 [SMPlayer](https://www.smplayer.info/)
- 程序会自动搜索 `C:/D:Program Files`、PATH、注册表、快捷方式
- 搜不到会弹文件选择框让你手动指

### 获取 SESSDATA

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. 按 `F12` → **Application** → **Cookies** → `www.bilibili.com`
3. 找到 **SESSDATA**，复制 **Value** 列的内容
4. 首次运行程序时粘贴

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `bili_yt_player.pyw` | GUI 主程序（双击启动） |
| `bili_clipboard_dolby.py` | 后端引擎（WBI 签名 / playurl 解析 / EP 解析 / 播放器唤起） |
| `BiliYTPlayer.exe` | 编译好的独立 exe（PyInstaller 打包） |
| `bili_yt_player.spec` | PyInstaller 打包配置 |
| `build_exe.bat` | 一键打包脚本 |
| `启动监听.bat` | Windows 源码快捷启动 |
| `mpv-portable/` | 内置便携版 mpv（v0.41） |

---

## 自行打包

```bash
# 安装依赖
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pip install -r requirements.txt

# 打包（需设置环境变量绕过沙箱安全策略）
set SAFE_DELETE_DISABLE=1
.venv\Scripts\python.exe -m PyInstaller --noconfirm bili_yt_player.spec

# 产物：dist\BiliYTPlayer.exe（约 21MB，UPX 压缩）
```

---

## FAQ

**Q：电影/番剧复制没反应？**
请复制带 `ep` 编号的链接，如 `bilibili.com/bangumi/play/ep780621`。程序通过 `pgc/view/web/season` API 获取 bvid + cid。

**Q：提示"未检测到播放器"？**
确认 `mpv-portable/mpv.exe` 与 exe 在同一目录。或安装独立 [mpv](https://mpv.io)。

**Q：SESSDATA 过期了？**
删掉 `%APPDATA%\BiliYTPlayer\.env` 文件重新运行，弹框输入新的。

**Q：YouTube 不能播？**
已内置 yt-dlp，无需额外安装。exe 版包含完整 yt-dlp 依赖。

**Q：有声音无画面？**
已修复。确保使用最新版 exe（≥ 2024-07-24）。

---

## License

MIT
