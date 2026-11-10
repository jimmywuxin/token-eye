package com.coffeelab.tokeneye.core

import android.util.Log
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/** providers.json JSON → EyeConfig（字段缺省即用默认值，与 Python 侧宽松解析一致） */
object ConfigLoader {

    /**
     * 与 scripts/check-config-sync.py 的 `ANDROID_EXCLUDED = {"mimo","qwen"}` 显式常量对齐：
     * 按 **id** 白名单剔除，不按 refreshParam / parser.type 动态豁免，
     * 这样新增或误改的平台不会被静默视为「Android 理应没有」。
     */
    private val ANDROID_EXCLUDED = setOf("mimo", "qwen")

    fun parse(text: String): EyeConfig {
        val root = JsonParser.parseString(text).asJsonObject
        return fromRoot(root)
    }

    private fun fromRoot(root: JsonObject): EyeConfig {
        val providers = mutableListOf<Provider>()
        val providersArr = root.getAsJsonArray("providers")
        providersArr?.forEach { el ->
            val p = el.asJsonObject
            val id = p.get("id")?.asString ?: return@forEach
            val pType = p.getAsJsonObject("parser")?.get("type")
                ?.takeIf { it.isJsonPrimitive }?.asString
            val pRefresh = p.get("refreshParam")?.takeIf { it.isJsonPrimitive }?.asString
            // 与 scripts/check-config-sync.py 的显式 id 白名单对齐：先按 id 剔除；
            // 再对 refreshParam（浏览器 Cookie）/ command（本机 CLI）两类不支持类型做
            // 运行时防御性过滤并留可观测日志。两层护栏互补，避免新平台被静默跳过。
            val excludedById = id in ANDROID_EXCLUDED
            val unsupportedType = pType == "command" || !pRefresh.isNullOrBlank()
            if (excludedById || unsupportedType) {
                warnUnsupported(id, pType, !pRefresh.isNullOrBlank(), excludedById)
                return@forEach
            }
            val apiObj = p.getAsJsonObject("api") ?: run {
                // 白名单外平台缺 api 段也是配置异常，留痕而不是静默消失
                warnMissingApi(id)
                return@forEach
            }
            val parserObj = p.getAsJsonObject("parser") ?: return@forEach
            val parser = ParserSpec(
                type = parserObj.get("type")?.asString ?: return@forEach,
                fields = strMap(parserObj.getAsJsonObject("fields")),
                arrayPath = parserObj.get("arrayPath")?.asString ?: "",
                showModels = parserObj.get("showModels")?.takeIf { it.isJsonArray }
                    ?.asJsonArray?.mapNotNull { it.takeIf { e -> e.isJsonPrimitive }?.asString },
                modelLabels = strMap(parserObj.getAsJsonObject("modelLabels")),
                windowLabels = strMap(parserObj.getAsJsonObject("windowLabels"))
                    .ifEmpty { mapOf("interval" to "5h", "weekly" to "7d") },
                pctDirection = parserObj.get("pctDirection")?.asString ?: "remaining",
                defaultMinBalance = parserObj.get("defaultMinBalance")?.takeIf { it.isJsonPrimitive }?.asDouble,
                okField = parserObj.get("okField")?.asString ?: "",
                okValue = parserObj.get("okValue")?.asString ?: "",
                peakWindow = parserObj.getAsJsonObject("peakWindow")?.let { pw ->
                    val hoursArr = pw.getAsJsonArray("hours")
                    val hours = hoursArr?.mapNotNull { el ->
                        if (!el.isJsonArray) return@mapNotNull null
                        val pair = el.asJsonArray
                        if (pair.size() < 2) return@mapNotNull null
                        val s = pair[0].takeIf { it.isJsonPrimitive }?.asInt ?: return@mapNotNull null
                        val e = pair[1].takeIf { it.isJsonPrimitive }?.asInt ?: return@mapNotNull null
                        if (s !in 0..23 || e !in 1..24 || s >= e) return@mapNotNull null
                        s until e
                    } ?: emptyList()
                    val weekdaysArr = pw.getAsJsonArray("weekdays")
                    val weekdays = weekdaysArr?.mapNotNull { it.asIntOrNull() }
                        ?.filter { it in 1..7 }
                        ?.ifEmpty { null }
                        ?: listOf(1, 2, 3, 4, 5)
                    PeakWindowSpec(
                        tz = pw.get("tz")?.asString ?: "Asia/Shanghai",
                        weekdays = weekdays,
                        hours = hours,
                        peakLabel = pw.get("peakLabel")?.asString ?: "⚡高峰",
                        offPeakLabel = pw.get("offPeakLabel")?.asString ?: "🌙空闲",
                        holidays = pw.get("holidays")?.takeIf { it.isJsonPrimitive }?.asBoolean ?: false,
                    )
                },
            )
            val displayObj = p.getAsJsonObject("display")
            val display = DisplaySpec(
                label = displayObj?.get("label")?.asString ?: "余额",
                currencySymbols = strMap(displayObj?.getAsJsonObject("currencySymbols")),
            )
            val alertSpec = p.getAsJsonObject("alert")?.let { a ->
                AlertSpec(
                    minBalance = a.get("minBalance")?.takeIf { it.isJsonPrimitive }?.asDouble,
                    minPct = a.get("minPct")?.takeIf { it.isJsonPrimitive }?.asDouble,
                )
            }
            providers.add(
                Provider(
                    id = id,
                    name = p.get("name")?.asString ?: id,
                    enabled = p.get("enabled")?.takeIf { it.isJsonPrimitive }?.asBoolean ?: true,
                    refreshParam = p.get("refreshParam")?.takeIf { it.isJsonPrimitive }?.asString,
                    consoleUrl = p.get("consoleUrl")?.asString,
                    api = ApiSpec(
                        url = apiObj.get("url")?.asString ?: return@forEach,
                        method = apiObj.get("method")?.asString ?: "GET",
                        authHeader = apiObj.get("authHeader")?.asString ?: "Authorization",
                        authPrefix = apiObj.get("authPrefix")?.asString ?: "Bearer ",
                        headers = strMap(apiObj.getAsJsonObject("headers")),
                        envelope = apiObj.getAsJsonObject("envelope")?.let { env ->
                            EnvelopeSpec(
                                codePath = env.get("codePath")?.asString ?: "code",
                                okCodes = env.getAsJsonArray("okCodes")
                                    ?.mapNotNull { it.takeIf { e -> e.isJsonPrimitive }?.asString }
                                    ?.ifEmpty { null }
                                    ?: listOf("200"),
                                msgPath = env.get("msgPath")?.asString ?: "msg",
                            )
                        },
                    ),
                    parser = parser,
                    display = display,
                    alert = alertSpec,
                )
            )
        }

        val cacheTtl = mutableMapOf("balance" to 300L, "plan_usage" to 30L, "status" to 60L)
        root.getAsJsonObject("cache")?.entrySet()?.forEach { (k, v) ->
            (v.asLongOrNullIfPrimitive())?.let { cacheTtl[k] = it }
        }

        val alerts = mutableMapOf<String, AlertSpec>()
        root.getAsJsonObject("alerts")?.entrySet()?.forEach { (k, v) ->
            if (v.isJsonObject) {
                alerts[k] = AlertSpec(
                    minBalance = v.asJsonObject.get("minBalance")?.takeIf { it.isJsonPrimitive }?.asDouble,
                    minPct = v.asJsonObject.get("minPct")?.takeIf { it.isJsonPrimitive }?.asDouble,
                )
            }
        }

        // 解析阶段已按「显式 id 白名单 + 不支持类型」两层口径剔除并留日志；此处再兜底
        // 过滤一次，避免配置层漏网把它们带进刷新流程。
        val supported = providers.filter {
            it.id !in ANDROID_EXCLUDED &&
                it.refreshParam.isNullOrBlank() &&
                it.parser.type != "command"
        }

        return EyeConfig(providers = supported, cacheTtl = cacheTtl, alerts = alerts)
    }

