# Token Eye 👁

macOS 菜单栏 LLM Token 用量实时监控插件，基于 SwiftBar + Bash + Python。

**无 Node.js、无构建步骤、无后台进程** — 只需一个 Shell 脚本。

## 技术栈

- **SwiftBar** — macOS 菜单栏插件运行时（brew install --cask swiftbar）
- **Bash** — 启动器（token-eye.sh），SwiftBar 每 30 秒执行一次
- **Python** — 核心逻辑（token_eye.py），处理 JSON 解析、Keychain 读取、API 调用、菜单渲染
- **macOS Keychain** — API Key 安全管理
- **curl + security CLI** — API 请求和 Keychain 读取

## 项目结构

```
token-eye/
├── swiftbar/
│   ├── token-eye.sh       ← 插件启动器，复制到 ~/SwiftBar/
│   └── token_eye.py       ← 核心逻辑（缓存/告警/解析/渲染），从项目目录读取
├── scripts/
│   ├── refresh-mimo-cookie.py  ← MiMo Cookie 一键刷新（多浏览器，会话过期时运行）
│   ├── check-colors.py         ← 配色对比度回归检查（WCAG AA ≥4.5:1）
│   ├── validate-schema.py      ← providers.json JSON Schema 校验（零依赖）
│   ├── add-provider.py         ← 新平台添加向导（交互式，支持模板）
│   └── provider-templates.json ← 内置平台模板库（OpenAI/Kimi/GLM/…）
├── schema/
│   └── providers.schema.json   ← 配置结构定义（编辑器补全 + 校验）
├── tests/
│   └── test_token_eye.py       ← 单元测试（unittest，零依赖）
├── providers.json         ← 核心配置（JSON），定义所有平台
├── Makefile               ← make install / test / check
├── .github/workflows/ci.yml    ← CI（语法/测试/Schema/配色/版本一致性）
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
make install              # 或手动：cp swiftbar/token-eye.sh ~/SwiftBar/ && chmod +x
```

### 质量保障（提交前跑）
```bash
make test                 # 单元测试（unittest，零依赖）
make check                # 全部检查：语法 + 测试 + Schema + 配色对比度
make validate             # 仅 Schema + 配色
```

### 添加 API Key 到 Keychain
```bash
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-your-key"
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "your-key"
security add-generic-password -s "MIMO_API_KEY" -a "" -w "your-key"
```

### 添加新平台
```bash
/usr/bin/python3 scripts/add-provider.py    # 交互式向导，零代码
```

### 验证 Keychain 中的 Key
```bash
security find-generic-password -s DEEPSEEK_API_KEY -w
```

## 工作原理

```
SwiftBar（每30秒执行）
    ↓
~/SwiftBar/token-eye.sh（薄启动器，自动查找项目目录）
    ↓
$HOME/dev/token-eye/swiftbar/token_eye.py（核心逻辑，单进程，并发）
    ↓
$HOME/dev/token-eye/providers.json（读取配置）
    ↓
Python 核心逻辑：
  1. 检查 /tmp/token-eye-cache-{id}.json 缓存，命中则跳过 API
  2. 从 Keychain 读取各平台 API Key
  3. 并发调用各平台 API（ThreadPoolExecutor）
  4. HTTP 错误分类（5xx/4xx/网络/超时）
  5. 解析响应数据，balance 类检查告警阈值并统计今日消耗
  6. 输出 SwiftBar 格式菜单（含控制台跳转链接）
```

脚本自动查找 `providers.json` 的优先级（`token_eye.py` 同理，位于项目目录 `swiftbar/` 下）：
1. `~/SwiftBar/providers.json`（脚本同目录）
2. `$HOME/dev/token-eye/providers.json`（项目根目录）
3. 项目目录的上一级

## providers.json 配置

### parser 类型

- **balance** — 余额型，适用于 DeepSeek、MiMo（Cookie 鉴权）等有余额 API 的平台
- **plan_usage** — 用量型，适用于 MiniMax 等有按模型用量 API 的平台
- **status** — 状态型，适用于只验证 Key 有效性的平台

### 全局可选字段

- `cache` — 按 parser 类型设置缓存 TTL（秒），默认 balance 300 / plan_usage 30 / status 60
- `menuBar.showSummary` — 菜单栏汇总：false 不显示 / true 全部 / id 数组（如 `["deepseek","mimo"]`）只显示指定平台
- `alerts.{id}.minBalance` — balance 类余额阈值告警（按 parser 类型 balance 的阈值优先级链：API 字段阈值 `parser.fields.alertThreshold` > `provider.alert.minBalance` > `parser.defaultMinBalance` > 不告警；前两项均无则用兜底默认）
- `alerts.{id}.minPct` — plan_usage 类用量告警阈值（**已用%** 方向，与 dsh-cost-meter coding plan 卡片一致；已用% 超过阈值触发告警，如 minimax `{"minPct": 80}`）
- `colors.{dark,light}` — 自适应配色

### provider 可选字段

