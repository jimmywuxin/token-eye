# Token Eye Android

Mac 版（SwiftBar 菜单栏）的 Android 对应实现：桌面小部件 + 告警通知。

## 架构

| Mac 版 | Android 版 |
|---|---|
| SwiftBar 菜单栏 | Glance 桌面小部件（点按立即刷新） |
| 30s 刷新 | WorkManager 周期刷新（15 分钟，系统下限）+ 手动立即刷新 |
| Keychain | Android Keystore + EncryptedSharedPreferences（`core/SecretStore.kt`） |
| /tmp 缓存 + flag | `snapshot.json`（结果 + 告警去重 + 缓存时间戳） |
| osascript 通知 | NotificationChannel 告警/恢复 |

## 目录

```
android/
├── app/src/main/java/com/coffeelab/tokeneye/
│   ├── core/            # 核心逻辑（移植 token_eye.py）
│   │   ├── Models.kt        # 配置数据类 + 轻量校验
│   │   ├── ConfigLoader.kt  # providers.json 解析（与 Mac 版同 schema）
│   │   ├── JsonPath.kt      # resolve_field 点路径取值
│   │   ├── ResultParser.kt  # balance / plan_usage 解析 + 阈值链
│   │   ├── ApiClient.kt     # HTTP + 错误分类
│   │   ├── SecretStore.kt   # 密钥加密存储
│   │   ├── Repositories.kt  # 配置/快照持久化
│   │   ├── RefreshEngine.kt # 刷新编排 + 告警判定
│   │   └── AlertNotifier.kt # 通知
│   ├── widget/          # Glance 小部件
│   ├── work/            # WorkManager 调度
│   ├── App.kt           # Application：频道创建 + 定时任务
│   └── MainActivity.kt  # Compose 设置页
└── app/src/test/        # 单元测试（ParserTest）
```

## 小部件显示规则

- 只渲染**当前配置内、且已配置密钥**的平台：配几个显示几个，未配置/已移除的不占行
- 在 App 里关掉某平台开关（写回 `providers.json` 的 `enabled`）→ 不再拉取、小部件也不显示
- 错误行压缩为关键词（如「鉴权失败 401」），不展开原始响应
- 默认 **3×1（180×40dp，最小只占 1 格高）**，横竖都可拖动
- **字号固定 13sp，不随尺寸放大**（`ROW_FS`）；行自上而下依次排列，多余空间留在底部
- **只按宽度做降级**：宽度装不下时缩短摘要，最短摘要仍放不下才缩字号（下限 9sp）
  `5h 剩82% · 周 剩45%` → `5h 剩82%` → `82%`
- 标题行在高度 <72dp（1 格）时隐藏；「更新 HH:mm」仅在宽度 ≥210dp 时显示
- 行距按富余高度在 4–12dp 间自适应，不会被撑太开

  实测（DeepSeek `¥12.34` + MiniMax `5h 剩82% · 周 剩45%`）：

  | 小部件尺寸 | 标题 | 字号 | 底部留白 | MiniMax 显示 |
  |---|---|---|---|---|
  | 3×1（180×40dp） | 隐藏 | 13sp | 0 | `5h 剩82%` |
  | 4×1（250×40dp） | 隐藏 | 13sp | 0 | 完整 |
  | 3×2（180×110dp） | 显示 | 13sp | 9dp | `5h 剩82%` |
  | 4×2（250×110dp） | 显示 | 13sp | 9dp | 完整 |
  | 5×2（320×110dp） | 显示 | 13sp | 9dp | 完整 |

  3 格以上高度底部会留白较多——小部件拖到 1–2 格高最合适。
- ⚠️ 已放置的小部件**不会自动套用新的默认尺寸**：想改成 1 格高需要删掉重拖一次（拖大拖小则实时生效）

> **小米 HyperOS 找不到小部件的坑**：桌面「添加小部件」面板默认只列 HyperOS 风格小部件，
> 传统 Android AppWidget 全在列表**最底部的「安卓小部件」入口**里，进去后按 App 名找 Token Eye。

## 已知差异（vs Mac 版）

- **不含 MiMo（已移除）**：MiMo 靠浏览器 Cookie 会话鉴权，`refresh-mimo-cookie.py` 依赖本机浏览器解密，Android 上做不到，只剩「手动反复粘贴 Cookie」一条死路，因此 Android 版直接不做。
  保险机制：凡是配置里带 `refreshParam`（Cookie 自动刷新）的平台，`ConfigLoader` 加载时一律剔除——从 Mac 导入配置或旧配置残留都不会把它们带回来。
- 刷新频率 15 分钟（WorkManager 系统下限），告警实时性略降。
- 历史趋势（sparkline）、每日消耗统计暂未移植，属二期。

## 构建与安装

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

SDK 路径在 `local.properties`（本机 `/opt/homebrew/share/android-commandlinetools`，已 gitignore）。

## 使用

1. 安装后打开 App，在通知权限弹窗点允许
2. 每个平台点「填写密钥」粘贴 API Key
3. 配置默认用内置 providers.json（与仓库根目录同步），剪贴板复制新版配置后点「剪贴板导入配置」可覆盖
4. 桌面添加「Token Eye」小部件，点按即刷新
