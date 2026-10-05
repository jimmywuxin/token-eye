package com.coffeelab.tokeneye.core

import android.content.Context
import com.google.gson.Gson
import java.io.File

/**
 * 配置来源：**只有** `assets/providers.json`（随 APK 打包，版本与提交一一对应）。
 *
 * 设计说明（2026-10-05 变更，删除此前的 filesDir 覆盖机制）：
 * 旧实现是「filesDir/providers.json（用户剪贴板导入）> assets 内置版」，且 filesDir
 * 一旦存在就**永久遮蔽**内置版、永不过期。实践中它带来两个真实问题：
 * 1. 手机端配置被冻结在导入那一刻，重装 APK 也不更新（今天 Android 节假日期间
 *    峰谷倒计时误判为工作日，根因就是这份遮蔽住的旧配置缺 `peakWindow.holidays`）
 * 2. **不导入也会触发**：启用/停用开关的 `toggleProvider` 同样往 filesDir 写整份配置，
 *    所以「点一次开关」就足以让手机端配置永久停在旧版本
 *
 * 配置改动走 git：改根目录 `providers.json` → 拷到 `assets/` → 重打 APK
 * （有 `scripts/check-config-sync.py` 在 CI 兜底）。手机端不再需要「改配置」入口。
 *
 * 运行时可改的只剩两样，都不涉及配置本体：
 * - API Key：`SecretStore`（Android Keystore）
 * - 启用/停用：`EnabledStore`（只存 `{"id": false}` 这样的极简映射，不存配置本体）
 */
object ConfigRepository {

    /**
     * 读配置：**assets 内置版** + [EnabledStore] 的启用状态覆盖。
     *
     * 覆盖在唯一入口这里叠加，UI 与 RefreshEngine 自动一致，不给「显示是关的、实际还在刷」
     * 留机会。配置本体只有 assets 一份，升级 APK 必然生效。
     */
    fun load(context: Context): EyeConfig {
        val config = ConfigLoader.parse(defaultText(context))
        return applyEnabledOverrides(config, EnabledStore.load(context))
    }

    fun defaultText(context: Context): String =
        context.assets.open("providers.json").bufferedReader().use { it.readText() }

    /**
     * 把 [overrides]（`providerId -> 是否启用`）叠加到配置上。纯函数，供单测覆盖。
     *
     * 抽出来而不是内联在 [load] 里，是为了让「覆盖是否真的生效、是否只影响 enabled
     * 而不碰配置本体」这两件事能在无 Android 环境的单测里验证。
     */
    fun applyEnabledOverrides(config: EyeConfig, overrides: Map<String, Boolean>): EyeConfig {
        if (overrides.isEmpty()) return config
        return config.copy(
            providers = config.providers.map { p ->
                overrides[p.id]?.let { p.copy(enabled = it) } ?: p
            }
        )
    }
}

/**
 * 平台启用/停用的持久化：只记 `providerId -> 是否启用`，**不存配置本体**。
 *
 * 存成极简映射（而非改写整份 providers.json）是刻意的：配置本体永远来自 assets，
 * 启用状态只是一层薄覆盖，改开关不会造成「配置被冻结」。
 */
object EnabledStore {

    private const val FILE = "enabled.json"

    private fun file(context: Context): File = File(context.filesDir, FILE)

    /** 读出覆盖表；文件缺失或损坏时返回空表（全部按配置里的 enabled 走） */
    fun load(context: Context): Map<String, Boolean> {
        val f = file(context)
        if (!f.exists()) return emptyMap()
        return try {
            Gson().fromJson(f.readText(), Map::class.java)
                ?.entries
                ?.mapNotNull { (k, v) -> if (k is String && v is Boolean) k to v else null }
                ?.toMap()
                ?: emptyMap()
        } catch (_: Exception) {
            emptyMap()
        }
    }

    fun set(context: Context, id: String, enabled: Boolean) {
        val map = load(context).toMutableMap()
        // 值为 true 时删掉条目，让「默认值 = 配置里的 enabled」这条规则保持唯一真源
        if (enabled) map.remove(id) else map[id] = false
        try {
            file(context).writeText(Gson().toJson(map))
        } catch (_: Exception) {
            // 写不进去也不影响刷新：本次内存状态已生效，下次启动回到配置默认值
        }
    }
}

/** 快照持久化（对应 Mac 版 /tmp 缓存 + flag 的合并体，存私有目录） */
object SnapshotStore {

    private const val FILE = "snapshot.json"
    private val gson = Gson()

    fun load(context: Context): Snapshot {
        val f = File(context.filesDir, FILE)
        if (!f.exists()) return Snapshot()
        return try {
            gson.fromJson(f.readText(), Snapshot::class.java) ?: Snapshot()
        } catch (e: Exception) {
            Snapshot()
        }
    }

    fun save(context: Context, snapshot: Snapshot) {
        File(context.filesDir, FILE).writeText(gson.toJson(snapshot))
    }
}