    /** 不支持类型的可观测日志：只记 id / 剔除原因，不含 URL、Key 等敏感值。
     *  纯 JVM 单测里 android.util.Log 是 stub（会抛），用 runCatching 兜住，真机正常输出。 */
    private fun warnUnsupported(
        id: String,
        type: String?,
        hasRefreshParam: Boolean,
        excludedById: Boolean,
    ) {
        val reason = when {
            excludedById -> "ANDROID_EXCLUDED(id)"
            hasRefreshParam -> "refreshParam"
            type == "command" -> "command"
            else -> type ?: "unknown"
        }
        runCatching { Log.w("TokenEye", "skip unsupported provider id=$id reason=$reason") }
    }

    private fun warnMissingApi(id: String) {
        runCatching { Log.w("TokenEye", "skip provider without api section id=$id") }
    }

    private fun strMap(obj: JsonObject?): Map<String, String> {
        if (obj == null) return emptyMap()
        val out = mutableMapOf<String, String>()
        obj.entrySet().forEach { (k, v) ->
            if (v.isJsonPrimitive) out[k] = v.asString
        }
        return out
    }

    private fun com.google.gson.JsonElement.asLongOrNullIfPrimitive(): Long? =
        if (isJsonPrimitive) try { asLong } catch (e: Exception) { null } else null
}
