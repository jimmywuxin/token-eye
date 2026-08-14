# Token Eye — 设计文档

> 本文档描述**当前**架构（SwiftBar 菜单栏插件方案）。早期 Electron/Tauri 方案与演进过程见文末「演进史」。

## 1. 项目定位

macOS 菜单栏 LLM 余额/用量实时监控插件。解决的核心问题：日常使用多个大模型（DeepSeek、MiniMax、MiMo 等），各平台用量查看方式碎片化，需要分别登录开发者平台。

设计目标：

- **零侵入**：不拦截、不修改任何 Agent 的调用方式
- **零常驻**：无后台进程、无 Node.js、无构建步骤
- **零代码加平台**：新增平台只改 `providers.json`，不改脚本

## 2. 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 形态 | SwiftBar 菜单栏插件 | 点开即看、不离开当前工作流；SwiftBar 负责调度与 UI 壳，插件只输出纯文本菜单 |
| 数据获取 | 轮询平台官方 API | Agent 直接调 API，无法请求拦截；轮询覆盖所有调用场景（见 §2.1） |
| 实现语言 | Bash 启动器 + Python 核心 | 单脚本部署、无常驻进程；Python 处理 JSON 解析、并发、Keychain、加密 |
| 配置 | 配置驱动（`providers.json`） | 平台差异全部参数化，加平台零代码 |
| 密钥 | macOS Keychain | 安全；`security` CLI 读取，Key 变更无需重启插件 |
| 部署 | 复制 1 个文件，其余从项目目录读取 | `token-eye.sh` 复制到 `~/SwiftBar/`；`token_eye.py` / `providers.json` / `scripts/` 自动从项目目录加载 |
| 刷新节奏 | 30s 轮询 + 按类型 TTL 缓存 | 实时性与 API 调用成本平衡（余额类 5 分钟缓存，省 90% 调用） |

### 2.1 轮询 vs 代理拦截

早期评估过本地 OpenAI 兼容代理（所有 Agent 改 base_url 指向 localhost，逐请求精确记录）。**不采用**：侵入性强，需改动所有 Agent 配置；而本项目场景下 Agent 替用户调用 API，请求层不可控。轮询虽然拿不到逐请求的 token 明细，但能拿到余额/用量总量，足够覆盖监控诉求。

## 3. 系统架构

```
┌────────────────────────────────────────────────┐
│ SwiftBar（macOS 菜单栏，每 30s 调度一次插件）      │
│  └── ~/SwiftBar/token-eye.sh（Bash 启动器）      │
│        ├─ 检测深浅外观 → 导出配色环境变量          │
│        ├─ 自动定位项目目录（providers.json 所在）  │
│        ├─ 处理 SwiftBar 点击动作（param1）        │
│        └─ 调用 token_eye.py（Python 核心）        │
└──────────────────┬─────────────────────────────┘
                   ▼
        swiftbar/token_eye.py（单进程，并发）
   ┌──────────┬──────────┬──────────┬───────────┐
   │ 缓存读取  │ Keychain │ 并发 API │ 渲染输出   │
   │ /tmp     │ security │ Thread- │ SwiftBar  │
   │ cache    │ CLI      │ Pool    │ 格式菜单   │
   └────┬─────┴────┬─────┴────┬────┴─────┬─────┘
        │          │          │          │
   providers.json  Keychain  各平台 API  历史/趋势
   （配置）        （密钥）   （数据源）  ~/Library/Caches
                                       /token-eye/*.jsonl
```

**一次刷新周期**：

1. 读取 `providers.json`，做运行时 schema 校验（配置错误给出中文菜单提示）
2. 逐 provider 检查 `/tmp/token-eye-cache-{id}.json` 缓存，命中（未过期）则跳过 API
3. 从 Keychain 读取 API Key / Cookie
4. `ThreadPoolExecutor` 并发请求各平台 API（curl，5s 超时）
5. HTTP 错误分类（5xx 服务端 / 4xx 配置鉴权 / 网络失败 / 超时 / 解析失败）
6. 解析响应 → 渲染数据（余额/进度条/状态），balance 类检查告警阈值并统计今日消耗
7. 输出 SwiftBar 格式菜单（含控制台跳转、版本自检）

## 4. 核心模块设计

### 4.1 Parser 类型体系

`providers.json` 里每个 provider 的 `parser.type` 决定数据如何被解析和展示：

