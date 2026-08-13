# Changelog

## [Unreleased]

### Added
- **当日消耗估算**：余额类平台（DeepSeek / MiMo）基于当天余额快照差值统计「今日消耗 ¥x.xx」，充值不会干扰统计（`daily_spend`，仅消耗 > 0 时显示在详情菜单）
- **plan_usage 趋势线**：MiniMax 等用量类平台记录剩余百分比历史，详情菜单显示趋势线（与余额趋势同款 sparkline）

### Changed
- 历史记录（`~/Library/Caches/token-eye/history-{id}.jsonl`）现在同时服务于余额趋势、今日消耗估算与用量趋势三处

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
