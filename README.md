# Token Eye 👁

macOS 菜单栏 LLM Token 用量实时监控工具。

常驻在菜单栏，点击即看各平台余额和用量，每 60 秒自动刷新。

## 快速开始

### 前置条件

- macOS
- [SwiftBar](https://swiftbar.app/)（`brew install --cask swiftbar`）
- 各平台的 API Key

### 安装

```bash
# 1. 安装 SwiftBar（如未安装）
brew install --cask swiftbar

# 2. 添加 API Key 到 Keychain
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-你的key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "你的key"

# 3. 复制脚本和配置到 SwiftBar 插件目录
cp swiftbar/token-eye.sh ~/SwiftBar/
cp swiftbar/providers.json ~/SwiftBar/
chmod +x ~/SwiftBar/token-eye.sh
```

启动 SwiftBar 后菜单栏会出现 👁 图标。

### 更新

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
cp swiftbar/providers.json ~/SwiftBar/
```

## 添加新平台

编辑 `providers.json`，追加一段配置即可，无需改脚本：

```json
{
  "id": "your-provider",
  "name": "Your Provider",
  "keychainService": "YOUR_API_KEY",
  "api": {
    "url": "https://api.example.com/v1/usage",
    "method": "GET",
    "authHeader": "Authorization",
    "authPrefix": "Bearer "
  },
  "parser": {
    "type": "balance",
    "fields": {
      "balance": "balance",
      "currency": "currency"
    }
  },
  "display": { "unit": "$", "label": "余额" }
}
```

支持两种 parser 类型：
- `balance` — 单值展示（余额）
- `plan_usage` — 列表展示（多模型剩余次数 + 进度条 + 倒计时）

## 技术方案

- **SwiftBar** — macOS 菜单栏脚本运行器
- **providers.json** — 配置文件驱动，添加新平台零代码
- **Shell + Python** — curl 调 API，python3 解析 JSON
- **macOS Keychain** — API Key 安全存储
- 零依赖、零后台进程

## License

MIT