| 类型 | 语义 | 展示 |
|------|------|------|
| `balance` | 有余额 API（DeepSeek、MiMo） | 余额数字 + 货币符号 + 趋势线 + 今日消耗估算 |
| `plan_usage` | 有按模型用量 API（MiniMax） | 模型列表 + 进度条 + 双窗口（5h/周）+ 重置倒计时 + 趋势线 |
| `status` | 只验证 Key 有效性 | 自定义标签（可用/免费/…） |

**扩展方式**：新增类型只需在 `parse_provider()` 加分支 + 更新 schema + 加测试；字段路径用 `.` 分隔的嵌套/数组索引（`resolve_field`），适配任意响应结构。`fields` 映射是平台差异的收敛点——**平台响应结构差异全部参数化到配置，不在代码里硬编码**。

### 4.2 缓存与 TTL

- 按 parser 类型默认 TTL：balance 300s / plan_usage 30s / status 60s，`cache` 段全局覆盖，`cacheTtl` 单 provider 覆盖
- **失败请求 10s 短缓存**：连续失败不重复打 API（错误结果也缓存，短 TTL）
- 缓存文件在 `/tmp`（重启即清，天然无残留）；键为 provider id

### 4.3 HTTP 错误分类

5 类错误，各自独立文案与颜色语义：

| 错误 | 含义 | 颜色 | 是否临时 |
|------|------|------|---------|
| `server` (5xx) | 服务端异常 | warn（橙） | 是 |
| `network` | curl 失败/网络不通 | warn | 是 |
| `timeout` | 请求超时 | warn | 是 |
| `client` (4xx) | 配置/鉴权错误（Key 失效、Cookie 过期） | err（紫红） | 否 |
| `parse` | 响应无法解析 | err | 否 |

区分"临时故障"与"配置错误"是关键：前者提示稍后自动恢复，后者引导用户修配置或刷新凭据。

### 4.4 告警

- balance：`alert.minBalance` 余额低于阈值；plan_usage：`alert.minPct` 剩余百分比低于阈值
- **去重**：`token-eye-alerted-{id}.flag` 标记已通知，余额/用量恢复后自动清除并补发一条「已恢复」通知（`token-eye-recovered-{id}.flag` 去重）——阈值边界不会刷屏
- 标记位于 `~/Library/Caches/token-eye/`（持久化，重启不丢，避免重启后重复告警）
- `osascript` 发 macOS 系统通知；`TOKEN_EYE_NOTIFY=0` 可整体禁用

### 4.5 401 自愈（Cookie 平台）

配置 `refreshParam` 的 provider 在鉴权错误时**自动**执行刷新脚本并重试一次，用户无感：

```
401 → 跑 scripts/refresh-mimo-cookie.py → 成功 → 重新取 Key → 重试 API → 恢复
```

- **30 分钟防抖**：`token-eye-autorefresh-{id}.flag` 防止反复触发
- 刷新脚本失败 → 回退菜单手动入口「🔄 刷新 Cookie」
- 刷新脚本支持 **Edge / Chrome / Brave / Arc** 任一已登录浏览器（多配置档探测），第一个拿到完整 Cookie 组合的浏览器胜出
- **经验教训**：浏览器运行中时 Cookie 最新写入在 WAL 伴生文件里，只拷贝主库会拿到过期快照导致误报「缺少 Cookie」——必须连带拷贝 `-wal/-shm/-journal` 并重试（v0.10.0 修复）

### 4.6 历史、趋势与消耗统计

- **存储**：`~/Library/Caches/token-eye/history-{id}.jsonl`，append-only，每行 `时间戳,数值`
- **趋势线**：最近 288 个快照（30s 采样 ≈ 2.4 小时）→ sparkline 均匀降采样到 24 字符宽（`▁▂▃▄▅▆▇█`）+ 窗口首尾绝对值与差值
- **消耗统计**：`consumption_since(cutoff)` 通用窗口函数——按「相邻快照下降量之和」统计任意窗口的消耗（充值抬升不干扰），复用于今日 / 本周 / 本月 / 滚动 24h
- **耗尽预测**：按最近 24h 消耗速率外推「预计可用 ~N 天」（`days_left`）
- **近 7 天柱状图**：按天分桶每日消耗（跨零点下降归后一天），菜单内迷你柱状
- 同一套历史同时服务余额趋势、用量趋势（plan_usage 记 min_pct）、消耗统计与预测

### 4.7 渲染层

