# Changelog

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
