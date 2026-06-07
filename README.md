# Token Eye 👁

> macOS 菜单栏 LLM Token 用量实时监控

在日常使用多个大模型（DeepSeek、MiniMax、MiMo 等）时，各平台的用量查看方式碎片化，需要分别登录各个开发者平台。Token Eye 把它们汇聚到菜单栏一个 👁 图标里，点击即看，无需离开当前工作。

## 功能

- 👁 菜单栏常驻图标，点击展开详情面板
- 💰 DeepSeek 余额监控（¥）
- 📊 MiniMax 用量监控（M2.7 剩余次数 + 进度条 + 重置倒计时）
- 🆓 MiMo 可用性检测
- 🔑 所有 API Key 统一从 macOS Keychain 读取，安全且变更无需重启
- ⚙️ 配置驱动 — 添加新平台只需编辑项目里的 `providers.json`，零代码
- 🔄 每 30 秒自动刷新，支持手动刷新
- 🪶 零依赖、零后台进程，仅一个 Shell 脚本

## 支持平台

| 平台 | 展示内容 | API |
|------|---------|-----|
| DeepSeek | 余额 ¥9.67 | `/v1/user/balance` |
| MiniMax | M2.7/M3 71% · 周窗 100% · 🔥x2.0 加成中 | `/v1/token_plan/remains` |
| MiMo | 免费 · API Key 有效 | `/v1/models` |

## 使用方法

### 1. 安装 SwiftBar

```bash
brew install --cask swiftbar
```

启动 SwiftBar，首次运行选择一个插件目录，选 `~/SwiftBar/`。

### 2. 添加 API Key 到 Keychain

```bash
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-你的key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "你的key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "你的key"
```

Keychain 服务名约定：`<平台名大写>_API_KEY`。

### 3. 将脚本放入 SwiftBar 插件目录

只需复制 `token-eye.sh` 到 `~/SwiftBar/` 即可，**不需要复制 `providers.json`** — 脚本会自动从项目目录读取：

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
chmod +x ~/SwiftBar/token-eye.sh
```

SwiftBar 自动检测新脚本，菜单栏出现 👁 图标即完成。

### 工作原理

```
~/SwiftBar/token-eye.sh          →  SwiftBar 每 30 秒执行
       ↓ 自动探测项目路径
$HOME/dev/token-eye/providers.json  →  脚本直接读取项目里的配置
```

脚本按优先级自动查找 `providers.json`：
1. 脚本同目录（`~/SwiftBar/`）
2. 上一级目录（项目根目录）
3. `~/dev/token-eye/`（默认路径）

### 更新

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
```

## 添加新平台

编辑**项目根目录**的 `providers.json`（`~/dev/token-eye/providers.json`），在 `providers` 数组中追加配置，无需改脚本，无需复制文件。脚本下次刷新时自动加载。

### Parser 类型

| Parser | 适用场景 | 数据展示 |
|--------|---------|---------|
| `balance` | 有余额 API | 余额数字 |
| `plan_usage` | 有按模型用量 API | 模型列表 + 进度条 + 倒计时 |
| `status` | 无用量 API | 验证 Key 有效性，显示自定义标签 |

### balance 配置示例

在 `providers.json` 的 `"providers": [...]` 中追加：

```json
{
  "id": "openai",
  "name": "OpenAI",
  "keychainService": "OPENAI_API_KEY",
  "api": {
    "url": "https://api.openai.com/v1/dashboard/billing/credit_grants",
    "method": "GET",
    "authHeader": "Authorization",
    "authPrefix": "Bearer "
  },
  "parser": {
    "type": "balance",
    "fields": {
      "balance": "total_granted",
      "currency": "currency"
    }
  },
  "display": { "unit": "$", "label": "余额" }
}
```

### plan_usage 配置示例

```json
{
  "id": "minimax",
  "name": "MiniMax",
  "keychainService": "MINIMAX_CN_API_KEY",
  "api": {
    "url": "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains",
    "method": "GET",
    "authHeader": "Authorization",
    "authPrefix": "Bearer "
  },
  "parser": {
    "type": "plan_usage",
    "arrayPath": "model_remains",
    "fields": {
      "model": "model_name",
      "intervalPct": "current_interval_remaining_percent",
      "intervalStatus": "current_interval_status",
      "weeklyPct": "current_weekly_remaining_percent",
      "weeklyStatus": "current_weekly_status",
      "intervalBoost": "interval_boost_permille",
      "weeklyBoost": "weekly_boost_permille",
      "resetMs": "remains_time"
    },
    "modelLabels": { "general": "M2.7/M3 通用" },
    "showModels": ["general", "video"]
  },
  "display": { "unit": "%", "label": "剩余" }
}
```

- `fields` 支持 `.` 分隔的嵌套路径和数组数字索引（如 `balance_infos.0.total_balance`）
- `showModels` 精确匹配模型名（如 `general`、`video`）
- `modelLabels` 给原始模型名起别名
- 百分比接口（`intervalPct` / `weeklyPct`）直接使用 0-100 的整数；旧版按次数计的 `total` / `used` 字段已废弃

### status 配置示例

```json
{
  "id": "mimo",
  "name": "MiMo",
  "keychainService": "MIMO_API_KEY",
  "api": {
    "url": "https://api.xiaomimimo.com/v1/models",
    "method": "GET",
    "authHeader": "Authorization",
    "authPrefix": "Bearer "
  },
  "parser": {
    "type": "status",
    "okField": "object",
    "okValue": "list"
  },
  "display": { "label": "免费" }
}
```

## 项目结构

```
token-eye/
├── swiftbar/
│   └── token-eye.sh       ← 复制到 ~/SwiftBar/，SwiftBar 运行它
├── providers.json         ← 核心配置，脚本从项目目录自动读取
├── DESIGN.md              ← 设计文档
├── CHANGELOG.md
└── README.md
```

## License

MIT
