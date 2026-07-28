# Token Eye 👁

> macOS 菜单栏 LLM Token 用量实时监控

在日常使用多个大模型（DeepSeek、MiniMax、MiMo 等）时，各平台的用量查看方式碎片化，需要分别登录各个开发者平台。Token Eye 把它们汇聚到菜单栏一个 👁 图标里，点击即看，无需离开当前工作。

## 功能

- 👁 菜单栏常驻图标，点击展开详情面板（可选显示汇总数字）
- 💰 DeepSeek 余额监控（¥）+ 余额阈值告警
- 📊 MiniMax 用量监控（M2.7 剩余次数 + 进度条 + 重置倒计时）
- 🆓 MiMo 可用性检测
- 🔑 所有 API Key 统一从 macOS Keychain 读取，安全且变更无需重启
- ⚙️ 配置驱动 — 添加新平台只需编辑项目里的 `providers.json`，零代码
- 💾 按类型 TTL 缓存，余额类 5 分钟、用量类 30 秒，省 90% API 调用
- 🔔 余额低于阈值时推送 macOS 系统通知（去重，不刷屏）
- 🔗 详情菜单可一键跳转各平台控制台
- 🚦 HTTP 错误分类：服务端异常 / 配置错误 / 网络失败 / 超时 各自独立文案与颜色
- 🔄 每 30 秒自动刷新，支持手动刷新
- 🪶 零依赖、零后台进程，仅一个 Shell 脚本

## 支持平台

| 平台 | 展示内容 | API | 控制台 |
|------|---------|-----|--------|
| DeepSeek | 余额 ¥13.5 | `/user/balance` | platform.deepseek.com/usage |
| MiniMax | M2.7/M3 92% · 周窗 100% · 🔥x2.0 加成中 | `/v1/token_plan/remains` | platform.minimaxi.com |
| MiMo | 免费 · API Key 有效 | `/v1/models` | api.xiaomimimo.com |

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

## 高级配置

### 缓存（cache）

按 parser 类型设置 TTL（秒），命中缓存跳过 API 调用。失败请求 10s 内不重试，避免连续打 API。

```json
{
  "cache": {
    "balance": 300,
    "plan_usage": 30,
    "status": 60
  }
}
```

单个 provider 可用 `cacheTtl` 字段覆盖全局设置：

```json
{
  "id": "deepseek",
  "cacheTtl": 600
}
```

### 菜单栏汇总（menuBar）

默认菜单栏只显示 👁。开启 `showSummary` 后显示关键数字汇总：

```json
{
  "menuBar": {
    "showSummary": true
  }
}
```

效果：`👁 ¥13.5 | ✅ M2.7 92% | 免费`

### 余额告警（alert）

balance parser 支持 `alert.minBalance`，余额低于阈值时推送 macOS 系统通知（去重，余额恢复前不重复通知）：

```json
{
  "id": "deepseek",
  "alert": { "minBalance": 5.0 }
}
```

也可在根 `alerts` 段按 provider id 配置：

```json
{
  "alerts": {
    "deepseek": { "minBalance": 5.0 }
  }
}
```

### 控制台跳转（consoleUrl）

provider 配置 `consoleUrl`，详情菜单末尾出现「→ 打开 X 控制台」可点击跳转：

```json
{
  "id": "deepseek",
  "consoleUrl": "https://platform.deepseek.com/usage"
}
```

### 自定义请求头（api.headers）

支持额外 HTTP header（如 OpenAI Organization）：

```json
{
  "api": {
    "url": "...",
    "headers": {
      "OpenAI-Organization": "org-xxx"
    }
  }
}
```

### plan_usage 状态映射（parser.statusMap）

自定义状态码到文案的映射，默认 `{1: 可用, 2: 耗尽临近, 3: 耗尽}`：

```json
{
  "parser": {
    "statusMap": {
      "1": "可用",
      "2": "耗尽临近",
      "3": "耗尽"
    }
  }
}
```

### 进度条长度（parser.barLength）

默认 20 格，可自定义：

```json
{
  "parser": {
    "barLength": 16
  }
}
```

### 临时禁用通知

设环境变量 `TOKEN_EYE_NOTIFY=0` 可禁用告警通知（不影响其他功能）：

```bash
TOKEN_EYE_NOTIFY=0 bash ~/SwiftBar/token-eye.sh
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
