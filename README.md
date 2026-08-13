# Token Eye 👁

> macOS 菜单栏 LLM Token 用量实时监控

在日常使用多个大模型（DeepSeek、MiniMax、MiMo 等）时，各平台的用量查看方式碎片化，需要分别登录各个开发者平台。Token Eye 把它们汇聚到菜单栏一个 👁 图标里，点击即看，无需离开当前工作。

## 功能

- 👁 菜单栏常驻图标，点击展开详情面板（可选显示汇总数字）
- 💰 DeepSeek 余额监控（¥）+ 余额阈值告警
- 📉 当日消耗估算：余额类平台基于余额快照差值自动统计今日花费，充值不干扰
- 📊 MiniMax 用量监控（M2.7 剩余次数 + 进度条 + 重置倒计时）
- 📈 用量趋势线：余额与剩余百分比历史迷你走势图（▁▂▃▄▅▆▇█）
- 💰 MiMo 余额监控（Cookie 鉴权）
- 🔑 所有 API Key 统一从 macOS Keychain 读取，安全且变更无需重启
- ⚙️ 配置驱动 — 添加新平台只需编辑项目里的 `providers.json`，零代码
- 💾 按类型 TTL 缓存，余额类 5 分钟、用量类 30 秒，省 90% API 调用
- 🔔 余额低于阈值时推送 macOS 系统通知（去重，不刷屏），回升后自动发「已恢复」通知
- 🔗 详情菜单可一键跳转各平台控制台
- 🚦 HTTP 错误分类：服务端异常 / 配置错误 / 网络失败 / 超时 各自独立文案与颜色
- 🚨 菜单栏标题按最差状态变色：任一平台异常 → 橙/红，一眼可见
- 🔄 每 30 秒自动刷新，支持手动刷新；新版本出现时菜单可「一键升级」
- 🪶 零依赖、零后台进程，仅一个 Shell 脚本

## 支持平台

| 平台 | 展示内容 | API | 控制台 |
|------|---------|-----|--------|
| DeepSeek | 余额 ¥13.5 | `/user/balance` | platform.deepseek.com/usage |
| MiniMax | M2.7/M3 92% · 周窗 100% · 🔥x2.0 加成中 | `/v1/token_plan/remains` | platform.minimaxi.com |
| MiMo | 余额 ¥5.0（Cookie 鉴权） | `/api/v1/balance` | platform.xiaomimimo.com |

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
~/SwiftBar/token-eye.sh                  →  SwiftBar 每 30 秒执行（薄启动器）
       ↓ 自动探测项目路径
