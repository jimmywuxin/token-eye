# Token Eye 👁

macOS 菜单栏 LLM Token 用量实时监控插件，基于 SwiftBar + Bash + Python。

**无 Node.js、无构建步骤、无后台进程** — 只需一个 Shell 脚本。

## 技术栈

- **SwiftBar** — macOS 菜单栏插件运行时（brew install --cask swiftbar）
- **Bash** — 启动器（token-eye.sh），SwiftBar 每 30 秒执行一次
- **Python** — 核心逻辑（token_eye.py），处理 JSON 解析、Keychain 读取、API 调用、菜单渲染
- **macOS Keychain** — API Key 安全管理
- **curl + security CLI** — API 请求和 Keychain 读取
- **Android 版（android/ 目录）** — Kotlin + Compose + Glance 小部件 + WorkManager，密钥存 Android Keystore；构建见 `android/README.md`

## 项目结构

```
token-eye/
├── swiftbar/
│   ├── token-eye.sh       ← 插件启动器，复制到 ~/SwiftBar/
│   └── token_eye.py       ← 核心逻辑（缓存/告警/解析/渲染），从项目目录读取
├── scripts/
│   ├── refresh-mimo-cookie.py  ← MiMo Cookie 一键刷新（多浏览器，会话过期时运行）
│   ├── check-colors.py         ← 配色对比度回归检查（WCAG AA ≥4.5:1）
│   ├── check-config-sync.py    ← 跨端配置同步校验（根 providers.json/holidays ↔ Android assets 副本）
│   ├── validate-schema.py      ← providers.json JSON Schema 校验（零依赖）
│   ├── update-holidays.py      ← 中国法定节假日/调休表更新（make holidays；每年公告后跑）
│   ├── add-provider.py         ← 新平台添加向导（交互式，支持模板）
│   └── provider-templates.json ← 内置平台模板库（OpenAI/Kimi/GLM/…）
├── schema/
│   └── providers.schema.json   ← 配置结构定义（编辑器补全 + 校验）
├── parsers/
│   └── peak_window.py          ← 峰/谷时段判定（含节假日/调休查表）
├── holidays/
│   └── <年>.json               ← 中国法定节假日 + 调休数据（holiday-cn，随仓库分发、运行时不联网）
├── tests/
│   ├── test_token_eye.py       ← 单元测试（unittest，零依赖）
│   └── test_peak_window.py     ← 峰/谷时段 + 节假日单测
├── providers.json         ← 核心配置（JSON），定义所有平台
├── Makefile               ← make install / test / check / holidays
├── .github/workflows/ci.yml    ← CI（语法/测试/Schema/配色/版本一致性）
├── linux/                ← Linux 版（独立实现）
├── android/              ← Android 版（Kotlin + Compose + Glance，详见 android/README.md）
│   ├── app/src/main/java/com/coffeelab/tokeneye/
│   │   ├── core/             ← 核心逻辑（移植 token_eye.py：配置/解析/刷新/告警）
│   │   ├── widget/           ← Glance 桌面小部件
│   │   └── work/             ← WorkManager 定时刷新（15 分钟，系统下限）
│   └── app/src/test/         ← 单元测试（ParserTest / PeakWindowTest）
├── AGENTS.md              ← 本文件（项目指南）
├── README.md
├── CHANGELOG.md
└── DESIGN.md
```

**Mac/Linux 版无 src/、无 dist/、无 package.json — 不需要编译构建；Android 版是独立 Gradle 工程（android/ 内自带 wrapper），不与 Mac 版共用构建。**

## 环境要求

- macOS
- SwiftBar（`brew install --cask swiftbar`）
- Python 3（系统自带 `/usr/bin/python3`）
- `security` CLI（macOS 内置）
- `curl`（macOS 内置）

## 常用命令

### 安装/更新插件
```bash
make install              # 或手动：cp swiftbar/token-eye.sh ~/SwiftBar/ && chmod +x
```

### 质量保障（提交前跑）
```bash
make test                 # 单元测试（unittest，零依赖）
make check                # 全部检查：语法 + 单元测试 + Schema + 跨端配置同步 + 配色对比度
make validate             # 仅 Schema + 跨端配置同步 + 配色
```

