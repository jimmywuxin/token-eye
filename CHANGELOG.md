# Changelog

## [0.23.4] - 2026-10-06

### 修复
- **MiMo 主动续期成功后菜单仍显示旧错误**（用户实报）：`refreshInterval` 到点触发主动续期时，脚本自己已验过新 Cookie 有效（HTTP 200）、keychain 里已是新的，但代码**只写了条debug 日志、没重新拉取** —— 本轮 `fetch_result` 仍是「续期前」那次的结果（旧的 401），菜单要一直红到下个渲染周期。自愈路径（401 → 刷新 → 重拉）本来就有这个「刷新后重试」，主动续期这条漏了。现已补上：续期成功后立刻用新 Cookie 重拉一次
- **失败原因不留痕**（用户建议，排障效率）：Cookie 刷新失败时标记只写 `<时间戳> fail`，原因被丢掉，排障只能靠时间线反推。现在
  - 自愈失败：标记写 `<ts> fail <原因末行>`，冷却判定仍只看前两段（向后兼容）
  - 主动续期失败：原因写进**独立标记** `token-eye-proactive-fail-{id}.flag`（不写 `lastrefresh` —— 推进它会触发 interval 冷却、让失败后 6 小时内不再重试，与「失败不推进标记、下轮继续试」的原语义冲突）；续期成功时清掉该标记
  - 两者原因都会累积显示在错误菜单里（`↻ 自动刷新未生效: ...`），用户能直接看到「钥匙串未解锁」之类的话
- `self_heal_err` 初始化从 fetch 分支移到函数开头：命中缓存的早退分支不经过 fetch 段，原先读它会 `NameError`（既存隐患，本次一并修）

### 说明
- 测试：200 → 204（新增续期后重拉、续期失败原因入菜单、失败标记带原因、冷却解析兼容 4 例；已验证把「续期后重拉」代码删掉后测试会红）
- Mac/Linux 侧改动，Android 不受影响

## [0.23.3] - 2026-10-06

### 修复
- **网络恢复后小部件仍不自动刷新**（v0.23.2 的漏网之鱼，真机复测发现）：v0.23.2 只让 `RefreshWorker` 在失败时返 `Result.retry()`，但 **WorkManager 周期任务不支持 retry**（会被忽略），周期下限又是 15 分钟、MIUI 省电还会往后压。实测断网恢复后静置 3 分钟，周期任务根本没被调起。改为任何一轮失败都主动排一个「失败接力」任务（延时 1 分钟、`REPLACE` 避免自我阻塞），由它重试并在再失败时续排
- **在 App 内点「立即刷新」失败后不自愈**：该路径直调 `RefreshEngine`、不经过 Worker，因此没有接上自愈。现已与 Worker 共用同一套 `enqueueRecovery`
- **陈旧态卡住不重拉**：失败时 `successAt` 保持「上次成功」不变，而 balance 的 TTL 有 300 秒 —— 网络刚恢复的那一轮若距上次成功不足 TTL 就会复用旧结果、压根不发请求，`anyFailed=false` → 不重试 → 永远停在陈旧态。缓存判定新增条件：上次结果为陈旧时**必须重新拉取**（`RefreshEngine.canReuse()`，纯函数可单测）

### 验证
- 真机（小米 14 / Android 16）完整链路实测：飞行模式断网 → 点刷新 → 余额保留 + 标「数据陈旧」+ 黄点 → 关闭飞行模式后**完全不碰手机**，50 秒内自动回绿（`21:24:10` 断网 → `21:25:10` 接力成功）
- 测试：43 → 44（Kotlin，新增 `staleResult_mustNotBeCacheValid` 锁住陈旧项必须重拉）

## [0.23.2] - 2026-10-06

### 修复
- **桌面小部件断网后卡在「网络错误」不再自愈**（三处叠加）：
  1. 单平台拉取失败时 `RefreshEngine` 内是 `continue`（不抛异常），而 `RefreshWorker` 无条件 `Result.success()` → WorkManager 认为任务正常完成，**既不重试也不退避**，断网一次后就永久停在错误态
  2. 失败结果整条覆盖快照，把小部件本该显示余额的位置换成了错误文案
  3. 失败时 `successAt` 留空导致缓存判定恒过期，反复打 API

  现在：失败时保留上次成功的数据（余额照常显示，只标「数据陈旧」+ 黄点），并返回 `Result.retry()` 让 WorkManager 按退避策略尽快自愈。

### 变更
- 小部件/App 内新增「数据陈旧」状态：圆点变黄、状态标签显示「正常（数据陈旧）」，详情末尾追加失败原因。**余额/百分比照常显示**——旧数字比「网络错误」有用得多
- 陈旧数据用独立的 `ProviderResult.stale` 标记而非改 `status`：混成 WARN 会与「余额真的低于阈值」的告警混淆，连续多轮失败还会叠加放大
- 连续多轮失败时只保留最后一条失败说明，不堆成一长串

### 说明
- 测试：38 → 43（Kotlin，新增 `StaleResultTest` 覆盖兜底显示/首轮失败/上次也是错误/未配置密钥/连续失败不叠加）
- Android 侧改动，不影响 Mac/Linux 插件

## [0.23.1] - 2026-10-06

### 修复
- **配置写错时菜单不再全白**：`schema_validate` 校验 `peakWindow.hours` / `weekdays` 时直接 `int()` 转换，非数字值（如 `[["oops",12]]`）抛 ValueError 穿透整个渲染流程 → SwiftBar 只拿到空输出、菜单栏空白且没有任何提示。现在统一转为「配置错误」菜单逐条列出问题项。
- **Android 恢复通知永久失联**：余额告警阈值来自 `parser.defaultMinBalance`（provider 未配 `alert` 段）时，告警能正常发出，但余额回升后的「已恢复」通知条件写死了 `alert.minBalance`，永远发不出来。改用已解析的完整阈值链结果。
- **Android 用量状态取反了**：「取最差状态」误用 `minBy`，而 `Status` 枚举序是 OK<WARN<ERR，实际取到的是最好值 —— 5h 周窗正常、7d 周窗无数据时整体判为正常并显示绿色。改为 `maxBy`。
- **Android 小组件首装崩溃**：`rows` 为空（刚装 App、密钥未填）时排版计算访问空列表越界，小组件打不开、连「点按刷新（未配置密钥）」的提示都显示不出来。
- **Linux 托盘历史文件无限增长**：漏掉了 Mac 版每日一次的历史保留期清理。

