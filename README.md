# Token Eye

macOS 菜单栏 LLM Token 用量实时监控工具。

一个常驻在菜单栏的小工具，轮询各 LLM 平台 API，点击即可查看 DeepSeek、MiniMax 等平台的余额和用量。

## 功能

- 🔍 菜单栏常驻，点击即看，不占 Dock 位
- 📊 DeepSeek 余额监控（¥）
- 📊 MiniMax 用量监控（M2.7 模型剩余次数 + 重置倒计时）
- 🔑 所有 API Key 统一从 macOS Keychain 读取，变更无需重启
- ⚙️ 配置驱动 — 添加新平台只需编辑 `providers.json`，零代码
- 🔄 60 秒自动轮询，打开面板时自动刷新
- 🌙 暗色主题

## 快速开始

### 1. 安装依赖

```bash
npm install --legacy-peer-deps
```

### 2. 添加 API Key 到 Keychain

```bash
# DeepSeek
security add-generic-password -s "DEEPSEEK_API_KEY" -a "" -w "sk-你的key"

# MiniMax
security add-generic-password -s "MINIMAX_CN_API_KEY" -a "" -w "你的key"
```

### 3. 运行

```bash
# 开发模式（需要先构建前端）
npm run build && npx electron .
```

### 4. 构建打包

```bash
npm run pack
```

打包产物在 `release/` 目录。

## 添加新平台

编辑 `providers.json`，追加一段配置即可：

```json
{
  "id": "your-provider",
  "name": "Your Provider",
  "keychainService": "YOUR_API_KEY",
  "api": {
    "url": "https://api.example.com/v1/usage",
    "method": "GET",
    "authHeader": "Authorization",
    "authPrefix": "Bearer "
  },
  "parser": {
    "type": "balance",
    "fields": {
      "balance": "balance",
      "spent": "total_spent",
      "currency": "currency"
    }
  },
  "display": { "unit": "$", "label": "余额" }
}
```

支持三种 parser 类型：
- `balance` — 单值展示（余额、已用金额）
- `plan_usage` — 列表展示（多模型剩余次数 + 进度条 + 倒计时）
- `raw` — 原样展示 JSON

## 技术栈

- **Electron** + [menubar](https://github.com/maxogden/menubar) — macOS 菜单栏
- **React** + **TypeScript** — 前端面板
- **Vite** — 构建工具
- **macOS Keychain** — API Key 安全存储

## 项目结构

```
electron/
  main.ts             # Electron 主进程 + menubar
  keychain.ts         # macOS Keychain 读取
  provider-engine.ts  # 通用 Provider 引擎
  poller.ts           # 轮询调度器
  preload.ts          # IPC 桥接
src/
  App.tsx             # 主组件
  components/
    ProviderCard.tsx  # 平台用量卡片
    StatusBar.tsx     # 顶部状态栏
providers.json       # Provider 配置文件（核心扩展点）
```

## License

MIT
