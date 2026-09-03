package com.coffeelab.tokeneye.core

import com.google.gson.JsonElement

/**
 * 点路径取值，移植自 token_eye.py 的 resolve_field：
 * "balance_infos.0.total_balance" — 数字段落在数组上取索引，其余在对象上取 key。
 */
fun resolveField(obj: JsonElement?, path: String?): JsonElement? {
    if (obj == null || obj.isJsonNull || path.isNullOrBlank()) return null
    var cur: JsonElement = obj
    for (part in path.split('.')) {
        if (cur.isJsonNull) return null
        if (cur.isJsonArray) {
            val idx = part.toIntOrNull() ?: return null
            val arr = cur.asJsonArray
            if (idx < 0 || idx >= arr.size()) return null
            cur = arr[idx]
        } else if (cur.isJsonObject) {
            val next = cur.asJsonObject.get(part) ?: return null
            cur = next
        } else {
            return null
        }
        if (cur.isJsonNull) return null
    }
    return cur
}

fun JsonElement?.asStringOrNull(): String? {
    if (this == null || !isJsonPrimitive) return null
    return try { asJsonPrimitive.asString } catch (e: Exception) { null }
}

fun JsonElement?.asDoubleOrNull(): Double? {
    if (this == null || !isJsonPrimitive) return null
    return try { asJsonPrimitive.asDouble } catch (e: Exception) { null }
}

fun JsonElement?.asBoolOrNull(): Boolean? {
    if (this == null || !isJsonPrimitive) return null
    return try { asJsonPrimitive.asBoolean } catch (e: Exception) { null }
}