### 变更
- **Android 用量分档与 Mac 侧对齐**：统一按「已用%」判定（<80 正常 / 80-99 临近 / ≥100 耗尽），耗尽（剩余 ≤0）判错误而非仅警告；`parser.pctDirection` 不再被忽略，`"used"` 口径的 provider 不会被算反。
- 清理死代码：Android 侧 `barLength` / `display.unit` / `nameColor` 三个零使用字段与已废弃的 `intervalStatus` / `weeklyStatus` 读取路径（配置里的键保留，不影响旧配置校验）；Linux 侧三个定义即废的函数与变量；插件启动器里一个永远走不到的模块探测分支。

## [0.23.0] - 2026-10-05

### Removed

- **删除 Android「剪贴板导入配置」入口与整个 `filesDir` 配置覆盖层**（`MainActivity.kt` 按钮 + `ConfigRepository` 的 userConfig 系列方法 + 仅服务该功能的 `validateConfigJson`，净 -85 行）：旧实现里 `filesDir/providers.json` 优先级高于 `assets/providers.json`，一旦存在就**永久遮蔽**内置版且永不过期 —— 也就是「重装 APK 但手机端配置不更新」。更隐蔽的是**启用/停用开关的 `toggleProvider` 同样往 filesDir 写整份配置**，所以「点一次开关」就足以触发冻结，v0.22.1 修的那个节假日倒计时 bug 正是这么来的。该功能对实际使用零价值（配置改动本来就走 git 改根目录 → 拷 assets → 重打 APK，另有 `check-config-sync.py` 在 CI 兜底），纯负债

### Added

- 新增 `EnabledStore` 承接启用/停用：只持久化 `{"providerId": false}` 这样的极简映射，**不存配置本体**，覆盖统一在 `ConfigRepository.load` 叠加（UI 与 `RefreshEngine` 自动一致，不给「显示是关的、实际还在刷」留机会）
- `ConfigRepositoryTest`（5 例）：钉住「覆盖只动 `enabled`、不丢平台、不改配置本体字段、空覆盖表原样返回」，覆盖逻辑抽成纯函数 `applyEnabledOverrides` 以便无 Android 环境单测

## [0.22.1] - 2026-10-05

### Fixed

- **Android 法定节假日期间峰谷倒计时误判为工作日**（手机显示「空闲 距高峰 1h15m」，Mac 端同期为「节假日 距高峰 2d20h」）：`ConfigRepository.load` 的优先级是 `filesDir/providers.json`（用户点「剪贴板导入配置」写入）> `assets/providers.json` 内置版，而本机那份导入配置是 9 月的旧版、缺 `parser.peakWindow.holidays` → 开关按默认值读到 `false` → `ResultParser` 里 `if (spec.holidays) holidays else emptyMap()` 把已加载的 72 条节假日表整个丢弃，退化为纯「周一至周五」判定，国庆/春节等长假期间倒计时会指向一个并不存在的高峰。**注意重装 APK 不会更新 `filesDir` 里的用户配置**，此类配置类问题第一步应查 `adb shell run-as com.coffeelab.tokeneye cat files/providers.json`
- **`HolidayTable.load` 增强健壮性**：`assets.list("holidays")` 返回空时，回退按年份硬探测 `holidays/<年>.json`（当前年 ±1），避免打包/压缩配置差异导致节假日表整份读空
- 删除 `ResultParser.parse(p, data)` 这个带默认值的旧重载：它与 `parse(p, data, alerts, holidays)` 并存，误用时 `holidays` 静默变空表、节日判定整个失效且无任何报错。带上下文参数（alerts / holidays / 密钥）的方法一律不给默认值，让编译期强制调用方显式传入

### Added

- **端到端回归测试**（`ParserTest`，2 例）：此前 `PeakWindowTest` 只覆盖纯函数，测不到「配置开关 → 传入节假日表 → 详情行文案」这条实际出错的链。新增用例钉住该链路，并反向守住「空表时退化为 weekdays 而非误判为节假日」；节假日表按当天动态构造（今天起连续放假、其中一个工作日置为调休上班），不受真实日历影响，任意日期运行结论都成立

### Changed

- **Android app 版本号改为跟随项目版本**（`app/build.gradle.kts`）：`versionName` / `versionCode` 在构建时从 `swiftbar/token_eye.py` 的 `VERSION` 自动读取派生（0.22.0 → versionCode 2200），不再手工维护第三处。app 版本号此前长期停在 `0.19.1`（项目已到 0.22.0），`adb shell dumpsys package` 看到的会是旧版本号；现在唯一真源就是 `VERSION`，发版时无需再动 Android 工程

## [0.22.0] - 2026-10-05

### Added

- **跨端配置同步校验**（`scripts/check-config-sync.py`，已进 `make validate` 与 CI）：比对项目根 `providers.json` / `holidays/` 与 Android 的手工副本 `android/app/src/main/assets/`，防止「改了根配置忘了拷 → 手机 App 一直跑旧规则」（峰谷时段、配色、告警阈值都靠它）。报错精确到字段路径（如 `provider「deepseek」的 parser.peakWindow.hours 与根目录不一致`）；**允许的唯一差异**是带 `refreshParam` 的平台在 Android 侧被剔除（Cookie 刷新无法移植）。新增 `tests/test_config_sync.py` 10 个用例（含「真实仓库必须同步」护栏）

### Removed

- **移除菜单「一键升级」**（`swiftbar/token-eye.sh` 的 `param1=upgrade` 分支，-118 行）：插件自己 `git fetch + merge --ff-only` 自己、串 3 个国内镜像兜底、非 git 仓库再下 tarball 解压替换。同一份镜像地址在仓库里抄了三遍，且无代理环境下 git fetch 常年失败，用户只看到「升级失败」。**版本自检保留**：有新版本时菜单顶部提示「⬆ 新版本 vX.Y.Z 可用」并给 release 链接，升级方式回到 `make install`
- 删除 `docs/providers-config.html`（353 行）：从未被 README / AGENTS.md / DESIGN.md 链接，内容与 README + schema 三方重复、各自过时。其中独有的「配置字段速查」「配置→界面位置映射」「配色说明」已并入 README，其余与 README 重复的内容直接丢弃
- 死代码：`start_of_week` / `start_of_month`（生产零调用，仅测试引用）、常量 `HISTORY_LEN`（趋势窗口下线后无生产引用）

### Fixed

- **倒计时整点不再显示多余的 `0m`**：MiniMax 重置剩整 2 小时时，Mac 显示 `2h0m`、Android 显示 `0m`——同一段逻辑在 Mac 写了 2 份、Android 写了 2 份，注释还都声称「与另一处同口径」。现在 4 份收敛为 2 份（各语言一份）：`token_eye.format_ms` 委托 `parsers.peak_window.format_countdown`，Android `ResultParser` 委托 `PeakWindow.formatCountdown`，两端一致显示 `2h`；`format_ms(0)` 由 `0m` 改为空串

