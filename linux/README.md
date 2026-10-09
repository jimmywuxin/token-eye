# Token Eye — Linux 移植版

> 在 UKUI 3.25（麒麟 V10 SP1）系统托盘实时监控 DeepSeek / MiniMax / MiMo 的 LLM 用量

## 截图效果

系统托盘区显示 👁 风格图标（绿/橙/红三态，随最差 provider 变色），**右键**展开详情菜单（UKUI 3.25 host 设计：右键弹菜单、左键无响应）：

- ✅ DeepSeek: ¥xx.xx（余额 + 今日消耗 + 预计可用天数 + 近 7 天柱状）
- ✅ MiniMax: 5h/7d 进度条 + 重置倒计时
- ✅ MiMo: ¥xx.xx（Chromium 登录 Cookie 自动提取，见下文）

> 💡 麒麟系统无 emoji 字体，菜单中的无字形 emoji（🔄🔴🔑🔥等）会被自动降级为纯文本（状态由行颜色表达）。

## 与上游的关系

本目录 (`linux/`) 是**零改动上游**的注入层——直接 import `swiftbar/token_eye.py` 核心逻辑（fetch/缓存/解析/告警/历史/消耗估算/趋势线），仅 patch 4 处平台耦合点：

| 上游函数 | macOS 实现 | 本机 Linux 实现 |
|---|---|---|
| `get_key()` | `security` (Keychain) | `secretstorage` (gnome-keyring) |
| `send_notify()` | `osascript` (通知中心) | `notify-send` |
| `_open_login_page()` | `open` 命令 | 优先 Chromium 打开（兜底 `xdg-open`） |
| `fetch_api()` timeout | 5s/10s | 20s/35s（手机热点友好） |

**上游升级零冲突**：`cd ~/dev/token-eye && git pull` 即可——Linux 层自动适配。

## 架构

```
~/dev/token-eye/
├── swiftbar/token_eye.py   ← 上游核心（只读 import，不改一行）
├── providers.json          ← 上游配置（直接读，零维护）
├── linux/
│   ├── token-eye-tray.py   ← 托盘主程序（GLib MainLoop + AppIndicator3）
│   ├── setup-keys.py       ← 密钥管理（写入 gnome-keyring）
│   ├── install.sh          ← 一键安装（service + autostart + 图标）
│   ├── token-eye.service   ← systemd user service（崩溃自动重启）
│   ├── token-eye.desktop   ← autostart 兜底
│   ├── scripts/
│   │   └── refresh-mimo-cookie.py  ← MiMo Cookie 自动提取（Linux 版）
│   └── icons/              ← 三态 PNG（ok/warn/err）
└── tests/                  ← 上游单元测试（129 个用例，Python 3.8 验证通过）
```

## 快速开始

```bash
# 1. 一键安装
bash ~/dev/token-eye/linux/install.sh

# 2. 写入 API Key（交互式）
python3 ~/dev/token-eye/linux/setup-keys.py

# 3. 托盘自动运行（或注销重登）
```

## 密钥管理

三个平台的 key 存入 **gnome-keyring**（`secretstorage` 库），不落明文文件：

| 平台 | Service 名 | 鉴权方式 | 说明 |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | Bearer | platform.deepseek.com → API Keys |
| MiniMax | `MINIMAX_CN_API_KEY` | Bearer | platform.minimaxi.com → 开发设置 |
| MiMo | `MIMO_PLATFORM_TOKEN` | Cookie | 需在 **Chromium** 登录后自动提取（见下） |

### MiMo Cookie 提取（已验证 ✅）

MiMo 的余额查询 API 不支持 Bearer key，需要浏览器登录态。**本机方案：用 Chromium 登录 MiMo**（日常浏览仍用 360；360 安全浏览器加密实现非标准，外部不可解，不要用 360 登录 MiMo）：

1. 在 **Chromium** 打开 `platform.xiaomimimo.com` 并登录
2. 运行：

```bash
python3 ~/dev/token-eye/linux/scripts/refresh-mimo-cookie.py
```

脚本按 **Chromium → Edge → Chrome** 顺序扫描浏览器 Cookie 数据库，提取（v11/AES-CBC 解密）→ 写入 gnome-keyring → 调 API 验证（2026-09-02 实测 Edge 源 HTTP 200）。

**Cookie 过期自愈**：托盘检测到 MiMo 401 时会自动重跑本脚本（上游内建逻辑，带防抖限频），只要 Chromium 里 MiMo 仍是登录态就会无感续期；若会话也过期，Token Eye 会**直接用 Chromium 打开 MiMo 登录页**（不走系统默认浏览器——本机默认是 360，在 360 里登录等于白登，刷新脚本读不到），重新在 Chromium 登录一次即可。

