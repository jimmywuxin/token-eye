package com.coffeelab.tokeneye.core

import android.content.Context
import com.google.gson.Gson
import java.io.File

/**
 * 配置来源：
 * 1. filesDir/providers.json（用户导入的覆盖版）
 * 2. assets/providers.json（内置默认）
 */
object ConfigRepository {

    private const val USER_CONFIG = "providers.json"

    fun userConfigFile(context: Context): File = File(context.filesDir, USER_CONFIG)

    fun hasUserConfig(context: Context): Boolean = userConfigFile(context).exists()

    fun load(context: Context): EyeConfig {
        val userFile = userConfigFile(context)
        val text = if (userFile.exists()) userFile.readText() else defaultText(context)
        return ConfigLoader.parse(text)
    }

    fun loadRaw(context: Context): String {
        val userFile = userConfigFile(context)
        return if (userFile.exists()) userFile.readText() else defaultText(context)
    }

    fun saveUserConfig(context: Context, text: String) {
        userConfigFile(context).writeText(text)
    }

    fun clearUserConfig(context: Context) {
        userConfigFile(context).delete()
    }

    fun defaultText(context: Context): String =
        context.assets.open("providers.json").bufferedReader().use { it.readText() }
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