### Changed

- plan_usage 不再写历史文件（`history-minimax.jsonl`）：菜单里的趋势展示早已下线，写入的数据无人读取
- 死配置字段在文档里标注废弃：`display.unit` / `parser.statusMap` / `parser.fields.intervalTotal` / `weeklyTotal` / `intervalStatus` / `weeklyStatus` 代码里零引用（v0.13 统一百分比口径后断掉的旧路径），配置键与 JSON Schema 保留仅为兼容旧配置；AGENTS.md 补「配置字段必须代码真的读了才算数」铁律
- 文档同步：README 去掉已不存在的「用量趋势线」与「一键升级」描述、新增「配置字段速查」；DESIGN.md 重写历史/趋势章节与升级路径说明；AGENTS.md 明确「历史只服务 balance 类平台」
- 测试 197 例（-2 死函数用例，+1 防漂移用例，+10 跨端同步用例）

## [0.21.1] - 2026-10-05

### 修复

- **点「刷新」不再需要等一分钟**：菜单底部「刷新」原先是裸 `refresh=true`，SwiftBar 以**零参数**重跑插件（`param1` 根本传不进来），于是 MiMo Cookie 过期时这轮自愈会撞上 1 分钟失败冷却直接跳过——**点击看着毫无反应，必须等冷却过完再点一次才出余额**。现改为显式动作 `param1=refresh-now` → 以 `--force-refresh` 跑一轮核心逻辑：忽略 10s 错误短缓存 + 跳过自愈冷却，在同一轮内完成「刷 Cookie → 重拉余额 → 直接显示新余额」。成功缓存（300s）照常复用不额外打 API，登录页弹窗的 30 分钟限频也不受影响

## [0.21.0] - 2026-10-01

