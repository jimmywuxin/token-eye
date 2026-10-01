package com.coffeelab.tokeneye.core

import android.content.Context
import com.google.gson.JsonParser

/**
 * 中国法定节假日 / 调休表 — 镜像 swiftbar/parsers/peak_window.py 的 load_holidays()。
 *
 * 数据源同 Mac 版：`assets/holidays/<年>.json`（源自 NateScarlet/holiday-cn，逐条对照 gov.cn 公告）。
 * 字段语义：`isOffDay=true` 法定节假日/调休放假 → 空闲；`false` 调休上班的周末 → 按工作日算。
 *
 * 更新方式：在项目根跑 `make holidays` 后，把 holidays 目录下的全部 .json 拷到
 * `android/app/src/main/assets/holidays/`（Android 侧只读 assets，不联网）。
 * 资源缺失/损坏时返回空表 → 自动退化为纯 weekdays 判定，不影响余额显示。
 */
object HolidayTable {

    @Volatile
    private var cache: Map<String, Boolean>? = null

    /** 读取 assets/holidays/ 下的全部年份文件并合并（进程内缓存）。失败返回空表。 */
    fun load(context: Context): Map<String, Boolean> {
        cache?.let { return it }
        val merged = mutableMapOf<String, Boolean>()
        try {
            for (name in context.assets.list("holidays").orEmpty()) {
                if (!name.endsWith(".json")) continue
                val text = context.assets.open("holidays/$name").bufferedReader().use { it.readText() }
                merged.putAll(parse(text))
            }
        } catch (_: Exception) {
            // 资源缺失/损坏 → 退化为纯 weekdays 判定
        }
        cache = merged
        return merged
    }

    /**
     * 纯解析（可单测，不依赖 Context）。
     *
     * 输入形如 `{"year":2026,"days":[{"date":"2026-10-01","isOffDay":true}, ...]}`
     * 输出 `{"2026-10-01": true, ...}`（值为「是否放假」）。
     */
    fun parse(json: String): Map<String, Boolean> {
        val out = mutableMapOf<String, Boolean>()
        try {
            val root = JsonParser.parseString(json)
            if (!root.isJsonObject) return out
            val days = root.asJsonObject.getAsJsonArray("days") ?: return out
            for (el in days) {
                if (!el.isJsonObject) continue
                val o = el.asJsonObject
                val date = o.get("date")?.takeIf { it.isJsonPrimitive }?.asString ?: continue
                if (date.length != 10) continue  // 只收 YYYY-MM-DD
                val off = o.get("isOffDay")?.takeIf { it.isJsonPrimitive }?.asBoolean ?: false
                out[date] = off
            }
        } catch (_: Exception) {
            return out
        }
        return out
    }
}
