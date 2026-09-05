# Token Eye — Linux 移植版

> 在 UKUI 3.25（麒麟 V10 SP1）系统托盘实时监控 DeepSeek / MiniMax / MiMo 的 LLM 用量

## 截图效果

系统托盘区显示 👁 风格图标（绿/橙/红三态，随最差 provider 变色），**右键**展开详情菜单（UKUI 3.25 host 设计：右键弹菜单、左键无响应）：

- ✅ DeepSeek: ¥xx.xx（余额 + 今日消耗 + 预计可用天数 + 近 7 天柱状）
- ✅ MiniMax: 5h/7d 进度条 + 重置倒计时
- ✅ MiMo: ¥xx.xx（Edge 登录 Cookie 自动提取，见下文）

> 💡 麒麟系统无 emoji 字体，菜单中的无字形 emoji（🔄🔴🔑🔥等）会被自动降级为纯文本（状态由行颜色表达）。

## 与上游的关系

本目录 (`linux/`) 是**零改动上游**的注入层——直接 import `swiftbar/token_eye.py` 核心逻辑（fetch/缓存/解析/告警/历史/消耗估算/趋势线），仅 patch 4 处平台耦合点：

| 上游函数 | macOS 实现 | 本机 Linux 实现 |
|---|---|---|
| `get_key()` | `security` (Keychain) | `secretstorage` (gnome-keyring) |
| `send_notify()` | `osascript` (通知中心) | `notify-send` |
| `_open_login_page()` | `open` 命令 | `xdg-open` |
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
| MiMo | `MIMO_PLATFORM_TOKEN` | Cookie | 需在 **Edge** 登录后自动提取（见下） |

### MiMo Cookie 提取（已验证 ✅）

MiMo 的余额查询 API 不支持 Bearer key，需要浏览器登录态。**本机方案：用 Edge Linux 登录 MiMo**（日常浏览仍用 360；360 安全浏览器加密实现非标准，外部不可解，不要用 360 登录 MiMo）：

1. 在 **Edge** 打开 `platform.xiaomimimo.com` 并登录
2. 运行：

```bash
python3 ~/dev/token-eye/linux/scripts/refresh-mimo-cookie.py
```

脚本自动从 Edge Cookie 数据库提取（v11/AES-CBC 解密）→ 写入 gnome-keyring → 调 API 验证（2026-09-02 实测 HTTP 200）。

**Cookie 过期自愈**：托盘检测到 MiMo 401 时会自动重跑本脚本（上游内建逻辑，带防抖限频），只要 Edge 里 MiMo 仍是登录态就会无感续期；若 Edge 会话也过期，重新在 Edge 登录一次 MiMo 即可。

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

## 已知限制

- UKUI 托盘区只显示图标，不支持菜单栏文字汇总（SNI label 字段 UKUI 未实现）
- MiMo 余额依赖 **Edge** 登录态（360 浏览器加密非标准不可用），Cookie 过期后重跑刷新脚本
- 手机热点网络不稳定时，curl 可能超时（已放宽到 20s/35s，可按需调整）

## License

MIT（沿用上游）