### Added
- **峰谷判定支持中国法定节假日与调休**（`parser.peakWindow.holidays: true`）：原先只按「周一至周五 + 09:00-12:00 / 14:00-18:00」判定，国庆当天照旧显示 `⚡高峰`。现叠加 `holidays/<年>.json` 查表：**法定节假日（含调休放假）全天空闲**，详情行显示「节假日 距高峰 X」；**调休上班的周末按工作日算**（时段内 → 高峰，非时段 → 空闲而非「周末」）。DeepSeek 已默认开启
- 内置节假日数据 `holidays/2025.json`、`holidays/2026.json`（源自 [NateScarlet/holiday-cn](https://github.com/NateScarlet/holiday-cn)，逐条对照 gov.cn 公告，含调休上班日），零网络开销、纯本地查表；缺表/表损坏自动退化为原「周一至周五」规则，不影响余额显示
- `scripts/update-holidays.py`（`make holidays`）：每年国务院公告后一键更新下一年数据（直连 GitHub + 3 个国内镜像兜底；本地已有数据时断网只提示不改动、不误报失败）
- 测试新增 16 例（46 例全过）：国庆全天空闲、调休周六/周日算高峰、跨整段假期的倒计时（10-01 10:30 → 10-08 09:00 = 6d22h）、春节 9 连休的 9d13h 长空窗（超出旧版 7 天搜索窗口）、数据文件缺失/损坏降级等

### Changed
- **倒计时 ≥ 1 天改用 `d+h` 两级**：跨整段假期时 `距高峰 153h18m` 这种读不出来，现显示 `6d9h`（整点省略小时 → `6d`）；< 1 天口径不变（`1h30m` / `2h` / `45m`）。峰谷倒计时与 MiniMax 重置倒计时（`format_ms`，周窗最长 7 天）统一为同一口径
- `parsers/peak_window.py`：`classify()` / `next_switch()` 新增可选 `holidays` 参数（`{ISO 日期: 是否放假}`），新增 `load_holidays()` / `holiday_path()` / `load_holiday_file()` / `is_workday()` / `is_holiday()`；`classify()` 返回值新增 `is_holiday` 字段。倒计时搜索窗口由 7 天放宽到 21 天（覆盖春节 9 连休 + 前后周末）
- `schema/providers.schema.json` 与运行时 `schema_validate` 补 `peakWindow.holidays`（布尔）校验

> 说明：法定节假日的放假/调休安排由国务院逐年公告，**没有算法规律**，只能查表——这也是必须内置数据文件、并每年跑一次 `make holidays` 的原因。

## [0.20.2] - 2026-09-20

### Changed
- **Linux 版 MiMo Cookie 采集浏览器由 Edge 改为 Chromium**：`linux/token-eye-tray.py` 的浏览器偏好由 `microsoft-edge-*` 换成 `chromium-browser` / `chromium` / `chromium-browser-stable`，托盘打开的登录页与菜单控制台跳转统一走 Chromium（无 Chromium 才回退 `xdg-open`），通知文案同步改为「Chromium（…）」。避免本机系统默认的 360 安全浏览器抢走登录页；`TOKEN_EYE_BROWSER` 覆盖机制不变
- `linux/scripts/refresh-mimo-cookie.py` 浏览器扫描顺序改为 **Chromium → Edge → Chrome**（后两者保留作兜底）；`try_extract()` 新增诊断输出——Cookie 库缺失或 gnome-keyring 中无安全存储密码时打印「跳过 [X]: …」说明原因，不再静默跳过；报错文案改为引导在 Chromium 登录
- 文档同步：`README.md`、`linux/README.md`、`AGENTS.md` 的浏览器说明改为 Chromium（macOS 版仍支持 Edge / Chrome / Brave / Arc）

## [0.20.1] - 2026-09-18

### Fixed
- **Linux 版打开链接改用 Edge（不再走系统默认浏览器）**：本机系统默认是 360 安全浏览器，而 MiMo 的 Cookie 只能从 Chromium 系（Edge）解密提取——原先用 `xdg-open` 打开登录页会让用户在 360 里登录，刷新脚本读不到新 Cookie，陷入「登录了却一直 401」。新增 `linux/token-eye-tray.py` 的 `open_in_browser()`：探测 `microsoft-edge-stable` / `microsoft-edge`（等候选）优先调用（`--new-window`），无 Edge 才回退 `xdg-open`；`_open_login_page` 与菜单控制台跳转（`open_url`）统一走该函数，通知文案会说明实际所用浏览器。可用环境变量 `TOKEN_EYE_BROWSER=<可执行名|绝对路径>` 覆盖，`=default` 强制系统默认浏览器

## [0.20.0] - 2026-09-11

### Fixed
- **菜单里所有可点击项点了都没反应**（自 v0.15 系列起一直存在）：SwiftBar 的 `param1=`/`param2=` **不会传给插件本身**，只作为 `bash=` 所指定脚本的入参（上游 `MenuLineParameters.bashParams` 仅在 `params.bash` 存在时被消费）；本项目全部交互项只写了 `param1=… refresh=true`，SwiftBar 会用**零参数**重跑插件（`plugin.refresh(reason: .MenuAction)`），于是「刷新 Cookie」「一键升级」「自检」「点余额行复制」四个动作全部静默失效，观感就是点击无反应。现统一改为 `bash=<插件脚本> param1=… terminal=false refresh=true`：`terminal` 默认为 true（不写会弹出 Terminal.app），必须显式关闭；带 `refresh=true` 时 SwiftBar 会在脚本跑完自动重渲主菜单，刷新成功后余额立即恢复；路径由新增的 `action_script_path()` 解析（`SWIFTBAR_PLUGIN_PATH` → `SCRIPT_DIR` → 模块同级，取不到时退回旧写法保证菜单不空）
- **点击动作在后台执行看不到反馈**（`terminal=false` 会丢弃 stdout）：刷新 Cookie / 升级 / 复制余额 改用 `osascript` 系统通知回显结果（刷新失败附脚本关键错误行，成功不打扰）；新增 `param1=self-check` 分支，自检结果发通知摘要并把完整输出落到 `~/Library/Caches/token-eye/self-check.log`
- **同一次渲染里刷新脚本被跑两遍**：自愈成功只写 `autorefresh` 标记，紧接着的主动续期（`refreshInterval`）又跑一遍脚本；现自愈成功同时写 `lastrefresh` 标记

### Added
- 菜单项参数单测：`action_script_path()` 三级回退、`bash_action()` 格式与 `terminal=false` 强制、含空格值加引号、报错态刷新项携带 `bash=`、自愈成功写 `lastrefresh`（测试数 158 → 166）

## [0.19.3] - 2026-09-09

### Fixed
- **macOS 一键升级在无代理环境不可用**：SwiftBar 点击菜单项时是干净环境（无 `HTTP(S)_PROXY`），GitHub 直连国内常不通 → `git fetch` 挂死/失败，升级从未成功。改为：① 直连 fetch 加低速超时（约 8s 快速失败，不再无限挂起）；② 直连失败后依次尝试国内镜像 fetch（gh-proxy.com / ghfast.top / ghproxy.net，main + tags）；③ 非 git 仓库的 tarball 下载同样加镜像兜底；④ 版本自检 `check_latest_version` 在 API 直连失败时经镜像读 main 分支插件头部版本号兜底（此前无代理时连升级提示都不会出现）；⑤ 修复从项目目录直接运行时 cp 自拷贝报错退出的边界
## [0.19.2] - 2026-09-09

### Fixed
- **麒麟 Linux（Py3.8）峰谷时段不显示**：`parsers/peak_window.py` 顶层 `from zoneinfo import ZoneInfo` 在 Python 3.8（麒麟 `/usr/bin/python3`）抛 ImportError，导致 `_HAS_PEAK_WINDOW=False` 静默禁用峰谷渲染；`token_eye.py` 的 `parse_provider` 内另有一处局部 zoneinfo 硬依赖同样在 Py3.8 被吞。改为：`peak_window.py` 用 `try/except ImportError` 兜底，Py3.8 下以 `datetime.timezone(timedelta(hours=8))` 固定 +8 等价（中国无 DST）；`parse_provider` 不再直接依赖 zoneinfo，改传 naive 时间交给 `classify` 统一处理时区（含 tz 名非法回退）。测试 `tests/test_peak_window.py` 同步做 Py3.8 固定偏移兼容
- **Linux 托盘重启后误报「未配置 API key」**：默认钥匙环重启后常处于锁定态，`linux_get_key` 见锁即返回空导致全显未配置。改为先尝试 `coll.unlock()` 再读（自动解锁则无感成功，需密码则弹桌面密钥框，失败如实返回空）
- 新增 `linux/diag-keyring.py` 桌面诊断脚本：解锁 + 列出 3 个 key 是否就位 + 修复指引

## [0.19.1] - 2026-09-09

### Fixed
- **峰谷倒计时感知星期**：`next_switch` / `secondsToNextSwitch` 原先只看小时边界不看 weekdays，周五 20:00 误显示「距高峰 13h」（指向周六 09:00，实际应 ~61h 到下周一）、周六 09:30 误显示 2h30m；且 Mac 与 Android 口径不一致（Python 取下一边界、Kotlin 取下一区间起点）。统一为：高峰中（当天是高峰日）→ 当前区间结束（end=24 视为次日 00:00）；空闲/周末 → 下一个高峰日的第一个区间起点（最多向后找 7 天）
- **配置校验补齐**：`schema/providers.schema.json` 与运行时 `schema_validate` 补上 `parser.peakWindow` 定义与轻量校验（补齐项目约定）
- 清理未实现的 `unknownLabel` / `warnWithinMinutes` 死配置与文档承诺
- 测试补强：新增周末/跨零点倒计时用例（Python +5 / Kotlin +4）

## [0.19.0] - 2026-09-08

### Added
- **峰/谷时段标记（`parser.peakWindow`）**：DeepSeek 等采用峰谷定价的平台，API 不返回当前时段字段，由 `parsers/peak_window.py` 客户端按公示的本地时区规则自行判定。菜单栏余额后追加 `⚡高峰`/`🌙空闲`，详情菜单追加一行「状态 + 距下次切换」（如「高峰 距空闲 1h30m」「空闲 距高峰 10h30m」「周末 距高峰 10h30m」）。默认配置（DeepSeek）：北京时间 周一至周五 09:00-12:00、14:00-18:00 高峰，其余空闲；支持任意 IANA 时区 / 自定义工作日 / 多区间，零网络开销，parsers 模块不可用时静默降级

## [0.18.1] - 2026-09-03

### Changed
- **README 重构为分平台结构**：新增 `## 🐧 Linux 版` 使用章节（安装/管理命令/平台差异）、`## 🍎 macOS 版` 合并功能+使用方法为清晰章节、三平台（🍎/🐧/🤖）统一速览，消除「Linux 无说明、macOS 只提 SwiftBar」的割裂

## [0.18.0] - 2026-09-03

### Added
- **🤖 Android 版**（`android/` 目录，详见 [android/README.md](android/README.md)）：
  - Kotlin + Jetpack Compose + Glance 桌面小部件，Gradle 工程（AGP 8.10 / Kotlin 2.1.20），核心逻辑从 `token_eye.py` 移植（配置解析 / balance·plan_usage 解析 / 阈值链 / 刷新引擎 / 告警去重）
  - Glance 小部件：尺寸自适应（默认 3×1、最小只占 1 格高）、固定 13sp 单行自上而下排列、宽度不足时摘要降级（不换行/不放大字号）、点按立即刷新；仅显示已配置密钥的平台，错误行压缩为关键词
  - WorkManager 15 分钟周期刷新（系统下限）+ 打开 App 即时刷新
  - 密钥存 Android Keystore（EncryptedSharedPreferences），支持剪贴板导入 `providers.json`
  - 告警：NotificationChannel + 去重/恢复通知，逻辑照搬 Mac 版
  - 单元测试（ParserTest）覆盖点路径 / 余额 / 阈值 / 用量状态
  - **刻意不做**：MiMo Cookie 自动刷新（依赖本机浏览器解密，Android 无法移植），加载时剔除所有带 `refreshParam` 的平台
- **🐧 Linux (UKUI/银河麒麟) 系统托盘版**（`linux/` 目录，详见 [linux/README.md](linux/README.md)）：
  - `token-eye-tray.py`：AppIndicator3 常驻进程，复用上游核心（fetch/缓存/解析/告警/历史全部 import，零改动），GLib 定时器 30s 刷新，状态三图标（ok/warn/err），菜单行点击复制余额/打开控制台
  - `setup-keys.py`：gnome-keyring (secretstorage) 密钥管理，替代 macOS Keychain
  - `scripts/refresh-mimo-cookie.py`：MiMo Cookie 自动提取的 Linux 版（Edge/Chrome/Chromium v10/v11 AES-CBC 解密，密钥读 gnome-keyring）
  - `install.sh` + `token-eye.service`：systemd user service 一键安装（崩溃自动重启）
  - 平台适配细节：`send_notify`→notify-send、`open`→xdg-open、无 emoji 字体时菜单图标自动降级为纯文本（`fix_glyphs`）

## [0.17.1] - 2026-08-27

### Fixed
- **Cookie 刷新失败后的「锁死感」**：自愈失败冷却从 5 分钟缩短到 **1 分钟**（重新登录浏览器后最多等 1 分钟即自动拾取新 cookie）；冷却提示现在会引导「点菜单 🔄 刷新 Cookie 立即重试」（该菜单项本就不受冷却限制）；刷新脚本成功时清掉错误短缓存（`/tmp/token-eye-cache-mimo.json`），菜单点击恢复后立即重拉余额，不再闪 10 秒旧错误

## [0.17.0] - 2026-08-26

### Changed
- **详情菜单简约化（统一跨 provider 视觉）**：
  - **MiniMax（plan_usage）**：详情从 4 行收敛为 2 行（5h / 7d 各一行 label + 进度条 + %），重置时间融入 5h 行末；移除括号内「可用/耗尽临近」文字（由图标 + 颜色传达）；窗口名默认 `5h / 7d`（可由 `parser.windowLabels` 覆盖）；移除 trend 趋势行（历史继续写入以便恢复）
  - **DeepSeek / MiMo（balance）**：详情从 5–6 行收敛到 1–2 行（余额 + 今日消耗/预计可用合并行 + 近 7 天柱状）；移除 2.4h 趋势、本周/本月、「可用/不可用」副行；无消耗数据时详情退化到 1 行
  - **菜单栏图标统一**：所有 provider menu_bar 前缀加 `✅ / ⚠️ / 🔴`（余额阈值 / 用量阈值 / 不可用），跨 provider 健康度一眼可见
- **进度条口径切到「已用%」**（与 dsh-cost-meter coding plan 卡片一致）：阈值翻向 `>=80 warn / >=100 over`；源字段为剩余%的 provider（如 MiniMax）由 `parser.pctDirection: "remaining"`（默认）自动翻转；`alert.minPct` 阈值语义同步翻向（MiniMax 20 → 80）

### Added
- **告警阈值优先级链**（余额型）：API 字段（`parser.fields.alertThreshold`，预留接口）> `provider.alert.minBalance` > `parser.defaultMinBalance` > 不告警；优先级链解析集中在 `resolve_alert_threshold()`，menu_bar 图标与 `alert_check` 共用同一阈值（避免两处各算各的不一致）
- **`parser.windowLabels`**（plan_usage）：自定义窗口显示名，默认 `{"interval":"5h","weekly":"7d"}`
- **`parser.pctDirection`**（plan_usage）：`remaining | used`，默认 `remaining`（兼容 MiniMax 等历史 provider）；未来直接返回已用%的 provider 配 `"used"` 跳过翻转
- **`parser.defaultMinBalance`**（balance）：按 parser 类型兜底的余额告警阈值
- **`parser.fields.alertThreshold`**（balance）：指向 API 返回的告警阈值字段路径，平台有则自动读

## [0.16.0] - 2026-08-24

### Added
- **MiMo Cookie 半自动刷新**：新增 provider 配置 `refreshInterval`（秒），即使 cookie 仍有效也会按周期从浏览器复制最新 cookie（主动续期），保持 keychain 与浏览器会话同步、显著减少 401 触发面；当会话真正过期导致刷新失败时，自动在默认浏览器打开控制台登录页并发送系统通知（30 分钟限频防弹窗），登录后下个重试周期自动拾取新 cookie，无需再手动跑刷新脚本

### Fixed
- **401 自愈失败后冷却过久**：失败的自愈尝试原来也冷却 30 分钟，导致会话恢复（如 Edge 重新打开）后仍需手动刷新；现改为**失败后 5 分钟即可重试**，成功后才 30 分钟防抖；自愈失败原因（如「冷却中」）现在会显示在错误菜单里

## [0.15.0] - 2026-08-14

### Added
- **自检菜单项**：菜单底部「🔧 自检」一键检查 Keychain Key / 网络连通 / 插件版本一致性（`--self-check`）
- **菜单交互**：点余额行复制到剪贴板（`param1=copy-balance`）、点「今日消耗」行打开控制台（充值/账单）

### Changed
- **趋势窗口加长**：24 → 288 条快照（30s 采样 ≈ 2.4 小时），sparkline 均匀降采样保持 24 字符宽

## [0.14.0] - 2026-08-14

### Added
- **平台模板库**：`scripts/provider-templates.json` 内置 8 个平台模板（OpenAI / DeepSeek / Anthropic / Kimi / 智谱 GLM / 阿里云百炼 / 硅基流动 / MiniMax），添加向导可选模板一键生成配置
- **历史自动清理**：`history-*.jsonl` 保留 30 天，每天自动清理一次（`cleanup_history` / `last-cleanup.ts` 标记），防无限增长
- **通知提示音**：告警通知默认带系统声音（Glass），`TOKEN_EYE_SOUND` 可换声音名或设 `0` 静音

## [0.13.0] - 2026-08-14

### Fixed
- **MiniMax 状态误报「无套餐」**：新接口中 `total_count` 字段已废弃、对真实套餐也恒为 0，旧逻辑据此误判；现改为 **percent 字段优先**推导状态（≥20% 可用 / 10–20% 耗尽临近 / <10% 耗尽，与图标阈值一致），`statusMap` 仅在无百分比字段的旧接口兜底（`total=0` 才显示「无套餐」）。Starter 套餐的「5小时窗口 90%（可用）/ 周窗口 100%（可用）」恢复正确显示

## [0.12.0] - 2026-08-14

### Added
- **余额耗尽预测**：按最近 24h 消耗速率外推「预计可用 ~N 天」（`days_left`，余额类平台）
- **新告警维度**：`alert.dailySpendMax`（当日消耗上限告警）、`alert.daysLeft`（预计可用天数低于阈值预警）
- **周/月消耗统计**：详情菜单显示「本周 ¥x · 本月 ¥y」（`consumption_since` 任意窗口复用）
- **近 7 天消耗柱状图**：详情菜单显示每日消耗迷你柱状（右 = 今天）

### Changed
- **趋势行可读性优化**：括号差值改为窗口首尾差值，并显示绝对值范围（如 `¥8.17→7.39 (-0.78)`），与走势图形状一致；不再显示几乎恒为 0.00 的相邻快照差值
- 消耗统计重构为通用窗口函数 `consumption_since`（今日/本周/本月/滚动 24h 共用同一套下降量算法）

## [0.11.0] - 2026-08-14

### Added
- **当日消耗估算**：余额类平台（DeepSeek / MiMo）基于当天余额快照差值统计「今日消耗 ¥x.xx」，充值不会干扰统计（`daily_spend`，仅消耗 > 0 时显示在详情菜单）
- **plan_usage 趋势线**：MiniMax 等用量类平台记录剩余百分比历史，详情菜单显示趋势线（与余额趋势同款 sparkline）
- **告警恢复通知**：余额/用量回升到阈值以上时推送「已恢复」通知（去重，不刷屏）
- **菜单栏状态着色**：👁 标题按所有平台最差状态整体变色（任一错误→红，任一告警/缺 Key→橙）
- **一键升级**：版本自检发现新版本时，菜单出现「一键升级」（git 仓库自动 fetch+ff 合并并同步插件；非 git 仓库下载 release 包替换）
- **调试日志**：`TOKEN_EYE_DEBUG=1` 时请求的缓存命中/状态码/耗时/自愈结果写入 `~/Library/Caches/token-eye/debug.log`
- **货币符号可配置**：`display.currencySymbols` 自定义映射（如 `{"USD":"$","EUR":"€"}`），默认 USD→$ 其余→¥
- **多浏览器 Cookie 支持**：`refresh-mimo-cookie.py` 支持 Edge / Chrome / Brave / Arc 任一已登录浏览器（多配置档探测）
- **新平台添加向导**：`scripts/add-provider.py` 交互式生成配置，自动 schema 校验并提示 Keychain 命令

### Changed
- 历史记录（`~/Library/Caches/token-eye/history-{id}.jsonl`）现在同时服务于余额趋势、今日消耗估算与用量趋势三处
- **告警/自愈标记持久化**：从 `/tmp` 移至 `~/Library/Caches/token-eye/`，重启后不再重复告警
- **DESIGN.md 重写**：移除早期 Tauri 方案残留，改为描述当前 SwiftBar 架构（设计决策、模块设计、权衡与演进史）
- HTTP 状态码解析加固：curl 输出改用唯一分隔符 `__TE_HTTP__`，正文以数字结尾不再误判

## [0.10.0] - 2026-08-14

### Added
- **单元测试**：`swiftbar/token_eye.py` 核心逻辑（字段解析 / parser 渲染 / 告警去重 / HTTP 错误分类 / 缓存 / Schema 校验 / 401 自愈）拆为可测试的纯函数，`tests/test_token_eye.py` 覆盖 70 个用例（`make test`）
- **JSON Schema**：新增 `schema/providers.schema.json` + 零依赖校验器 `scripts/validate-schema.py`；编辑器打开 `providers.json` 自动补全，`make validate` / `--validate` 模式可离线校验
- **CI**：新增 GitHub Actions（`.github/workflows/ci.yml`），push/PR 自动检查 bash 语法 + ShellCheck、Python 编译、单元测试、Schema 校验、配色对比度、版本一致性
- **Makefile**：`make install / test / lint / validate / check` 收拢常用命令

### Changed
- **架构拆分**：Python 核心逻辑从 bash heredoc（约 650 行）拆出为 `swiftbar/token_eye.py`，`token-eye.sh` 变为薄启动器（环境检测 + 参数动作转发）。部署模型不变——仍只需复制 `token-eye.sh`，核心逻辑与 `providers.json` 一样从项目目录自动读取
- 版本号双处维护由 CI 校验一致性（`bitbar.version` vs `VERSION`）

### Fixed
- **一键刷新 Cookie 失败时菜单空白**：刷新脚本失败退出码非零时，`set -euo pipefail` 会中断 bash，导致「❌ 刷新失败」菜单永远不显示；现以 `|| true` 捕获退出码，由分支正常展示成功/失败
- **MiMo Cookie 刷新误报「缺少 Cookie」**：Edge 运行中时最新 Cookie 写入在 `Cookies-wal/-shm/-journal` 里，旧脚本只拷贝主库拿到过期快照而误报缺失；现一并拷贝伴生文件，关键 Cookie 缺失时自动重试一次（`scripts/refresh-mimo-cookie.py`），失败菜单显示更多诊断输出（`tail -4`）

## [0.9.0] - 2026-08-10

### Added
- **MiMo 401 自动自愈**：鉴权错误时自动刷新 Cookie 并重试一次，无感恢复（30 分钟防抖，失败才显示手动刷新入口）
- **MiniMax 用量阈值告警**：plan_usage 支持 `alert.minPct`，剩余低于阈值推送系统通知（默认 20）
- **余额历史趋势**：记录余额快照（`~/Library/Caches/token-eye/`），详情菜单显示迷你趋势线（▁▂▃▄▅▆▇█）+ 变化量
- **菜单栏汇总可定制**：`menuBar.showSummary` 支持平台 id 数组（如 `["deepseek","mimo"]` 只显示指定平台）
- **配置 schema 校验**：providers 必填字段检查，配置错误给出明确中文提示
- **配色对比度回归检查**：`scripts/check-colors.py`（WCAG AA ≥4.5:1，当前 20 处全达标）
- **版本自检**：菜单底部显示版本号，GitHub 有新 release 时提示跳转（24h 缓存）

### Changed
- **MiniMax 状态语义修正**：total_count=0（无套餐配额）时显示「无套餐」而非「耗尽」（原「周窗口 100%（耗尽）」误导）
- 版本升至 v0.9.0

## [0.8.3] - 2026-08-10

### Added
- 菜单栏「一键刷新 Cookie」：provider 配置 `refreshParam` 后，鉴权错误时详情菜单出现「🔄 刷新 X Cookie」可点击项，点击自动执行刷新脚本并显示成功/失败反馈，无需打开终端（MiMo 401 时一键恢复）
- token-eye.sh 支持 SwiftBar 点击动作（`param1` 触发）

### Changed
- MiMo 配置新增 `refreshParam: "refresh-mimo-cookie"`

## [0.8.2] - 2026-08-10

### Added
- `display.nameColor` 支持深浅双套：字符串（旧版兼容）或 `{"dark":..., "light":...}` 对象，随系统外观自动切换

### Changed（配色审计，红绿色弱友好）
- 全配色按 WCAG AA（≥4.5:1）审计，修正浅色模式 3 处不达标：
  - warn `#B86E00`（3.99:1）→ `#8A5A00`（5.93:1）
  - DeepSeek `#FF375F`（3.52:1）→ 浅色 `#B3154A`（6.72:1），深色保持 `#FF375F`
  - MiniMax `#AC8E68`（3.08:1）→ 青绿 `#1D9E75`（深）/ `#0F6E56`（浅）
- 三平台名色相角拉开：DeepSeek 粉红 348° / MiniMax 青绿 165° / MiMo 橙 35°，红绿色弱可清晰区分
- 状态色沿用 Wong 色盲安全色板（ok 蓝 / warn 橙 / err 紫红），深浅两套全部 ≥4.5:1

### Fixed
- `scripts/refresh-mimo-cookie.py` 防御 PYTHONPATH 污染（WorkBuddy/Hermes 注入路径导致 cryptography ImportError）；shebang 改 `/usr/bin/python3`

## [0.8.1] - 2026-08-04

### Added
- MiMo 余额监控：从「验证 Key 有效性」升级为真实余额查询（`/api/v1/balance`），显示 ¥ 余额
- MiMo 余额阈值告警：`alert.minBalance` 默认 5.0
- 新增 `scripts/refresh-mimo-cookie.py`：一键刷新 MiMo Cookie（从 Edge Cookie 数据库提取解密 → 更新 Keychain → 验证）

### Changed
- MiMo 鉴权方式：从 Bearer Token（API Key）改为完整 Cookie 组合（`authHeader: "Cookie"` + `authPrefix: ""`，Keychain 存 `MIMO_PLATFORM_TOKEN`）
- 新增「Cookie 鉴权（多 Cookie 组合）」配置模式说明（README 高级配置段）

### Notes
- MiMo platform API 要求**完整 4 Cookie 组合**（api-platform_ph + serviceToken + slh + userId），仅 serviceToken 会返回 401
- Cookie 为会话级，Edge 关闭/过期后需运行刷新脚本；tokenPlan/usage 接口当前返回空数据，待账户有套餐后接入

## [0.8.0] - 2026-07-28

### Added
- 缓存机制：按 parser 类型设置默认 TTL（balance 300s / plan_usage 30s / status 60s），`providers.json` 的 `cache` 段可全局覆盖，单个 provider 可用 `cacheTtl` 字段覆盖；失败请求 10s 内不重试，避免连续打 API
- 余额阈值告警：balance parser 支持 `alert.minBalance` 配置，余额低于阈值时用 `osascript` 推送 macOS 系统通知；告警去重（余额恢复前不重复）
- 菜单栏汇总显示：`menuBar.showSummary` 开启后菜单栏显示关键数字（余额/百分比/状态），不再只显示 👁
- 各平台控制台跳转：provider 配置 `consoleUrl`，详情菜单末尾出现「→ 打开 X 控制台」可点击跳转
- HTTP 错误分类：5xx 服务端异常 / 4xx 配置鉴权错误 / 网络失败 / 超时 各自独立文案与颜色；临时故障用 warn 色（橙），配置错误用 err 色（红紫），不再一律显示「API 错误」
- 自定义请求头：`api.headers` 支持额外 header（如 OpenAI Organization）
- `plan_usage` 状态映射可配置：`parser.statusMap` 自定义状态码到文案的映射，默认 `{1: 可用, 2: 耗尽临近, 3: 耗尽}`
- 进度条长度可配置：`parser.barLength`，默认 20

### Changed
- 合并两段 Python 为一段：渲染逻辑内联，减少一次进程启动和 JSON 序列化，冷启动开销下降约 50%
- 颜色变量统一由 Python 输出，bash 不再二次解析
- 未配置 Key 时提示命令直接使用配置里的 `keychainService`，不再推测

### Fixed
- `color=$C_MUTED` 在 Python heredoc 内未展开的 bug：未配置 Key 时提示命令的颜色显示为字面量 `$C_MUTED`，SwiftBar 解析失败回退默认色，现改为 `color={C_MUTED}` 由 Python 填值
- 渲染失败时菜单整体空白：原第二段 Python 异常被 `|| true` 吞掉无 fallback，现加 try-except 兜底输出占位菜单

## [0.7.6] - 2026-06-07

### Fixed
- providers.json 里的 `colors.light.header` / `colors.dark.header` 实际从未被读取，现已修复
- 状态色 C_OK/C_WARN/C_ERR 此前硬编码在脚本中，无法通过 providers.json 自定义

### Changed
- providers.json colors 段新增 `ok` / `warn` / `err` 三个字段，支持自定义状态色
- 脚本 fallback 颜色（C_OK/C_WARN/C_ERR）也按浅色/深色分别导出，env 链路打通
- "Token Eye" 标题改由 Python 输出，colors.header 现在真正生效
- 第一个 Python 脚本输出结构化 JSON `{colors, providers}`，第二个脚本从 JSON 读色
- 任意颜色字段缺失时自动 fallback 到 env 值，向后兼容旧 providers.json

## [0.7.5] - 2026-06-07

### Changed
- 浅色模式配色优化（红绿色弱友好）：
  - `colors.light.header`: `#DAA520` → `#0066CC`（深蓝替代金色，浅色菜单栏上更醒目）
  - `colors.light.secondary`: `#3a3a3c` → `#2c2c2e`（更深，次要文字更清晰）
  - 脚本浅色 fallback 同步更新（C_HEADER / C_SECONDARY / C_MUTED / C_DEFAULT）
- 状态色改为色弱安全调色板（蓝/橙/紫，Wong 2011）：
  - `C_OK`: `#2ecc71`（绿）→ `#0072B2`（蓝）
  - `C_WARN`: `#f39c12`（亮橙）→ `#B86E00`（深橙）
  - `C_ERR`: `#e74c3c`（红）→ `#8E1A4A`（深紫红）
  - 红绿色弱用户可清晰区分三种状态，不再混淆红/绿

## [0.7.4] - 2026-06-07

### Fixed
- 进度条 pct < 5% 时不显示填充字符，现至少显示 1 格
- HTTP 响应解析：body 中含换行时状态码提取失败
- 余额浮点精度：`round(balance, 2)` 避免显示多余小数
- `int()` 转换未加 try-except，非数字值导致崩溃
- `ThreadPoolExecutor(max_workers=0)` 当所有 provider 被禁用时崩溃
- providers.json JSON 格式错误时无友好提示，现展示具体错误信息

### Changed
- 新增 `"enabled": false` 支持，可临时禁用 provider 而不删除配置
- 新增颜色常量 `C_OK`/`C_WARN`/`C_ERR`，消除散落的硬编码色值
- 统一 refreshTime 文档（30s），README/AGENTS.md 与脚本保持一致
- .gitignore 清理 Electron 时代残留条目
- DESIGN.md 标注为早期方案参考

## [0.7.3] - 2026-06-06

### Added
- 自适应配色：脚本检测 macOS 浅色/深色模式，自动切换全局文字色和标题色
- providers.json 新增 colors 段：colors.dark / colors.light 分别定义深浅模式下的 default、secondary、muted、header 四色
- docs/providers-config.html：providers.json 完整配置参考文档，含 23 色色板速查

### Changed
- 浅色模式下默认文字改为纯黑 #000000，解决白字在浅色菜单栏不可见的问题
- 浅色模式次要文字调深为 #3a3a3c，弱化文字调深为 #48484a
- DeepSeek nameColor #5AC8FA -> #0A84FF（iOS 系统蓝），深浅模式均清晰
- 配色从脚本硬编码移至 providers.json，修改 colors 无需改脚本

### Fixed
- set -o pipefail + set -e 导致 inline Python pipe 异常时脚本提前退出，加 || true 兜底
- ThreadPoolExecutor(max_workers=0) 当 providers 数组为空时抛 ValueError，改为 max(1, len(...))
- display.nameColor 未设置时使用自适应 default 色而非固定 #ffffff
## [0.7.2] - 2026-06-05

### Fixed
- DeepSeek 余额 API URL 移除多余的 /v1/ 前缀，适配官方文档 GET /user/balance 端点

### Changed
- 移除未使用的 spent 配置字段
- fetch_api: 去掉 curl -sf 中的 -f 标志，改为通过 -w %{http_code} 捕获 HTTP 状态码，出错时展示具体错误信息
- except: 裸捕获改为 except Exception:，避免吞掉 KeyboardInterrupt 等系统异常
- 余额解析增加 None 防护：余额缺失时显示 ? 而非 ¥None
- 并发化：ThreadPoolExecutor 并行获取所有 provider
- refreshTime 从 60s 调整至 30s，curl --max-time 从 10s 降至 5s

## [0.7.1] - 2026-06-05

### Added
- `display.nameColor` 字段：每个 provider 可在下拉菜单名称行使用独立强调色（默认 `#ffffff`）
- 下拉菜单标题 `Token Eye` 配色从灰 `#aaaaaa` 改为亮黄 `#FFD60A`

### Changed
- `balance` / `plan_usage` parser 渲染时优先读取 `display.nameColor`，缺失时回退到白

### Fixed
- `plan_usage` parser 的首行（`{name}:` 标题行）原本硬编码为白色，会忽略 `display.nameColor`；现在统一读取 `display.nameColor`，与 `balance` parser 行为一致

## [0.7.0] - 2026-06-04

### Changed
- MiniMax `token_plan/remains` 接口改为百分比制（`current_interval_remaining_percent` / `current_weekly_remaining_percent`），适配 M3 上线后的新字段
- 替换已废弃的 `current_interval_total_count` / `current_interval_usage_count` 字段
- `showModels` 从通配符匹配改为精确匹配

### Added
- 5 小时窗口与周窗口分别显示剩余百分比 + 状态语义（可用 / 耗尽临近 / 耗尽）
- 限时加成标识 `🔥x2.0`（`interval_boost_permille` / `weekly_boost_permille` > 1000 时显示）
- README 同步更新 API URL 与展示示例

## [0.6.0] - 2026-05-30

### Changed
- 脚本自动探测项目目录读取 `providers.json`，无需复制到 `~/SwiftBar/`
- 安装流程精简：只需复制 `token-eye.sh` 一个文件

### Added
- README 增加完整 parser 配置示例和"工作原理"图解
- GitHub About 设置项目简介和 topics 标签

## [0.5.0] - 2026-05-30

### Changed
- `providers.json` 移出 swiftbar 目录，放在项目根目录
- 项目结构调整为 `swiftbar/` + `providers.json`

### Added
- 完善 README：项目介绍、支持平台表格、parser 类型说明

## [0.4.0] - 2026-05-30

### Added
- MiMo provider：通过 `/v1/models` 验证 Key 有效性，显示"免费"状态
- 支持 `status` parser 类型（验证 API 可用性，无用量数据的平台）
- 菜单栏只显示 👁 图标，详情全部在下拉菜单

## [0.3.0] - 2026-05-30

### Changed
- 重构为配置驱动：`providers.json` 定义所有平台，脚本自动读取并调用
- 添加新平台只需编辑 JSON，无需改脚本代码
- 修复 `resolve_field` 对数组数字索引的支持

## [0.2.0] - 2026-05-30

### Changed
- 迁移到 SwiftBar 方案，去掉 Electron + menubar
- 纯 Shell + Python 脚本实现，零依赖、零后台进程

## [0.1.0] - 2026-05-30

### Added
- macOS 菜单栏常驻应用（Electron + menubar）
- DeepSeek 余额监控 + MiniMax 用量监控
- macOS Keychain 统一管理 API Key
