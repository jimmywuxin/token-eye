# Token Eye 👁

> macOS 菜单栏 LLM Token 用量实时监控

在日常使用多个大模型（DeepSeek、MiniMax、MiMo 等）时，各平台的用量查看方式碎片化，需要分别登录各个开发者平台。Token Eye 把它们汇聚到菜单栏一个 👁 图标里，点击即看，无需离开当前工作。

## 功能

- 👁 菜单栏常驻图标，点击展开详情面板
- 💰 DeepSeek 余额监控（¥）
- 📊 MiniMax 用量监控（M2.7 剩余次数 + 进度条 + 重置倒计时）
- 🆓 MiMo 可用性检测
- 🔑 所有 API Key 统一从 macOS Keychain 读取，安全且变更无需重启
- ⚙️ 配置驱动 — 添加新平台只需编辑 `providers.json`，零代码
- 🔄 每 60 秒自动刷新，支持手动刷新
- 🪶 零依赖、零后台进程，仅一个 Shell 脚本

## 支持平台

| 平台 | 展示内容 | API |
|------|---------|-----|
| DeepSeek | 余额 ¥9.67 | `/v1/user/balance` |
| MiniMax | M2.7 0/600次 · 重置 2h | `/v1/api/openplatform/coding_plan/remains` |
| MiMo | 免费 · API Key 有效 | `/v1/models` |

## 快速开始

### 前置条件

- macOS
- [SwiftBar](https://swiftbar.app/)（`brew install --cask swiftbar`）

### 安装

```bash
# 1. 安装 SwiftBar（如未安装）
brew install --cask swiftbar

# 2. 添加 API Key 到 Keychain
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-你的key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "你的key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "你的key"

# 3. 复制脚本和配置到 SwiftBar 插件目录
cp swiftbar/token-eye.sh ~/SwiftBar/ cp swiftbar/token-eye.sh ~/SwiftBar/cp swiftbar/token-eye.sh ~/SwiftBar/ chmod +x ~/SwiftBar/token-eye.sh
chmod +x ~/SwiftBar/token-eye.sh
```

启动 SwiftBar，菜单栏出现 👁 即完成。

### 更新

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/ cp swiftbar/token-eye.sh ~/SwiftBar/cp swiftbar/token-eye.sh ~/SwiftBar/ chmod +x ~/SwiftBar/token-eye.sh
```

## 添加新平台

编辑 `swiftbar/providers.json`，追加一段配置，无需改脚本。支持三种 parser：

| Parser | 适用场景 | 数据展示 |
|--------|---------|---------|
| `balance` | 有余额 API | 余额数字 |
| `plan_usage` | 有按模型用量 API | 模型列表 + 进度条 + 倒计时 |
| `status` | 无用量 API | 验证 Key 有效性，显示自定义标签 |

完整配置示例参考 `swiftbar/providers.json`。

## 项目结构

```
token-eye/
├── swiftbar/
│   ├── token-eye.sh       ← SwiftBar 插件脚本
│   └── providers.json     ← API 配置（核心扩展点）
├── DESIGN.md              ← 设计文档
├── CHANGELOG.md
└── README.md
```

## License

MIT