- `consoleUrl` — 控制台跳转链接，详情菜单末尾显示
- `cacheTtl` — 单 provider 覆盖全局缓存 TTL
- `alert.minBalance` / `alert.minPct` / `alert.dailySpendMax` / `alert.daysLeft` — 单 provider 告警阈值（balance 余额/用量百分比/当日消耗上限/预计可用天数预警）
- `api.headers` — 额外请求头（如 OpenAI Organization、User-Agent）
- `parser.statusMap` — plan_usage 状态码映射，默认 `{1:可用, 2:耗尽临近, 3:耗尽}`；接口返回百分比字段时**优先按百分比推断状态**（≥20 可用 / 10-20 耗尽临近 / <10 耗尽），statusMap 仅在旧接口兜底
- `parser.barLength` — 进度条长度，默认 20
- `parser.fields.intervalTotal` / `weeklyTotal` — 旧接口的套餐总量字段路径；仅当接口无百分比字段时生效（total=0 显示「无套餐」）。**注意：MiniMax 新接口该字段已废弃恒为 0，状态由百分比推断**
- `display.nameColor` — 平台名颜色；支持深浅双套 `{"dark":"#xxx","light":"#xxx"}`，随系统外观切换（注意红绿色弱对比度）
- `refreshParam` — 鉴权错误时自动刷新 + 菜单「🔄 刷新 Cookie」点击项（如 MiMo 的 `refresh-mimo-cookie`）
- `refreshInterval` — 主动续期周期（秒，≥60）：即使 cookie 仍有效也定期从浏览器复制最新 cookie，保持 keychain 与浏览器会话同步、减少 401 触发面（仅对配置了 `refreshParam` 的 provider 生效）
- `enabled` — 设为 false 临时禁用

### Cookie 鉴权（MiMo 特例）

- MiMo platform API（`/api/v1/balance`）要求**完整 Cookie 组合**（ph + serviceToken + slh + userId），仅单个 Cookie 返回 401
- 完整 Cookie 串存 Keychain 单个条目 `MIMO_PLATFORM_TOKEN`，provider 配 `authHeader: "Cookie"` + `authPrefix: ""`
- Cookie 为会话级，过期后运行 `scripts/refresh-mimo-cookie.py` 一键刷新（支持 Edge / Chrome / Brave / Arc，从任一已登录浏览器解密提取）
- **半自动刷新机制**：`refreshInterval` 按周期主动续 cookie（浏览器会话存活时 keychain 始终最新）；当服务端会话真正过期、浏览器同步失效导致刷新失败时，自动在默认浏览器打开 `consoleUrl` 登录页并发系统通知（`token-eye-loginopened-*.flag` 30 分钟限频），登录后下个 5 分钟重试周期自动拾取新 cookie——**无需再手动跑刷新脚本**

详细配置示例见 `README.md`。

## 添加新平台

1. 编辑 `providers.json`，在 `providers` 数组中追加配置
2. 将对应 API Key 添加到 Keychain
3. SwiftBar 下次刷新时自动加载，无需修改脚本

## 开发注意事项

- 核心逻辑在 `swiftbar/token_eye.py`（可 import、可单测），`token-eye.sh` 只做环境检测与转发；两者都从项目目录读取，部署时**只需复制 token-eye.sh**
- 提交前跑 `make check`（语法 + 单元测试 + Schema + 配色）；CI（`.github/workflows/ci.yml`）会在 push/PR 时自动执行同样的检查
- 改配置结构时：同步更新 `schema/providers.schema.json` 与 `token_eye.py` 里的 `schema_validate`（运行时轻量校验，与 JSON Schema 互补）
- 版本号双处维护：`token-eye.sh` 头部 `bitbar.version` 与 `token_eye.py` 的 `VERSION`，CI 校验两者一致
- 脚本使用 `set -euo pipefail`，任何命令失败都会退出（注意：命令替换里放可能失败的脚本时需 `|| true` 兜底，见 refresh-mimo-cookie 分支）
- API 超时时间：curl 5s，subprocess 10s
- SwiftBar 刷新间隔：30 秒（脚本内 `# <bitbar.refreshTime>30</bitbar.refreshTime>` 声明）
- 缓存文件位于 `/tmp/token-eye-cache-{id}.json`，失败请求 10s 短缓存避免连续打 API
- 告警去重/自愈防抖标记位于 `~/Library/Caches/token-eye/token-eye-{alerted|recovered|autorefresh}-{id}.flag`（持久化，重启不丢）；余额/用量恢复时发「已恢复」通知（去重）
- 自愈冷却策略：`autorefresh` 标记内容为 `<ts> ok|fail`——**失败后 5 分钟可重试**（会话可能很快恢复），成功后 30 分钟防抖；自愈失败原因会显示在错误菜单
- 半自动刷新额外标记（均在 `~/Library/Caches/token-eye/`）：`token-eye-loginopened-{id}.flag` 记录自动打开登录页的时间戳（30 分钟限频）；`token-eye-lastrefresh-{id}.flag` 记录主动续期成功的时间戳（用于 `refreshInterval` 节流）
- 历史文件（history-*.jsonl）保留 30 天，每天自动清理一次（`cleanup_history` / `last-cleanup.ts` 标记），防无限增长
- 告警通知默认带提示音（`TOKEN_EYE_SOUND` 换声音名，`0` 静音）；`TOKEN_EYE_DEBUG=1` 时请求明细写入 `~/Library/Caches/token-eye/debug.log`
- 趋势窗口 `HISTORY_LEN=288`（≈2.4h），`sparkline` 自动均匀降采样到 24 字符宽
- 行级交互参数（`param1=copy-balance` / `href`）通过 render dict 的 `line_params` 列表与 `lines` 一一对应，新增行时必须同步 append（None 或参数 dict）
- 模板库 `scripts/provider-templates.json` 的每个模板必须通过 JSON Schema 与运行时校验（测试覆盖）
- 渲染层有 try-except 兜底，异常时输出占位菜单，不会空白
- 环境变量 `TOKEN_EYE_NOTIFY=0` 可临时禁用告警通知