> **浏览器偏好**（`linux/token-eye-tray.py` 的 `open_in_browser()`）：托盘打开任何平台链接（MiMo 登录页、菜单里的控制台跳转）都优先调 Chromium（`chromium-browser` / `chromium` / `chromium-browser-stable` 依序探测），无 Chromium 才回退 `xdg-open`。
> 覆盖方式：环境变量 `TOKEN_EYE_BROWSER=chromium-browser`（可执行名或绝对路径）；`TOKEN_EYE_BROWSER=default` 强制走系统默认浏览器。systemd 用户服务里加 `Environment=TOKEN_EYE_BROWSER=...` 并 `systemctl --user daemon-reload && systemctl --user restart token-eye` 生效。
>
> 注：登录 MiMo 用的是 Chromium 的**默认 profile**（`~/.config/chromium`），与 OA 取件专用 profile（`--user-data-dir=~/.workbuddy/oa-profile`）互相隔离——刷新脚本只扫默认 profile 及 `Profile *`。

## 管理命令

```bash
# 查看状态
systemctl --user status token-eye

# 实时日志
journalctl --user -u token-eye -f

# 重启
systemctl --user restart token-eye

# 自检（key / 配置 / 网络）
python3 ~/dev/token-eye/linux/token-eye-tray.py --check

# 单次拉取（排障，不启动 GUI）
python3 ~/dev/token-eye/linux/token-eye-tray.py --once
```

## 添加新平台

直接编辑上游 `~/dev/token-eye/providers.json`，追加 provider 配置，无需改任何代码。
详见上游 README。

## 排障（Troubleshooting）

### 托盘全显「未配置 Key」/ 余额用量全不显示

先看数据管线停更时间（cache/history 的 mtime 就是最后一次成功拉取时间）：

```bash
ls -la ~/.cache/token-eye/token-eye-cache-*.json ~/.cache/token-eye/history-*.jsonl
```

**头号原因：gnome-keyring 取消 / 锁定 / 被重置**。token-eye 的所有 key、MiMo Cookie、Chromium 的 Safe Storage 全存在默认钥匙环里，钥匙环一没，全部静默失效（`linux_get_key` 读不到只返回空串，不留任何日志）。判定：

```bash
ls -la ~/.local/share/keyrings/   # 看 .keyring 文件与 default 指针的变更时间
```

- 若 `default` 指针被改到新建的空钥匙环，把旧 `.keyring` 文件拷回该目录、`default` 写回旧环名称，然后重启钥匙环与托盘：`gnome-keyring-daemon -r -d && systemctl --user restart token-eye`
- 弹解锁框输入登录密码即可（旧环密码通常 = 登录密码）
- ⚠️ 副作用：取消钥匙环会让 Chromium 的加密密钥更换，浏览器里所有网站的登录态 Cookie 作废被清，需重新登录

### MiMo 自动刷新一直报「未找到完整 Cookie」

说明 Chromium 的 Cookies 库里没有平台的 4 个 Cookie（`api-platform_ph` / `api-platform_serviceToken` / `api-platform_slh` / `userId`）。

判定（关键坑）：**小米账号 SSO 成功 ≠ 平台登录完成**。账号域的 passToken/userId 已落库、余额页看起来也打开了，但 STS 那步没走完时，平台 Cookie 一个都不会落库——此时托盘自动刷新永远抓不到。直接查库：

```bash
cp ~/.config/chromium/Default/Cookies /tmp/ck.db
sqlite3 /tmp/ck.db "SELECT host_key, name FROM cookies WHERE host_key LIKE '%xiaomimimo%' OR name LIKE 'api-platform%';"
```

- 查得到 4 个 Cookie → 保持 Chromium 开着，点托盘「🔄 立即刷新」
- 查不到 → 在 Chromium 重新打开余额页 `https://platform.xiaomimimo.com/console/balance?userId=<你的userId>`，让页面完全加载（STS 走完、Cookie 落库），再点「立即刷新」

注意：刷新脚本读的是 Cookies 数据库文件，Cookie 还在浏览器内存里没落库时（刚登录完的几十秒内）也读不到；Chromium 开着约 30 秒后会自动落库。

## 已知限制

- UKUI 托盘区只显示图标，不支持菜单栏文字汇总（SNI label 字段 UKUI 未实现）
- MiMo 余额依赖 **Chromium** 登录态（360 浏览器加密非标准不可用），Cookie 过期后重跑刷新脚本
- 手机热点网络不稳定时，curl 可能超时（已放宽到 20s/35s，可按需调整）

## License

MIT（沿用上游）
