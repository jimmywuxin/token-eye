# 智谱 / 千问 费用与额度查询入口调研

> 调研日期：2026-10-07　目的：为 token-eye 增加 `zhipu`、`qwen` 两个 provider 找到可用的数据源。
> 结论先行：**两家都分成「按量付费余额」和「Coding Plan 订阅额度」两条完全不同的链路**，token-eye 现在模板库里那两个 `status` 型（只验 API 通不通）都应该升级。

---

## 一、智谱 AI（BigModel / 智谱清言）

智谱有两套互不相干的凭证，**不要混**：

| 链路 | 凭证 | 用途 |
|------|------|------|
| 按量付费 | 普通 API Key（`{id}.secret` 那种） | 查账户余额 |
| Coding Plan | 套餐专用 Key / 控制台 JWT | 查 5 小时 + 周额度 |

### 1.1 账户余额（balance 型，推荐给 token-eye）

```
GET https://www.bigmodel.cn/api/biz/account/query-customer-account-report
Authorization: {api_key}          ← 注意：不带 "Bearer " 前缀
Content-Type: application/json
```

响应字段（社区实测，来源 linux.do/t/topic/1049783）：

```json
{
  "balance": {          // 根节点即 balance 对象
    "balance": 0,            // 当前余额
    "rechargeAmount": 0,     // 累计充值
    "giveAmount": 0,         // 赠送金额
    "totalSpendAmount": 0,   // 累计消费
    "frozenBalance": 0,      // 冻结余额
    "availableBalance": 0    // 可用余额 ← 告警阈值应该用这个
  }
}
```

- 官方文档里**没有**这个接口，属于官网前端在用的内部接口，但稳定可调。
- token-eye 映射建议：`parser.type=balance`，`fields.balance="balance.availableBalance"`。
- 告警：`alert.minBalance` 用 `availableBalance` 对比，跟 DeepSeek 一个路子。

### 1.2 Coding Plan 额度（plan_usage 型）

```
GET https://bigmodel.cn/api/monitor/usage/quota/limit          # 国内
GET https://api.z.ai/api/monitor/usage/quota/limit             # 国际站
Authorization: {api_key}
Content-Type: application/json
```

**这个接口 token-eye 的 `plan_usage` parser 基本可以直接套**，MiniMax 就是同一类结构：

```json
{
  "code": 200, "msg": "success", "success": true,
  "data": {
    "limits": [
      { "type": "TOKENS_LIMIT", "usage": 10000000, "currentValue": 500000,
        "percentage": 5, "nextResetTime": 1706200000000 },
      { "type": "TIME_LIMIT",  "usage": 100, "currentValue": 10, "percentage": 10 }
    ]
  }
}
```

| type | 含义 |
|------|------|
| `TOKENS_LIMIT` | 周 Token 配额 |
| `TIME_LIMIT` | 5 小时窗口 / MCP 搜索次数（月度） |

- 数组在 `data.limits`，`arrayPath: "data.limits"`，按 `type` 区分两窗（token-eye 现有 `plan_usage` 只有 interval/weekly 二窗，正好对上 TIME_LIMIT/TOKENS_LIMIT）。
- `percentage` 是**已用百分比**，方向跟 `alert.minPct` 一致。
- ⚠️ **坑**：如果只用普通按量付费 Key 打这个接口，可能返回 401/空 limits。用 Coding Plan 的 Key。
- ⚠️ token-watch 的做法是用**控制台 JWT**（浏览器 F12 从 `bigmodel.cn/coding-plan/personal/usage` 抓 `authorization` 头）+ `bigmodel-organization` + `bigmodel-project` 两个头。API Key 能不能单独打通，**待实测**。

### 1.3 控制台入口

- 用量 / Coding Plan 用量：`https://bigmodel.cn/coding-plan/personal/usage`
- API Key 管理：`https://open.bigmodel.cn/usercenter/apikeys`

---

## 二、千问 / 通义（阿里云百炼 Model Studio）

同样两条链路，而且**坑比智谱多**。

### 2.1 按量付费 · 免费额度（balance 型）

```
GET https://dashscope.aliyuncs.com/api/v1/usage
X-DashScope-Access-Token: {api_key}      ← 或 Authorization: Bearer，两种都有人用
```

| 要点 | 说明 |
|------|------|
| **权限** | Key 必须勾选 `dashscope:usage:read`，只勾 `text-generation:call` 会一直 403 |
| **限流** | **每天只允许调 100 次**，不计入模型调用配额 |
| **风控** | 社区实测有人因查询过频被临时冻结 24 小时，务必设长缓存（token-eye 的 `cacheTtl` 给 3600） |
| 地域 | 走 `dashscope.aliyuncs.com` 的是中国内地北京地域 |