- SwiftBar 纯文本协议：`文本 | color=.. size=.. href=.. param1=..`
- **自适应配色**：检测系统深浅外观切换两套色板；全色板按 WCAG AA ≥4.5:1 审计 + 色弱安全（蓝/橙/紫，Wong 色板）
- **状态着色**：菜单栏标题按所有平台最差状态整体变色（任一错误→红，任一告警/缺 Key→橙），异常一眼可见
- **兜底**：渲染全程 try-except，任何异常输出占位菜单，绝不让菜单空白
- **版本自检 + 一键升级**：菜单底部对比 GitHub 最新 release（24h 缓存），有新版本时提示并可一键升级（git 仓库自动 fetch+ff 合并并同步插件；非 git 仓库下载 release 包替换）

### 4.8 配置校验（三层）

| 层 | 实现 | 时机 |
|----|------|------|
| 运行时轻量校验 | `schema_validate()`（必填字段/类型枚举） | 每次刷新，错误显示在菜单 |
| JSON Schema | `schema/providers.schema.json` + 零依赖校验器 `scripts/validate-schema.py` | `make validate` / CI / 编辑器自动补全 |
| 单元测试 | `tests/` 覆盖解析与校验逻辑 | `make test` / CI |

三层互补：运行时校验保护菜单显示，Schema 服务编辑体验与 CI，测试守护回归。

## 5. 质量保障

- **纯函数化核心**：`token_eye.py` 顶层只有常量与函数，`main()` 才读环境变量——解析/告警/分类/缓存全部可独立单测（79 个用例）
- **CI**（GitHub Actions）：bash 语法 + ShellCheck、Python 编译、单元测试、Schema 校验、配色对比度、版本一致性（`bitbar.version` vs `VERSION`）
- **部署模型不变**：无论核心逻辑如何拆分，用户始终只复制 `token-eye.sh` 一个文件

## 6. 已知权衡与边界

- **消耗估算是近似值**：基于余额差值推算，无逐请求明细；DeepSeek 等接口不返回 token 级用量，这是当前模型的上限
- **Cookie 鉴权脆弱**：会话级、依赖浏览器 Safe Storage Key；已支持多浏览器（Edge/Chrome/Brave/Arc），过期仍需重新登录
- **休眠唤醒后的陈旧窗口**：睡眠期间不刷新，唤醒后首个周期可能展示旧缓存（balance TTL 5 分钟）
- **升级路径有 git 依赖**：一键升级的 git 分支要求项目目录是 git 仓库且远端可访问；非 git 仓库走 tarball 替换（仅插件文件，核心逻辑需项目目录同步）

## 7. 演进史

| 版本 | 里程碑 |
|------|--------|
| v0.1 | Electron + menubar 桌面应用（弃用：重、需打包） |
| v0.2 | 迁移 SwiftBar，纯 Shell + Python，零依赖 |
| v0.3 | 配置驱动重构（`providers.json`），加平台零代码 |
| v0.4–0.6 | status/balance/plan_usage 三类 parser、自动探测项目目录 |
| v0.7 | 自适应配色、色弱安全审计、并发拉取、错误分类 |
| v0.8 | 缓存 TTL、告警去重、控制台跳转、MiMo Cookie 鉴权与刷新 |
| v0.9 | 401 自愈、用量告警、余额趋势、schema 校验、版本自检 |
| v0.10 | 质量基建：单元测试（79）/ JSON Schema / CI / Makefile；架构拆分（Python 拆为独立模块）；修复刷新菜单空白与 WAL 误报 |
| 当前 | 当日消耗估算 + 用量趋势线 |

## 8. Roadmap

- ~~菜单栏汇总状态着色~~ ✅（标题按最差状态变色）
- ~~一键升级闭环~~ ✅（版本自检 + git/tarball 两路升级）
- ~~多浏览器 Cookie 支持~~ ✅（Edge/Chrome/Brave/Arc）
- ~~告警恢复通知~~ ✅（回升「已恢复」去重通知）
- ~~调试日志 / 标记持久化 / 货币符号可配置 / 新平台向导~~ ✅
- ~~消耗预测与聚合~~ ✅（预计可用天数 / 周月消耗 / 7 天柱状 / dailySpendMax / daysLeft 告警）
- ~~自检菜单项 / 菜单交互（复制余额、消耗行打开控制台）/ 趋势窗口加长~~ ✅
- **精确用量接入**：若平台开放 token 级用量接口，可补充精确计费（当前为余额差值近似）
- **更多告警维度**：用量下降速率（趋势斜率）告警