$HOME/dev/token-eye/swiftbar/token_eye.py  →  Python 核心逻辑（缓存/告警/解析/渲染）
$HOME/dev/token-eye/providers.json         →  配置（与核心逻辑一样从项目目录读取）
```

脚本按优先级自动查找 `providers.json`：
1. 脚本同目录（`~/SwiftBar/`）
2. 上一级目录（项目根目录）
3. `~/dev/token-eye/`（默认路径）

### 更新

```bash
make install
# 或手动：
cp swiftbar/token-eye.sh ~/SwiftBar/
```

菜单栏版本自检发现新版本时，可直接点「⬆ 一键升级」：
- 项目目录是 git 仓库：自动 `git fetch + merge --ff-only origin/main` 并同步插件
- 非 git 仓库：自动下载 release 包替换插件文件

## 添加新平台

**推荐用向导**：`python3 scripts/add-provider.py` 交互式问答生成配置，自动校验并提示 Keychain 命令。

也可以手动编辑**项目根目录**的 `providers.json`（`~/dev/token-eye/providers.json`），在 `providers` 数组中追加配置，无需改脚本，无需复制文件。脚本下次刷新时自动加载。

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

### Cookie 鉴权（多 Cookie 组合）

部分平台（如 MiMo platform API）不用 Bearer Token，而是要求请求头携带**完整 Cookie 组合**——只发单个 Cookie（如仅 serviceToken）会返回 401。

配置方法：
1. 把完整 Cookie 串（`name1=value1; name2=value2; ...`）存入 Keychain 的**单个条目**
2. provider 配置 `authHeader: "Cookie"`、`authPrefix: ""`，Keychain 值作为整个 Cookie 头发送：

```json
{
  "api": {
    "url": "https://platform.xiaomimimo.com/api/v1/balance",
    "authHeader": "Cookie",
    "authPrefix": "",
    "headers": {
      "Accept": "application/json"
    }
  },
  "parser": {
    "type": "balance",
    "fields": {
      "balance": "data.balance",
      "currency": "data.currency"
    }
  }
}
```

**Cookie 过期维护**：MiMo 的 Cookie 是会话级，Edge 关闭或长时间不用后失效（菜单栏显示「配置/鉴权错误」）。重新登录平台后运行一键刷新脚本（支持 Edge / Chrome / Brave / Arc 任一已登录浏览器）：

```bash
/usr/bin/python3 scripts/refresh-mimo-cookie.py
```

脚本会从浏览器 Cookie 数据库提取并解密 4 个 Cookie（api-platform_ph / serviceToken / slh / userId），拼好更新到 Keychain `MIMO_PLATFORM_TOKEN`，并自动验证；鉴权错误时 Token Eye 也会自动触发该刷新（401 自愈）。

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

### 货币符号（display.currencySymbols）

balance 类默认 USD → `$`、其余 → `¥`，可自定义映射：

```json
{
  "display": {
    "currencySymbols": { "USD": "$", "EUR": "€", "CNY": "¥" }
  }
}
```

### 临时禁用通知

设环境变量 `TOKEN_EYE_NOTIFY=0` 可禁用告警通知（不影响其他功能）：

```bash
TOKEN_EYE_NOTIFY=0 bash ~/SwiftBar/token-eye.sh
```

### 调试日志

设 `TOKEN_EYE_DEBUG=1` 时，每次请求的缓存命中/状态码/耗时/自愈结果写入 `~/Library/Caches/token-eye/debug.log`：

```bash
TOKEN_EYE_DEBUG=1 bash ~/SwiftBar/token-eye.sh
tail -20 ~/Library/Caches/token-eye/debug.log
```

## 项目结构

```
token-eye/
├── swiftbar/
│   ├── token-eye.sh       ← SwiftBar 启动器（复制到 ~/SwiftBar/）
│   └── token_eye.py       ← 核心逻辑：缓存/告警/解析/渲染（从项目目录读取）
├── scripts/               ← 辅助脚本（Cookie 刷新 / 配色检查 / Schema 校验）
├── schema/
│   └── providers.schema.json  ← providers.json 的 JSON Schema（编辑器补全 + 校验）
├── tests/
│   └── test_token_eye.py  ← 单元测试（unittest，零依赖）
├── providers.json         ← 核心配置，脚本从项目目录自动读取
├── Makefile               ← make install / test / check
├── .github/workflows/     ← CI（语法/测试/Schema/配色/版本一致性）
├── AGENTS.md
├── DESIGN.md
├── CHANGELOG.md
└── README.md
```

## 开发与质量保障

项目无构建步骤，纯脚本。常用命令（详见 `Makefile`）：

```bash
make install    # 安装/更新插件到 ~/SwiftBar/
make test       # 单元测试（unittest，零依赖）
make check      # 全部检查：语法 + 测试 + Schema + 配色对比度
```

- **单元测试**：`swiftbar/token_eye.py` 的解析/告警/错误分类/缓存等核心函数全部可测，`tests/` 覆盖 90+ 用例，`python3 -m unittest discover -s tests` 即可运行
- **JSON Schema**：`schema/providers.schema.json` 描述配置结构；VS Code 等编辑器打开 `providers.json` 时自动补全与校验；`python3 scripts/validate-schema.py` 提供零依赖的运行时校验（脚本内置的轻量校验用于菜单栏提示）
- **CI**：GitHub Actions（`.github/workflows/ci.yml`）自动执行 bash 语法 + ShellCheck、Python 编译、单元测试、Schema 校验、配色对比度、版本一致性检查
- **配色回归**：`scripts/check-colors.py` 保证全部颜色 WCAG AA ≥4.5:1
- **排查**：`TOKEN_EYE_DEBUG=1` 输出调试日志到 `~/Library/Caches/token-eye/debug.log`

## License

MIT