### 添加 API Key 到 Keychain
```bash
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-your-key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "your-key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "your-key"
```

### 添加新平台
```bash
/usr/bin/python3 scripts/add-provider.py    # 交互式向导，零代码
```

### 验证 Keychain 中的 Key
```bash
security find-generic-password -s DEEPSEEK_API_KEY -w
```

## 工作原理

```
SwiftBar（每30秒执行）
    ↓
~/SwiftBar/token-eye.sh（薄启动器，自动查找项目目录）
    ↓
$HOME/dev/token-eye/swiftbar/token_eye.py（核心逻辑，单进程，并发）
    ↓
$HOME/dev/token-eye/providers.json（读取配置）
    ↓
Python 核心逻辑：
  1. 检查 /tmp/token-eye-cache-{id}.json 缓存，命中则跳过 API
  2. 从 Keychain 读取各平台 API Key
  3. 并发调用各平台 API（ThreadPoolExecutor）
  4. HTTP 错误分类（5xx/4xx/网络/超时）
  5. 解析响应数据，balance 类检查告警阈值并统计今日消耗
  6. 输出 SwiftBar 格式菜单（含控制台跳转链接）
```

脚本自动查找 `providers.json` 的优先级（`token_eye.py` 同理，位于项目目录 `swiftbar/` 下）：
1. `~/SwiftBar/providers.json`（脚本同目录）
2. `$HOME/dev/token-eye/providers.json`（项目根目录）
3. 项目目录的上一级

## providers.json 配置

### parser 类型

- **balance** — 余额型，适用于 DeepSeek、MiMo（Cookie 鉴权）等有余额 API 的平台
- **plan_usage** — 用量型，适用于 MiniMax 等有按模型用量 API 的平台
- **status** — 状态型，适用于只验证 Key 有效性的平台

### 全局可选字段

- `cache` — 按 parser 类型设置缓存 TTL（秒），默认 balance 300 / plan_usage 30 / status 60
- `menuBar.showSummary` — 菜单栏汇总：false 不显示 / true 全部 / id 数组（如 `["deepseek","mimo"]`）只显示指定平台
- `alerts.{id}.minBalance` — balance 类余额阈值告警（按 parser 类型 balance 的阈值优先级链：API 字段阈值 `parser.fields.alertThreshold` > `provider.alert.minBalance` > `parser.defaultMinBalance` > 不告警；前两项均无则用兜底默认）
- `alerts.{id}.minPct` — plan_usage 类用量告警阈值（**已用%** 方向，与 dsh-cost-meter coding plan 卡片一致；已用% 超过阈值触发告警，如 minimax `{"minPct": 80}`）
- `colors.{dark,light}` — 自适应配色

### provider 可选字段

- `consoleUrl` — 控制台跳转链接，详情菜单末尾显示
- `cacheTtl` — 单 provider 覆盖全局缓存 TTL
- `alert.minBalance` / `alert.minPct` / `alert.dailySpendMax` / `alert.daysLeft` — 单 provider 告警阈值（balance 余额/用量百分比/当日消耗上限/预计可用天数预警）
- `api.headers` — 额外请求头（如 OpenAI Organization、User-Agent）
- `parser.barLength` — 进度条长度，默认 20
- ~~`parser.statusMap`~~ / ~~`parser.fields.intervalStatus` / `weeklyStatus`~~ / ~~`parser.fields.intervalTotal` / `weeklyTotal`~~ — **已废弃，`token_eye.py` 与 Android `ResultParser` 都不读取**：老接口的「状态码→文案映射」与「按次数算百分比」两条路径在 v0.13 统一为百分比口径时就断了，配置键与 JSON Schema 保留只为兼容旧配置，**别当功能用、也别接线**。现行口径：状态一律按**已用%** 分档（<80 正常 / 80–99 临近 / ≥100 耗尽，Mac 侧常量 `USED_WARN_PCT` / `USED_OVER_PCT`，Android 侧同值硬编码）；余额单位来自接口 `fields.currency`（USD→`$`，其余 `¥`），用量行的 `%` 写死在渲染代码里 → **`display.unit` 同样不读取**（Android 侧已从 `DisplaySpec` 删掉该字段），`display.label` 只有 `status` parser 会用
- `display.nameColor` — 平台名颜色；支持深浅双套 `{"dark":"#xxx","light":"#xxx"}`，随系统外观切换（注意红绿色弱对比度）
- `refreshParam` — 鉴权错误时自动刷新 + 菜单「🔄 刷新 Cookie」点击项（如 MiMo 的 `refresh-mimo-cookie`）
- `refreshInterval` — 主动续期周期（秒，≥60）：即使 cookie 仍有效也定期从浏览器复制最新 cookie，保持 keychain 与浏览器会话同步、减少 401 触发面（仅对配置了 `refreshParam` 的 provider 生效）
- `enabled` — 设为 false 临时禁用

