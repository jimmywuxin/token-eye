# Token Eye 👁

macOS 菜单栏 LLM Token 用量实时监控插件，基于 SwiftBar + Bash + Python。

**无 Node.js、无构建步骤、无后台进程** — 只需一个 Shell 脚本。

## 技术栈

- **SwiftBar** — macOS 菜单栏插件运行时（brew install --cask swiftbar）
- **Bash** — 主脚本（token-eye.sh），SwiftBar 每 30 秒执行一次
- **Python** — 内嵌在 Bash 脚本中，处理 JSON 解析、Keychain 读取、API 调用
- **macOS Keychain** — API Key 安全管理
- **curl + security CLI** — API 请求和 Keychain 读取

## 项目结构

```
token-eye/
├── swiftbar/
│   └── token-eye.sh       ← 插件脚本，复制到 ~/SwiftBar/
├── providers.json         ← 核心配置（JSON），定义所有平台
├── AGENTS.md              ← 本文件（项目指南）
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
SwiftBar（每30秒执行）
    ↓
~/SwiftBar/token-eye.sh（自动查找项目目录）
    ↓
$HOME/dev/token-eye/providers.json（读取配置）
    ↓
Python 内嵌脚本（单段，并发）：
  1. 检查 /tmp/token-eye-cache-{id}.json 缓存，命中则跳过 API
  2. 从 Keychain 读取各平台 API Key
  3. 并发调用各平台 API（ThreadPoolExecutor）
  4. HTTP 错误分类（5xx/4xx/网络/超时）
  5. 解析响应数据，balance 类检查告警阈值
  6. 输出 SwiftBar 格式菜单（含控制台跳转链接）
```

脚本自动查找 `providers.json` 的优先级：
1. `~/SwiftBar/providers.json`（脚本同目录）
2. `$HOME/dev/token-eye/providers.json`（项目根目录）
3. 项目目录的上一级

## providers.json 配置

### parser 类型

- **balance** — 余额型，适用于 DeepSeek 等有余额 API 的平台
- **plan_usage** — 用量型，适用于 MiniMax 等有按模型用量 API 的平台
- **status** — 状态型，适用于 MiMo 等只验证 Key 有效性的平台

### 全局可选字段

- `cache` — 按 parser 类型设置缓存 TTL（秒），默认 balance 300 / plan_usage 30 / status 60
- `menuBar.showSummary` — 菜单栏是否显示汇总数字，默认 false
- `alerts.{id}.minBalance` — balance 类余额阈值告警
- `colors.{dark,light}` — 自适应配色

### provider 可选字段

- `consoleUrl` — 控制台跳转链接，详情菜单末尾显示
- `cacheTtl` — 单 provider 覆盖全局缓存 TTL
- `alert.minBalance` — 单 provider 余额告警阈值
- `api.headers` — 额外请求头（如 OpenAI Organization）
- `parser.statusMap` — plan_usage 状态码映射，默认 `{1:可用, 2:耗尽临近, 3:耗尽}`
- `parser.barLength` — 进度条长度，默认 20
- `enabled` — 设为 false 临时禁用

详细配置示例见 `README.md`。

## 添加新平台

1. 编辑 `providers.json`，在 `providers` 数组中追加配置
2. 将对应 API Key 添加到 Keychain
3. SwiftBar 下次刷新时自动加载，无需修改脚本

## 开发注意事项

- 脚本使用 `set -euo pipefail`，任何命令失败都会退出
- API 超时时间：curl 5s，subprocess 10s
- SwiftBar 刷新间隔：30 秒（脚本内 `# <bitbar.refreshTime>30</bitbar.refreshTime>` 声明）
- 缓存文件位于 `/tmp/token-eye-cache-{id}.json`，失败请求 10s 短缓存避免连续打 API
- 告警去重标记 `/tmp/token-eye-alerted-{id}.flag`，余额恢复后自动清除
- 单段 Python 通过 `CONFIG_FILE="..." python3 << 'ENDOFPYTHON'` 内嵌，渲染逻辑合并，无需第二段进程
- 渲染层有 try-except 兜底，异常时输出占位菜单，不会空白
- 环境变量 `TOKEN_EYE_NOTIFY=0` 可临时禁用告警通知