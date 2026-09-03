package com.coffeelab.tokeneye.core

import com.google.gson.JsonObject
import com.google.gson.JsonParser

/** providers.json JSON → EyeConfig（字段缺省即用默认值，与 Python 侧宽松解析一致） */
object ConfigLoader {

    fun parse(text: String): EyeConfig {
        val root = JsonParser.parseString(text).asJsonObject
        return fromRoot(root)
    }

    private fun fromRoot(root: JsonObject): EyeConfig {
        val providers = mutableListOf<Provider>()
        val providersArr = root.getAsJsonArray("providers")
        providersArr?.forEach { el ->
            val p = el.asJsonObject
            val apiObj = p.getAsJsonObject("api") ?: return@forEach
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
                barLength = parserObj.get("barLength")?.takeIf { it.isJsonPrimitive }?.asInt ?: 20,
                pctDirection = parserObj.get("pctDirection")?.asString ?: "remaining",
                defaultMinBalance = parserObj.get("defaultMinBalance")?.takeIf { it.isJsonPrimitive }?.asDouble,
                okField = parserObj.get("okField")?.asString ?: "",
                okValue = parserObj.get("okValue")?.asString ?: "",
            )
            val displayObj = p.getAsJsonObject("display")
            val nameColor = displayObj?.get("nameColor")
            val display = DisplaySpec(
                unit = displayObj?.get("unit")?.asString ?: "¥",
                label = displayObj?.get("label")?.asString ?: "余额",
                nameColorDark = when {
                    nameColor?.isJsonObject == true -> nameColor.asJsonObject.get("dark")?.asString
                    nameColor?.isJsonPrimitive == true -> nameColor.asString
                    else -> null
                },
                nameColorLight = nameColor?.takeIf { it.isJsonObject }?.asJsonObject?.get("light")?.asString,
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
                    id = p.get("id")?.asString ?: return@forEach,
                    name = p.get("name")?.asString ?: (p.get("id")?.asString ?: "?"),
                    enabled = p.get("enabled")?.takeIf { it.isJsonPrimitive }?.asBoolean ?: true,
                    refreshParam = p.get("refreshParam")?.takeIf { it.isJsonPrimitive }?.asString,
                    consoleUrl = p.get("consoleUrl")?.asString,
                    api = ApiSpec(
                        url = apiObj.get("url")?.asString ?: return@forEach,
                        method = apiObj.get("method")?.asString ?: "GET",
                        authHeader = apiObj.get("authHeader")?.asString ?: "Authorization",
                        authPrefix = apiObj.get("authPrefix")?.asString ?: "Bearer ",
                        headers = strMap(apiObj.getAsJsonObject("headers")),
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

        // Android 无法从浏览器解密/刷新 Cookie（Mac 版 refresh-mimo-cookie.py 的能力），
        // 这类平台加载即剔除，避免只剩「手动反复粘贴 cookie」这一条死路。
        val supported = providers.filter { it.refreshParam.isNullOrBlank() }

        return EyeConfig(providers = supported, cacheTtl = cacheTtl, alerts = alerts)
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
