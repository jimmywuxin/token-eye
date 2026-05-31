# Token Eye 👁

macOS 菜单栏 LLM Token 用量实时监控插件，基于 SwiftBar + Bash + Python。

**无 Node.js、无构建步骤、无后台进程** — 只需一个 Shell 脚本。

## 技术栈

- **SwiftBar** — macOS 菜单栏插件运行时（brew install --cask swiftbar）
- **Bash** — 主脚本（token-eye.sh），SwiftBar 每 60 秒执行一次
- **Python** — 内嵌在 Bash 脚本中，处理 JSON 解析、Keychain 读取、API 调用
- **macOS Keychain** — API Key 安全管理
- **curl + security CLI** — API 请求和 Keychain 读取

## 项目结构

```
token-eye/
├── swiftbar/
│   └── token-eye.sh       ← 插件脚本，复制到 ~/SwiftBar/
├── providers.json         ← 核心配置（JSON），定义所有平台
├── CLAUDE.md              ← 本文件
├── README.md
├── CHANGELOG.md
└── DESIGN.md
```

**无 src/、无 dist/、无 package.json** — 项目本身不需要编译构建。

## 环境要求

- macOS
- SwiftBar（`brew install --cask swiftbar`）
- Python 3（系统自带 `/usr/bin/python3`）
- `security` CLI（macOS 内置）
- `curl`（macOS 内置）

## 常用命令

### 安装/更新插件
```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
chmod +x ~/SwiftBar/token-eye.sh
```

### 添加 API Key 到 Keychain
```bash
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-your-key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "your-key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "your-key"
```

### 验证 Keychain 中的 Key
```bash
security find-generic-password -s DEEPSEEK_API_KEY -w
```

## 工作原理

```
SwiftBar（每60秒执行）
    ↓
~/SwiftBar/token-eye.sh（自动查找项目目录）
    ↓
$HOME/dev/token-eye/providers.json（读取配置）
    ↓
Python 内嵌脚本：
  1. 从 Keychain 读取各平台 API Key
  2. 调用各平台 API
  3. 解析响应数据
  4. 输出 SwiftBar 格式菜单
```

脚本自动查找 `providers.json` 的优先级：
1. `~/SwiftBar/providers.json`（脚本同目录）
2. `$HOME/dev/token-eye/providers.json`（项目根目录）
3. 项目目录的上一级

## providers.json 配置

### balance parser（余额型）
适用于有余额 API 的平台，如 DeepSeek。

### plan_usage parser（用量型）
适用于有按模型用量 API 的平台，如 MiniMax。

### status parser（状态型）
适用于无用量 API、只验证 Key 有效性的平台，如 MiMo。

详细配置示例见 `README.md`。

## 添加新平台

1. 编辑 `providers.json`，在 `providers` 数组中追加配置
2. 将对应 API Key 添加到 Keychain
3. SwiftBar 下次刷新时自动加载，无需修改脚本

## 开发注意事项

- 脚本使用 `set -euo pipefail`，任何命令失败都会退出
- API 超时时间：curl 10s，整体 15s
- SwiftBar 刷新间隔：60 秒（脚本内 `# <bitbar.refreshTime>60</bitbar.refreshTime>` 声明）
- Python 代码通过 `CONFIG_FILE="..." python3 << 'PYEOF'` 内嵌在 Bash 中