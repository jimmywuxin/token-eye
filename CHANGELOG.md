# Changelog

## [0.1.0] - 2026-05-30

### Added
- macOS 菜单栏常驻应用，不占 Dock 位
- DeepSeek 余额监控（调用 `/v1/user/balance` API）
- MiniMax 用量监控（M2.7 模型剩余次数 + 进度条 + 重置倒计时）
- 所有 API Key 统一从 macOS Keychain 读取，每次轮询重新读取，变更无需重启
- 配置驱动的 Provider 引擎，添加新平台只需编辑 `providers.json`，零代码
- 60 秒自动轮询，打开面板时自动触发刷新
- 暗色主题 UI，支持 status 色标（绿/黄/红/灰）
- 无 Key 时显示 Keychain 添加命令提示

### Known Issues
- 仅支持 macOS（依赖 `security` 命令读取 Keychain）
- DeepSeek balance API 返回字段可能随版本变化，需关注