### Cookie 鉴权（MiMo 特例）

- MiMo platform API（`/api/v1/balance`）要求**完整 Cookie 组合**（ph + serviceToken + slh + userId），仅单个 Cookie 返回 401
- 完整 Cookie 串存 Keychain 单个条目 `MIMO_PLATFORM_TOKEN`，provider 配 `authHeader: "Cookie"` + `authPrefix: ""`
- Cookie 为会话级，过期后运行 `scripts/refresh-mimo-cookie.py` 一键刷新（macOS 版支持 Edge / Chrome / Brave / Arc；Linux 版 `linux/scripts/` 按 **Chromium → Edge → Chrome** 顺序，从任一已登录浏览器解密提取）
- **半自动刷新机制**：`refreshInterval` 按周期主动续 cookie（浏览器会话存活时 keychain 始终最新）；当服务端会话真正过期、浏览器同步失效导致刷新失败时，自动打开 `consoleUrl` 登录页并发系统通知（**Linux 版由 `linux/token-eye-tray.py` 的 `open_in_browser()` 优先调 Chromium，兜底 xdg-open；环境变量 `TOKEN_EYE_BROWSER` 可覆盖、`=default` 强制系统默认**；`token-eye-loginopened-*.flag` 30 分钟限频），登录后下个 1 分钟重试周期自动拾取新 cookie——**无需再手动跑刷新脚本**
- **点菜单底部「刷新」= 一次点击搞定**（`refresh-now` + `--force-refresh`）：忽略 10s 错误短缓存 + 跳过 1 分钟自愈冷却，在同一轮内完成「刷 Cookie → 重拉余额 → 直接显示新余额」，不必等冷却过完再点第二次。Cookie 本身已死（浏览器会话也过期）时会照常弹登录页 + 通知，你登录完再点一次「刷新」即刻出余额

详细配置示例见 `README.md`。

## 添加新平台

1. 编辑 `providers.json`，在 `providers` 数组中追加配置
2. 将对应 API Key 添加到 Keychain
3. SwiftBar 下次刷新时自动加载，无需修改脚本

## 开发注意事项

