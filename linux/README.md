# Token Eye — Linux 移植版

> 在 UKUI 3.25（麒麟 V10 SP1）系统托盘实时监控根 `providers.json` 中 5 个平台的 LLM 用量
> （DeepSeek / MiniMax / MiMo / 智谱 GLM / 千问 Qwen；Linux 直接复用根配置，无独立副本）

## 截图效果

系统托盘区显示 👁 风格图标（绿/橙/红三态，随最差 provider 变色），**右键**展开详情菜单（UKUI 3.25 host 设计：右键弹菜单、左键无响应）：

- ✅ DeepSeek: ¥xx.xx（余额 + 今日消耗；消耗行仅在当天余额下降时出现，候选行随上游核心一起走）
- ✅ MiniMax: 5h/7d 进度条 + 重置倒计时
- ✅ 智谱 GLM: ¥xx.xx（余额）
- ✅ MiMo: ¥xx.xx（Chromium 登录 Cookie 自动提取，见下文）
- 千问 Qwen：根配置中启用，但 Linux 端登录自愈脚本缺失（见「已知限制」）

> 💡 麒麟系统无 emoji 字体，菜单中的无字形 emoji（🔄🔴🔑🔥等）会被自动降级为纯文本（状态由行颜色表达）。

## 与上游的关系

本目录 (`linux/`) **复用上游数据层**：直接 import `swiftbar/token_eye.py` 的核心逻辑
（fetch/缓存/解析/告警/历史/消耗估算），并 patch 平台耦合点。但**菜单是 Linux
独立实现**（AppIndicator/GTK，不是 SwiftBar 菜单层）——上游 `run()` 的菜单输出不会
在这里自动生效；上游 `process_provider` 返回的 `result` 结构一旦变化，`rebuild_menu()`
需同步复核调整。

| 上游函数 | macOS 实现 | 本机 Linux 实现 |
|---|---|---|
| `get_key()` | `security` (Keychain) | `secretstorage` (gnome-keyring) |
| `send_notify()` | `osascript` (通知中心) | `notify-send`（失败写 debug 日志） |
| `_open_login_page()` | `open` 命令 | 优先 Chromium 打开（兜底 `xdg-open`），成功后才写冷却标记 |
| `fetch_api()` timeout | 5s/10s | 20s/35s（手机热点友好），包装器按 `*args/**kwargs` 转发 |

因此 `git pull` 后**并非零冲突**：数据层（字段解析、告警规则）随上游同步，但菜单文案、
`result` 结构解读、图标状态映射等由本目录维护，上游相关改动需人工复核。钥匙环解锁语义
已抽到 `keyring_common.py`，三个脚本共用并用 `is_locked()` 复核，消除
`Collection.unlock()` 返回值口径分歧。

## 架构

```
~/dev/token-eye/
├── swiftbar/token_eye.py   ← 上游核心（只读 import，不改一行）
├── providers.json          ← 上游配置（5 个 platform，Linux 直接读）
├── linux/
│   ├── token-eye-tray.py   ← 托盘主程序（GLib MainLoop + AppIndicator，菜单独立实现）
│   ├── setup-keys.py       ← 密钥管理（写入 gnome-keyring）
│   ├── diag-keyring.py     ← 钥匙环解锁 / 密钥存在性诊断（桌面终端运行）
│   ├── keyring_common.py   ← 解锁语义统一：open_collection + unlock_and_verify
│   ├── install.sh          ← 一键安装（模板生成 service + 图标 + 自启去重）
│   ├── token-eye.service.in ← service 模板（@PYTHON@ / @TRAY@ 占位）
│   ├── token-eye.service   ← 默认示例 unit（实际文件由 install.sh 生成）
│   ├── requirements.txt    ← pip 依赖及最低版本
│   ├── scripts/
│   │   └── refresh-mimo-cookie.py  ← MiMo Cookie 自动提取（Linux 版）
│   └── icons/              ← 三态 PNG（ok/warn/err）
└── tests/                  ← 单测（全仓共 290 个用例，含 Linux 注入层 21 例）
```

## 开机自启（唯一来源：systemd）

自启动**只走 systemd user service**，没有 XDG autostart 兜底项。历史版本曾用
`token-eye.desktop`（autostart 模板，Exec 直接跑 python3）和 `token-eye-start.desktop`
（Exec=systemctl start）做兜底，与 systemd 并存会导致双实例/开关失真。
`install.sh` **只清理这两个固定模板**：删除前打印清单，先备份到带时分秒的
`~/.workbuddy/tmp/token-eye-autostart-YYYYmmdd-HHMMSS/`（用 `cp -n`，同日重复执行不覆盖
前次备份）再删；其余 `*token-eye*.desktop` **仅告警、不删除**，避免误删用户自定义项，
如有残留需人工确认。

开关统一用命令，桌面环境的「开机启动」列表里**不会出现 Token Eye**（预期行为，非故障）：

```bash
systemctl --user enable token-eye    # 开机自启
systemctl --user disable token-eye   # 关闭自启
```

## 快速开始

```bash
# 1. 一键安装
bash ~/dev/token-eye/linux/install.sh

# 2. 写入 API Key（交互式）
python3 ~/dev/token-eye/linux/setup-keys.py

# 3. 托盘自动运行（或注销重登）
```

## 依赖与 Python 版本

