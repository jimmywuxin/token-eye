# Changelog

## [0.5.0] - 2026-05-30

### Changed
- `providers.json` 移出 swiftbar 目录，放在项目根目录

### Added
- 完善 README：项目介绍、支持平台表格、parser 类型说明
- GitHub About：添加项目简介和 topics 标签

## [0.4.0] - 2026-05-30

### Added
- MiMo provider：通过 `/v1/models` 验证 Key 有效性，显示"免费"状态
- 支持 `status` parser 类型（验证 API 可用性，无用量数据的平台）
- 菜单栏只显示 👁 图标，详情全部在下拉菜单

## [0.3.0] - 2026-05-30

### Changed
- 重构为配置驱动：providers.json 定义所有平台，脚本自动读取并调用
- 添加新平台只需编辑 JSON，无需改脚本代码
- 修复 resolve_field 对数组索引的支持

## [0.2.0] - 2026-05-30

### Changed
- 迁移到 SwiftBar 方案，去掉 Electron + menubar
- 纯 Shell + Python 脚本实现，零依赖

## [0.1.0] - 2026-05-30

### Added
- macOS 菜单栏常驻应用（Electron + menubar）
- DeepSeek 余额监控 + MiniMax 用量监控
- macOS Keychain 统一管理 API Key