- 核心逻辑在 `swiftbar/token_eye.py`（可 import、可单测），`token-eye.sh` 只做环境检测与转发；两者都从项目目录读取，部署时**只需复制 token-eye.sh**
- 提交前跑 `make check`（语法 + 单元测试 + Schema + 跨端配置同步 + 配色）；CI（`.github/workflows/ci.yml`）会在 push/PR 时自动执行同样的检查
- **改配置必须同步 Android 副本**：Mac/Linux 读项目根目录的 `providers.json`，Android 读手工副本 `android/app/src/main/assets/providers.json`（`holidays/` 同理）。改完根配置**必须**把文件拷到 assets 同名路径并重装 APK；`scripts/check-config-sync.py`（已进 `make validate` 与 CI）会比对两份，唯一允许的差异是带 `refreshParam` 的平台在 Android 侧被剔除（Cookie 刷新无法移植）
- **~~Android 还有第三份配置 = 手机上的 `filesDir/providers.json`~~（该机制已于 2026-10-05 整层删除，勿再恢复）**：旧实现 `ConfigRepository.load` 优先读 `filesDir/providers.json`（用户点「剪贴板导入配置」写入），一旦存在就**永久遮蔽** assets 内置版且永不过期；更坑的是**启用/停用开关的 `toggleProvider` 也往 filesDir 写整份配置**，所以「点一次开关」就足以让手机端配置冻结在旧版本、重装 APK 也更新不了。实测症状：手机缺 `peakWindow.holidays` → 读到 `false` → 国庆当天被当成工作日空闲，倒计时指向一个并不存在的高峰（`空闲 距高峰 55m`）。**现状**：配置本体只有 `assets/providers.json` 一份（`ConfigRepository.load` 只读它），App 内不再有改配置入口；运行时可改的只有 API Key（`SecretStore`/Keystore）与启用状态（`EnabledStore`，只存 `{"id": false}` 极简映射、不存配置本体，覆盖在 `ConfigRepository.load` 统一叠加）。**加任何「手机端改配置」的功能前先想清楚**：它一旦能写配置本体，就会重新引入「升级 APK 但手机规则不变」这类静默不一致
- **峰谷/节假日类问题若「改了配置却不生效」，先查生效的是哪份配置**（排查命令：`adb shell run-as com.coffeelab.tokeneye cat files/enabled.json` 确认启用覆盖、`HolidayTable.load` 是否返回非空、`spec.holidays` 是否 true），再怀疑算法。Android 端链路是「assets 配置 → ConfigLoader → ResultParser → PeakWindow.classify」，每段都可插入 `Log.d("TokenEye", ...)` 打印关键入参，**一次日志同时打出多个环节的入参往往直接暴露矛盾点**（2026-10-05 就是靠 `spec.holidays=false incoming=72` 一击定位：表已加载成功，问题在开关没读进来）
- **不要给 Android 写"看起来一样但会静默丢参数"的重载**：`ResultParser.parse(p, data)` 曾与 `parse(p, data, alerts, holidays)` 并存，调用方误用前者时 holidays 静默变空表、节日判定整个失效且无任何报错。已删除该重载；新增带上下文参数（alerts/holidays/密钥等）的方法**不要给默认值**，让编译期强制调用方显式传入
- 改配置结构时：同步更新 `schema/providers.schema.json` 与 `token_eye.py` 里的 `schema_validate`（运行时轻量校验，与 JSON Schema 互补）
- **配置字段必须「代码真的读了」才算数**：新增字段要同时落在「代码读取处 + JSON Schema + 模板/文档」三处；只写文档/只配 Schema 不接线 = 死配置（`display.unit` / `parser.statusMap` / `parser.fields.intervalTotal` / `weeklyTotal` / `intervalStatus` / `weeklyStatus` 就是这么攒出来的，已在 provider 段标注废弃）。自检一句：`grep -c '<字段名>' swiftbar/token_eye.py` 为 0 → 代码不读，要么实现要么标注废弃。**Android 侧同样按此清理**（2026-10-06 已删 `ParserSpec.barLength` / `DisplaySpec.unit` / `nameColor*`与 `intervalStatus`/`weeklyStatus` 的读取路径；配置里的键保留给 Mac 侧读，Android 忽略不影响跨端同步校验）
- **「取最差状态」一律 `maxByOrNull { it.ordinal }`，永远别写 `minBy`**：`Status` 枚举序是 `OK(0) < WARN(1) < ERR(2) < NOKEY(3)`，ordinal 越大越差。Android `ResultParser` 曾误用 `minBy` —— 5h 正常 + 7d 无数据时整体判 OK、图标显示绿色（无报错、无日志）。三端任何聚合多个状态取最差的场景都适用（Mac 的 `render()`、Linux 的 `worst_status()`、Android 的 `worst`）
- **告警/恢复通知的阈值判断必须用「已 resolve 的阈值」，不能回头读原始配置**：`token_eye.py` 的恢复通知曾写死 `alert_cfg["minBalance"] is not None`，而告警本身可由 `parser.defaultMinBalance` 或 API 阈值字段触发 → 告警能发、恢复通知永远发不出（静默失联）。`min_balance` 已在 `parse_provider` 里走完「API 字段 > alert.minBalance > defaultMinBalance」整条链，判定一律用它
- **`schema_validate` 等入口层不许抛异常**：校验器的调用方（`run()` / `validate_mode()`）没有包 try，校验时一旦抛异常整轮渲染就崩 → SwiftBar 只拿到空 stdout、菜单全白且无任何提示。所有 `int()` / 下标 / 类型转换都要先判脏（见 `_as_int`）。新增校验项时用现有单测 `test_peak_window_garbage_does_not_raise` 的写法：脏值必须转成错误列表而非异常
- **「部分失败」必须能触发自愈动作，否则永不刷新**（2026-10-06 v0.23.2/0.23.3 连续两次真机实测踩坑）：
  1. `RefreshEngine.refresh` 对单平台失败是 `continue`（不抛异常，合理——一个平台挂不该带崩其他），所以调度层必须自己判断失败。返回值已带 `Outcome.anyFailed`
  2. **拿到 `anyFailed` 后不要直接 `Result.retry()`** —— WorkManager **周期任务不支持 retry**（会被忽略），只能按原周期排下一轮；而周期下限 15 分钟、MIUI 省电还会再往后压（实测周期任务根本没被调起）。正确做法是**主动排一个「失败接力」任务**（`RefreshWorker.enqueueRecovery()`，延时 1 分钟 + `ExistingWorkPolicy.REPLACE`；用 KEEP 会让接力任务自我阻塞、断网期间彻底停摆）
  3. **凡是绕过调度器直接调 `refresh()` 的入口（如 App 内「立即刷新」按钮）也要接上自愈**，否则该路径失败后永远不自愈
  4. 失败时 `successAt` 保持「上次成功」的真实时间戳（失败不是成功）—— 但这带来一个必须配套的规则：**缓存判定要额外要求 `!prevResult.stale`**（见 `canReuse()`），否则网络刚恢复时若距上次成功不足 TTL（balance 300s）就会复用旧结果、压根不发请求，永远停在陈旧态
