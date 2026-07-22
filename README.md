# 🔗 剪贴板直连播放器 — B 站 / YouTube

> 复制链接即播。绕过网页播放器，走 CDN 直链，画质不降级，隐私不追踪。

双击启动 → 首次弹框粘贴 SESSDATA → 之后复制任何 B 站/YouTube 链接，1 秒内 mpv 弹出播放。

---

## 功能

- **B 站**：WBI 动态签名 + CDN 直链，杜比视界/全景声优先提取，自动降级
- **YouTube**：yt-dlp 自动解析最高画质 VP9 + Opus
- **全终端通用**：UWP 客户端、Edge/Chrome、微信、QQ——复制即播
- **零遥测**：mpv 不向 B 站/Google 上报任何观看数据
- **弹框配置**：首次运行弹框粘贴 SESSDATA，不用手动改配置文件

## 安装

### 1. 安装播放器（必需）

推荐 [SMPlayer](https://www.smplayer.info/)（自带 mpv，有 GUI）。  
也可用独立 [mpv](https://mpv.io/installation/)。安装后脚本会自动检测。

### 2. 下载本项目

```bash
git clone https://github.com/你的用户名/repo名.git
cd repo名
pip install -r requirements.txt
```

### 3. 获取 SESSDATA

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. 按 `F12` → **Application** → **Cookies** → `www.bilibili.com`
3. 找到 **SESSDATA**，复制 **Value** 列的内容

### 4. 启动

双击 `启动监听.bat`，或命令行：

```bash
python bili_yt_player.pyw
```

首次运行弹框粘贴 SESSDATA → 窗口显示"监听中"→ 复制链接即可。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `bili_yt_player.pyw` | GUI 主程序（双击启动） |
| `bili_clipboard_dolby.py` | 后端（WBI 签名 / playurl 解析 / 播放器唤起） |
| `启动监听.bat` | Windows 快捷启动 |
| `.env` | SESSDATA 保存文件（已 gitignore） |

---

## FAQ

**Q：SESSDATA 是什么？从哪里来？**  
B 站登录凭证，从浏览器 Cookie 中复制。看第 3 步。

**Q：提示"未检测到播放器"？**  
安装 [mpv](https://mpv.io) 或 [SMPlayer](https://www.smplayer.info/)，脚本会自动搜。搜不到会弹文件选择框让你手动指。

**Q：YouTube 不能播？**  
`pip install yt-dlp`。mpv 依赖 yt-dlp 解析 YouTube 流。

**Q：SESSDATA 过期了？**  
删掉 `.env` 文件重新运行，弹框输入新的即可。

---

## License

MIT