- **Python ≥ 3.7**（f-string、`subprocess.run(capture_output=)`、`ThreadPoolExecutor` 等）。
- pip 依赖及最低版本见 `linux/requirements.txt`：

  ```bash
  python3 -m pip install -r ~/dev/token-eye/linux/requirements.txt
  ```

  `secretstorage>=3.3`（钥匙环读写）、`cryptography>=3.4`（MiMo Cookie 解密）、
  `dbus-python>=1.2`（部分发行版 `secretstorage` 的 D-Bus 后端）。
- **系统包**（由发行版包管理器安装，非 pip）：`python3-gi`、
  `gir1.2-ayatana-appindicator3`（或 `gir1.2-appindicator3-0.1`）、
  `python3-secretstorage`、`python3-dbus`、`python3-cryptography`、`curl`、
  `notify-send`、剪贴板工具（`wl-copy` 或 `xclip`）、Chromium。AppIndicator 优先加载
  `AyatanaAppIndicator3`，缺失时回退 `AppIndicator3`。
- `install.sh` 逐项检查依赖：致命项（gi/AppIndicator、`secretstorage`）缺失即退出，
  软依赖缺失只告警不阻断；`systemctl --user` 三步失败会显式提示并给出手动拉起的
  降级方式，不再无条件报「已装并启动」。service 由 `token-eye.service.in` 按 `$PYTHON`
  与 install.sh 实际所在目录（`$LINUX_DIR`）注入生成，仓库放在任意路径或换用 venv
  解释器都能启动。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PYTHON` | `/usr/bin/python3` | install.sh 使用的解释器（可指向 venv），并注入生成的 service |
| `TOKEN_EYE_REFRESH` | `30` | 托盘轮询间隔（秒） |
| `TOKEN_EYE_SHOW_LABEL` | `0` | `1` 时图标旁显示文字汇总（UKUI 可能不实现 SNI label） |
| `TOKEN_EYE_BROWSER` | 自动探测 | 优先浏览器：可执行名/绝对路径；`default` 强制走 `xdg-open` |
| `TOKEN_EYE_DEBUG` | `0` | `1` 时写 `~/.cache/token-eye/debug.log`（通知失败、未知状态等留痕） |

> systemd 服务里加 `Environment=...` 后需 `systemctl --user daemon-reload &&
> systemctl --user restart token-eye` 生效。service 不再硬编码 `DISPLAY` /
> `WAYLAND_DISPLAY`（由会话继承），`DBUS_SESSION_BUS_ADDRESS` 用 `unix:path=%t/bus`。

## 密钥管理

根配置 5 个平台中，需要 API Key / Cookie 的 4 个存入 **gnome-keyring**
（`secretstorage` 库），不落明文文件；千问 Qwen 是 `command` 型（由外部 CLI
`qianwen` 自行管理凭证，无 `keychainService`），见「已知限制」：

| 平台 | Service 名 | 鉴权方式 | 说明 |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | Bearer | platform.deepseek.com → API Keys |
| MiniMax | `MINIMAX_CN_API_KEY` | Bearer | platform.minimaxi.com → 开发设置 |
| 智谱 GLM | `GLM_API_KEY` | 裸 key（无 Bearer） | bigmodel.cn → API Keys |
| MiMo | `MIMO_PLATFORM_TOKEN` | Cookie | 需在 **Chromium** 登录后自动提取（见下） |

### MiMo Cookie 提取（已验证 ✅）

MiMo 的余额查询 API 不支持 Bearer key，需要浏览器登录态。**本机方案：用 Chromium 登录 MiMo**（日常浏览仍用 360；360 安全浏览器加密实现非标准，外部不可解，不要用 360 登录 MiMo）：

1. 在 **Chromium** 打开 `platform.xiaomimimo.com` 并登录
2. 运行：

```bash
python3 ~/dev/token-eye/linux/scripts/refresh-mimo-cookie.py
```

脚本按 **Chromium → Edge → Chrome** 顺序扫描浏览器 Cookie 数据库，提取（v11/AES-CBC 解密，结果须为可打印 ASCII）→ 调 balance API 校验 → **响应体有 `data` 对象、无业务错误码且 HTTP 200 才写 keyring 并打印 `HTTP=200`**；失败结论走 stdout 供上游 `auto_refresh_cookie` 读取，避免 HTTP 200 + `{"code":401}` 之类业务错误体被误判成功（假绿）。临时 Cookie 库副本权限收紧为 `0600`。

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

直接编辑根 `~/dev/token-eye/providers.json` 追加 provider：数据层（拉取 / 解析 /
告警）随上游自动生效；但菜单是 Linux 独立实现，若上游 `process_provider` 返回的
`result` 结构变化，`rebuild_menu()` 需同步复核。详见上游 README。

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
- **千问 Qwen**：根配置为 `command` 型，依赖外部 `qianwen` CLI 与 `~/.local/bin/qianwen`；
  Linux 端缺 `linux/scripts/qwen-login.py` 登录自愈脚本，CLI 不存在时该平台余额与
  自动登录续期静默不可用——是否有意不支持待确认，临时方案是在本机安装 `qianwen` CLI
- 钥匙环状态分三态：`已锁定`（菜单给「解锁钥匙环」入口）、`不可用`（D-Bus / gnome-keyring
  未就绪，只提示确认桌面会话）、`正常`；`unavailable` 不会误导成「去加 Key」
- 版本自检移到后台线程（结果经 `GLib.idle_add` 回传），新版本提示在下一轮常规刷新出现，
  不会阻塞 GTK 主线程；`check_latest_version` 读第三方镜像，仅在 `TOKEN_EYE_DEBUG=1`
  时留痕，无完整性校验

## License

MIT（沿用上游）