- **拉取失败时优先「显示上次成功的数据」而非错误文案**：余额/百分比是有用信息，「网络错误」不是。做法是给结果加独立的 `stale` 标记（`ProviderResult.stale`）而不是改 `status` —— 混成 WARN 会与「余额真的低于阈值」的告警混淆，多轮失败还会叠加放大；details 里的陈旧提示要**按前缀去重、只保留最后一条**，否则断网一晚会堆出一长串。兜底逻辑抽成纯函数 `staleResult()` 才能单测（埋在 `refresh()` 里依赖 Context + 真实网络，没法验证）
- **版本号唯一真源 = `token_eye.py` 的 `VERSION`**：发版只改这一处 + `token-eye.sh` 头部 `bitbar.version`（CI 校验两者一致）。Android 的 `versionName` / `versionCode` 由 `app/build.gradle.kts` 构建时**自动读取** `VERSION` 派生（0.22.0 → 2200），**不要手工填**，也别再让 app 版本号单独漂移（曾长期停在 0.19.1）
- 脚本使用 `set -euo pipefail`，任何命令失败都会退出（注意：命令替换里放可能失败的脚本时需 `|| true` 兜底，见 refresh-mimo-cookie 分支）
- API 超时时间：curl 5s，subprocess 10s
- SwiftBar 刷新间隔：30 秒（脚本内 `# <bitbar.refreshTime>30</bitbar.refreshTime>` 声明）
- 缓存文件位于 `/tmp/token-eye-cache-{id}.json`，失败请求 10s 短缓存避免连续打 API
- 告警去重/自愈防抖标记位于 `~/Library/Caches/token-eye/token-eye-{alerted|recovered|autorefresh}-{id}.flag`（持久化，重启不丢）；余额/用量恢复时发「已恢复」通知（去重）
- 自愈冷却策略：`autorefresh` 标记内容为 `<ts> ok|fail`——**失败后 1 分钟可重试**（会话可能很快恢复），成功后 30 分钟防抖；自愈成功时同时写 `lastrefresh` 标记，避免同一轮渲染里主动续期再跑一遍脚本；自愈失败原因会显示在错误菜单（含「点菜单 🔄 刷新 Cookie 立即重试」引导）；`refresh-mimo-cookie.py` 刷新成功时会清掉错误短缓存，下次渲染立即重拉余额
- 半自动刷新额外标记（均在 `~/Library/Caches/token-eye/`）：`token-eye-loginopened-{id}.flag` 记录自动打开登录页的时间戳（30 分钟限频）；`token-eye-lastrefresh-{id}.flag` 记录主动续期成功的时间戳（用于 `refreshInterval` 节流）
- **点「刷新」= 主动重拉（`--force-refresh`）**：菜单底部「刷新」是 `bash=… param1=refresh-now terminal=false refresh=true` 动作，**不是裸 `refresh=true`**——裸写法 SwiftBar 以零参数重跑插件，`param1` 根本传不进来（见上文「SwiftBar 交互项铁律」）。启动器收到 `refresh-now` 后以 `--force-refresh` 跑一轮核心逻辑，stdout 丢弃、结果由随后的 `refresh=true` 重渲回显。`force=True` 只做两件事：① 忽略 10s 错误短缓存（否则刚失败就点会直接命中缓存、压根不打 API，看着像「点了没反应」）；② `auto_refresh_cookie(force=True)` 跳过 1 分钟冷却立即跑脚本。于是**一次点击**即可跑完「刷 Cookie → 重拉余额 → 直接显示新余额」，不必等冷却过完再点第二次。**成功缓存（默认 300s）照常复用**，force 不额外打 API；`_open_login_page` 的 30 分钟限频也不受 force 影响（防连点反复弹浏览器）
- 历史文件（history-*.jsonl）保留 30 天，每天自动清理一次（`cleanup_history` / `last-cleanup.ts` 标记），防无限增长
- 告警通知默认带提示音（`TOKEN_EYE_SOUND` 换声音名，`0` 静音）；`TOKEN_EYE_DEBUG=1` 时请求明细写入 `~/Library/Caches/token-eye/debug.log`
- 历史只服务 balance 类平台（消耗统计/预测/7 天柱状）：近 7 天每日消耗按天分桶后用 `sparkline` 渲染成 24 字符宽柱状（`▁▂▃▄▅▆▇█`）；plan_usage **不写历史**（趋势展示已下线，别再加回来）
- **点击动作必须写成 `bash=` + `param1=`**（SwiftBar 铁律，2026-09-11 踩坑）：SwiftBar 的 `param1=`/`param2=` **不会传给插件本身**，只作为 `bash=` 所指定脚本的入参（上游 `MenuLineParameters.bashParams` 仅在 `params.bash` 存在时被消费）；只写 `refresh=true` 时 SwiftBar 会用**零参数**重跑插件，点击等于没反应。正确格式 `bash=<插件绝对路径> param1=<动作> terminal=false refresh=true`：`terminal` 默认 **true**（不写会弹 Terminal.app），`refresh=true` 让脚本跑完自动重渲菜单。路径由 `action_script_path()` 解析（`SWIFTBAR_PLUGIN_PATH` → `SCRIPT_DIR` → 模块同级）
- 点击动作在后台执行（`terminal=false`），**stdout 会被丢弃**：结果反馈走 `notify()`（osascript 系统通知），自检详情另存 `~/Library/Caches/token-eye/self-check.log`
- 行级交互参数（`bash=`/`param1=copy-balance` / `href`）通过 render dict 的 `line_params` 列表与 `lines` 一一对应，新增行时必须同步 append（None 或参数 dict）
- 模板库 `scripts/provider-templates.json` 的每个模板必须通过 JSON Schema 与运行时校验（测试覆盖）
- 渲染层有 try-except 兜底，异常时输出空菜单占位，不会空白
- 环境变量 `TOKEN_EYE_NOTIFY=0` 可临时禁用告警通知
- **节假日/调休数据**：`parser.peakWindow.holidays=true` 时按 `holidays/<年>.json` 查表（法定节假日全天空闲、调休上班的周末算工作日）；该表由国务院逐年公告、无算法规律，公告后跑 `make holidays`（`scripts/update-holidays.py`，直连 GitHub + 国内镜像）更新，运行时不联网；新增年份后**同步拷到 `android/app/src/main/assets/holidays/`**（Android 端只读 assets，`HolidayTable.load()` 合并整个目录；漏拷会被 `check-config-sync.py` 拦下）；表缺失/损坏自动退化为纯 weekdays 判定