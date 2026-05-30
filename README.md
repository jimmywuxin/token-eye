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

## 使用方法

### 1. 安装 SwiftBar

```bash
brew install --cask swiftbar
```

安装后启动 SwiftBar，它会出现在菜单栏。首次运行需要选择一个插件目录，选择 `~/SwiftBar/` 即可。

### 2. 添加 API Key 到 Keychain

```bash
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-你的key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "你的key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "你的key"
```

Keychain 服务名约定：`<平台名大写>_API_KEY`，脚本会自动按此规则查找。

### 3. 安装脚本

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
chmod +x ~/SwiftBar/token-eye.sh
```

SwiftBar 会自动检测新脚本，菜单栏立即出现 👁 图标。

> **注意**：只需复制 `token-eye.sh`。`providers.json` 直接从项目目录读取，不需要复制到 `~/SwiftBar/`。

### 4. 更新

```bash
cp swiftbar/token-eye.sh ~/SwiftBar/
```

修改 `providers.json` 无需重启，下次刷新时自动生效。

## 添加新平台

编辑项目根目录的 `providers.json`，在 `providers` 数组中追加一段配置，无需改脚本。

### Parser 类型

| Parser | 适用场景 | 数据展示 |
|--------|---------|---------|
| `balance` | 有余额 API | 余额数字 |
| `plan_usage` | 有按模型用量 API | 模型列表 + 进度条 + 倒计时 |
| `status` | 无用量 API | 验证 Key 有效性，显示自定义标签 |

### balance 配置示例

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
      "total": "current_interval_total_count",
      "used": "current_interval_usage_count",
      "resetMs": "remains_time"
    },
    "modelLabels": { "MiniMax-M*": "M2.7" },
    "showModels": ["MiniMax-M*"]
  },
  "display": { "unit": "次", "label": "剩余次数" }
}
```

- `fields` 支持 `.` 分隔的嵌套路径（如 `balance_infos.0.total_balance`）和数组数字索引
- `showModels` 过滤只展示特定模型名称（支持 `*` 通配符前缀匹配）
- `modelLabels` 给原始模型名起别名

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
│   └── token-eye.sh       ← SwiftBar 插件脚本
├── providers.json         ← API 配置（核心扩展点，脚本从项目目录读取）
├── DESIGN.md              ← 设计文档
├── CHANGELOG.md
└── README.md
```

## License

MIT