⚠️ 网上还流传两个路径，可信度较低，**落地前必须实测**：
- `https://dashscope.aliyuncs.com/api/v1/account/quota` → `{remaining_free_quota, used_paid_quota}`（仅见于 CSDN 博客）
- `https://dashscope.aliyuncs.com/compatible-mode/v1/models/quota`（仅见于 developer.aliyun.com 社区文章）

### 2.2 Coding Plan 额度（plan_usage 型）— 只能走控制台 RPC

**没有稳定的公开 REST API**。目前能用的是百炼控制台自己的 RPC：

```
POST https://bailian.console.aliyun.com/data/api.json?action=zeldaEasy.broadscope-bailian.codingPlan.queryCodingPlanInstanceInfoV2&product=broadscope-bailian&api=queryCodingPlanInstanceInfoV2
# 国际站把 host 换成 modelstudio.console.alibabacloud.com

Authorization: Bearer {api_key}
x-api-key: {api_key}
X-DashScope-API-Key: {api_key}
Content-Type: application/json
Accept: application/json
```

响应里 `codingPlanInstanceInfos[].codingPlanQuotaInfo`：

| 字段 | 窗口 |
|------|------|
| `per5HourUsedQuota` / `per5HourTotalQuota` / `per5HourQuotaNextRefreshTime` | 5 小时（primary） |
| `perWeekUsedQuota` / `perWeekTotalQuota` / `perWeekQuotaNextRefreshTime` | 周（secondary） |
| `perBillMonthUsedQuota` / `perBillMonthTotalQuota` / `perBillMonthQuotaNextRefreshTime` | 订阅月（tertiary） |

- 套餐额度：Pro ¥200/月，6000 次 / 5 小时、45000 次 / 周、90000 次 / 月。Lite 已停售。
- 计划名：`codingPlanInstanceInfos[].planName` / `instanceName` / `packageName`。

**已知限制（CodexBar 项目的实测结论）**：
- 部分中国内地账号即使配了 API Key，这个 RPC 仍返回 `ConsoleNeedLogin` → **必须走浏览器 cookie 模式**。
- 这不是稳定公开 API，阿里可能随时改。

### 2.3 官方 CLI（最省事的第三条路）

百炼官方提供 `bl` CLI，能直接查全部额度，**比自己扒接口稳**：

```bash
bl usage coding-plan      # 5 小时 / 周 / 月 用量
bl usage free             # 免费额度
bl usage stats            # 模型用量统计
bl usage summary          # 统一概览
bl usage token-plan       # Token Plan 用量
bl quota list             # RPM/TPM 限流
```

- 文档：`https://help.aliyun.com/zh/model-studio/cli/usage-quota`
- 可以让 token-eye 在 `qwen` provider 上加个 `command` 型的 fallback，或者干脆做成一个外部脚本由 token-eye 调。

### 2.4 控制台入口

- 模型用量 / 免费额度：`https://bailian.console.aliyun.com/` → 模型用量 → 免费额度页签
- Coding Plan 套餐页：`https://bailian.console.aliyun.com/cn-beijing/?tab=model#/efm/coding_plan`
- 限流控制台：`<WorkspaceId>.cn-beijing.maas.aliyuncs.com/api/v1/quotas`（**这个是官方公开的**，但只返回 QPS/RPM/TPM 限流，不返回费用）

---

## 三、结论：token-eye 该怎么做

| 平台 | 链路 | parser.type | 成熟度 |
|------|------|-------------|--------|
| 智谱 | 账户余额 | `balance` | 🟢 可直接落地，字段明确 |
| 智谱 | Coding Plan | `plan_usage` | 🟡 接口对得上，鉴权方式待实测 |
| 千问 | 免费额度 | `balance` | 🟡 路径待实测 + 100 次/天硬限流 |
| 千问 | Coding Plan | `plan_usage` | 🔴 只有控制台 RPC，Cookie 会过期，风控风险高 |

**建议路线**：
1. **先做智谱余额**（`balance.availableBalance`）——最稳，字段清楚，无 Cookie，无风控。
2. **再做智谱 Coding Plan**——结构跟 MiniMax 同构，parser 几乎不用改。
3. **千问优先走 `bl` CLI**，别硬扒接口；如果要做成 provider，用 `command` 方式调 CLI 比维护 Cookie 靠谱。
4. 千问的 `dashscope:usage:read` 权限和 100 次/天限制意味着 **token-eye 的 `cacheTtl` 至少给 3600 秒**，绝不能按 balance 默认的 300 秒。

---

## 四、待办

- [ ] 实测智谱两个接口（需要真实 Key）
- [ ] 确认 `Authorization` 是否要带 `Bearer ` 前缀（社区两种都有）
- [ ] 实测千问 `api/v1/usage` 三个候选路径
- [ ] 评估 `bl` CLI 是否已装；没装则给安装脚本
- [ ] 落地时记得同步 Android 副本 `android/app/src/main/assets/providers.json`
- [ ] 用 `scripts/add-provider.py` 或模板库加，别手改 providers.json
