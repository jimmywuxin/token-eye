package com.coffeelab.tokeneye.core

import com.google.gson.JsonObject

/** provider 的一项 API 定义（对应 providers.json 的 api 字段） */
data class ApiSpec(
    val url: String,
    val method: String = "GET",
    val authHeader: String = "Authorization",
    val authPrefix: String = "Bearer ",
    val headers: Map<String, String> = emptyMap(),
)

/** parser 定义（balance / plan_usage / status） */
data class ParserSpec(
    val type: String,
    val fields: Map<String, String> = emptyMap(),
    val arrayPath: String = "",
    val showModels: List<String>? = null,
    val modelLabels: Map<String, String> = emptyMap(),
    val windowLabels: Map<String, String> = emptyMap(),
    val barLength: Int = 20,
    val pctDirection: String = "remaining",
    val defaultMinBalance: Double? = null,
    val okField: String = "",
    val okValue: String = "",
)

data class DisplaySpec(
    val unit: String = "¥",
    val label: String = "余额",
    val nameColorDark: String? = null,
    val nameColorLight: String? = null,
    val currencySymbols: Map<String, String> = emptyMap(),
)

data class AlertSpec(
    val minBalance: Double? = null,
    val minPct: Double? = null,
)

data class Provider(
    val id: String,
    val name: String,
    val enabled: Boolean = true,
    /** 非空白 = 依赖浏览器 Cookie 自动刷新（Mac 版的 refreshParam）；Android 不支持，加载时会被过滤掉 */
    val refreshParam: String? = null,
    val consoleUrl: String? = null,
    val api: ApiSpec,
    val parser: ParserSpec,
    val display: DisplaySpec = DisplaySpec(),
    val alert: AlertSpec? = null,
)

/** 全局配置（providers.json 的内存形态） */
data class EyeConfig(
    val providers: List<Provider>,
    val cacheTtl: Map<String, Long> = mapOf("balance" to 300L, "plan_usage" to 30L, "status" to 60L),
    val alerts: Map<String, AlertSpec> = emptyMap(),
)

/** 解析结果状态 */
enum class Status { OK, WARN, ERR, NOKEY }

/** 单个 provider 的一次解析结果 */
data class ProviderResult(
    val id: String,
    val name: String,
    val status: Status,
    /** 小部件/摘要用的单行文本 */
    val summary: String,
    /** 详情页用的多行文本 */
    val details: List<String> = emptyList(),
    val balanceNum: Double? = null,
    val usedPct: Double? = null,
    val consoleUrl: String? = null,
)

/** 持久化快照：最近一次刷新结果 + 告警去重 + 各 provider 上次成功时间（缓存用） */
data class Snapshot(
    val fetchedAt: Long = 0,
    val results: List<ProviderResult> = emptyList(),
    val successAt: Map<String, Long> = emptyMap(),
    val alertedIds: List<String> = emptyList(),
)

/** 简单校验：缺关键字段则报错，供剪贴板导入时反馈 */
fun validateConfigJson(root: JsonObject): String? {
    if (!root.has("providers") || !root.get("providers").isJsonArray) return "缺少 providers 数组"
    val arr = root.getAsJsonArray("providers")
    if (arr.size() == 0) return "providers 为空"
    arr.forEach { el ->
        if (!el.isJsonObject) return "providers 含非对象元素"
        val p = el.asJsonObject
        val id = p.get("id")?.takeIf { it.isJsonPrimitive }?.asString
        if (id.isNullOrBlank()) return "某个 provider 缺少 id"
        val api = p.get("api")?.takeIf { it.isJsonObject }?.asJsonObject
        if (api?.get("url")?.takeIf { it.isJsonPrimitive }?.asString.isNullOrBlank())
            return "provider[$id] 缺少 api.url"
        val parser = p.get("parser")?.takeIf { it.isJsonObject }?.asJsonObject
        val type = parser?.get("type")?.takeIf { it.isJsonPrimitive }?.asString
        if (type !in setOf("balance", "plan_usage", "status"))
            return "provider[$id] parser.type 无效：$type"
    }
    return null
}
