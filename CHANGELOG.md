# Changelog

## [0.3.0] - 2026-05-30

### Changed
- 重构为配置驱动：providers.json 定义所有平台，脚本自动读取并调用
- 添加新平台只需编辑 JSON，无需改脚本代码
- 修复 resolve_field 对数组索引的支持（DeepSeek balance_infos.0.total_balance）

## [0.2.0] - 2026-05-30

### Changed
- 迁移到 SwiftBar 方案，去掉 Electron + menubar
- 纯 Shell + Python 脚本实现，零依赖
- 菜单栏显示紧凑摘要，下拉菜单显示详情 + 进度条

## [0.1.0] - 2026-05-30

### Added
- macOS 菜单栏常驻应用（Electron + menubar）
- DeepSeek 余额监控 + MiniMax 用量监控
- macOS Keychain 统一管理 API Key
