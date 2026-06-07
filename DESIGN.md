# Token Eye — 设计文档

> ⚠️ **注意**：本文档反映的是早期 Tauri/Web 方案的设计思路，当前已迁移到 SwiftBar 菜单栏插件方案（见 README.md）。保留本文档供参考。

> 多模型 LLM Token 消耗实时监控桌面仪表盘

## 项目背景

日常使用多个大模型（DeepSeek、MiMo、MiniMax），通过不同 Agent（Codex、OpenClaw、Hermes Agent）调用。目前各平台的用量查看方式碎片化，需要一个统一的桌面窗口实时展示所有模型的消耗情况。

## 当前使用现状

| 模型 | 调用方式 | 当前查看方式 |
|------|---------|------------|
| DeepSeek | Agent (codex/openclaw/hermes) | 登录开发者平台 |
| MiMo | Agent | 登录开发者平台 |
| MiniMax | Agent + 脚本 | API 查 plan 用量 (`check_usage.py`) |

**关键约束**：不是直接调 API，而是 Agent 替用户调用。因此不适合请求拦截，应采用**轮询平台 API** 的方式。

## 参考项目：DeepSeek Reasonix

**项目地址**：https://github.com/esengine/deepseek-reasonix

Reasonix 的核心做法值得借鉴：

### 1. 客户端拦截 + JSONL 日志
- 从 API 响应的 `usage` 字段提取 token 数
- 追加写入 `~/.reasonix/usage.jsonl`（append-only，不阻塞主流程）
- 超过 5MB 自动压缩，保留 365 天

### 2. 本地定价表计算费用
```typescript
// 内置定价（USD per 1M tokens）
const DEEPSEEK_PRICING = {
  "deepseek-v4-flash": { inputCacheHit: 0.0028, inputCacheMiss: 0.14, output: 0.28 },
  "deepseek-v4-pro":   { inputCacheHit: 0.003625, inputCacheMiss: 0.435, output: 0.87 },
};

// 费用公式
cost = (hitTokens × hitPrice + missTokens × missPrice + completionTokens × outputPrice) / 1,000,000
```

### 3. 缓存诊断（SHA-256 哈希对比）
- 每轮对话计算 system prompt、tool specs、few-shots 的哈希
- 与上一轮对比，推断缓存未命中原因（system-prompt-changed / tool-list-changed / cold-start 等）
- DeepSeek 本身不提供此信息，是 Reasonix 自己推断的

### 4. 滚动窗口聚合统计
- today / 7d / 30d / all-time
- 按 model、按 session 分组
- 子代理（subagent）单独归因

### 5. 内嵌 Web Dashboard
- Tauri 桌面应用，内嵌 React 前端
- 实时展示费用、缓存命中率、趋势图

## 架构设计

### 方案：轮询 API（推荐）

```
┌─────────────────────────────────────────────────┐
│           Desktop Dashboard (Tauri/Web)          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │ DeepSeek │ │  MiMo   │ │ MiniMax │  ...更多   │
│  │ $12.34  │ │  ¥5.67  │ │ 50/100  │           │
│  │ ▃▅▇▆▅▇ │ │ ▂▃▅▄▅▆ │ │ ██████░ │           │
│  └─────────┘ └─────────┘ └─────────┘           │
│           ← 每 30s 自动刷新 →                    │
└──────────────────┬──────────────────────────────┘
                   │ HTTP 轮询
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
 Provider A    Provider B    Provider C
 (定时抓取)    (定时抓取)    (定时抓取)
```

**选择理由**：不侵入 Agent 工作流，覆盖所有使用场景。

### 备选：本地代理拦截
- 在 `localhost` 起 OpenAI 兼容代理，所有 Agent 改用代理地址
- 优点：逐请求精确记录
- 缺点：需要改所有 Agent 的 base_url，侵入性强
- **暂不采用**

## 各平台 API 可用性

| 平台 | API 查询方式 | 能拿到什么 |
|------|------------|----------|
| DeepSeek | `GET /v1/user/balance` | 余额、已用金额、token 数 |
| MiMo | 待确认是否有 billing API | 可能需要走 OpenAI 兼容格式 |
| MiniMax | ✅ 已有 `check_usage.py` | 模型维度的 plan 用量/剩余/重置倒计时 |

### MiniMax 现有脚本
路径：`/Users/wuxin/.openclaw/workspace/skills/minimax-plan-usage/scripts/check_usage.py`
- 调用 `GET /v1/api/openplatform/coding_plan/remains`
- 从 macOS Keychain 读取 API Key
- 返回各模型的总次数、剩余次数、重置倒计时

## 桌面窗口方案

用户选择：**桌面动态窗口，实时显示**

可选方案：
- **浏览器页面**（最简单，HTML 文件，浏览器开着就能看）
- **Tauri 桌面应用**（原生窗口，像 Reasonix 那样）
- **菜单栏小工具**（macOS 菜单栏常驻，点开看详情）

## 待确认事项

- [ ] DeepSeek 和 MiMo 的 API Key 存放位置（Keychain / 环境变量 / 配置文件）
- [ ] MiMo 是否有 billing/balance API
- [ ] 桌面窗口最终形式（Tauri / 浏览器 / 菜单栏）
- [ ] 各平台定价表维护方式（硬编码 vs 配置文件）

## 技术栈（初步建议）

- **后端**：Python（与现有 check_usage.py 一致）
- **前端**：React + Tailwind（或更轻量的方案）
- **桌面**：Tauri / 或纯 Web 方案
- **存储**：SQLite（持久化）+ JSONL（日志）
- **调度**：定时轮询，间隔 30s~60s
