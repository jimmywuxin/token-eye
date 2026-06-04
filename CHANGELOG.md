# Changelog

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
