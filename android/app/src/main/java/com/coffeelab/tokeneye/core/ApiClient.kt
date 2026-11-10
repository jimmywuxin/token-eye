package com.coffeelab.tokeneye.core

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.URI
import java.util.concurrent.TimeUnit

enum class ErrorKind { SERVER, AUTH, HTTP, TIMEOUT, NETWORK, PARSE, CONFIG }

data class FetchResult(
    val data: JsonObject? = null,
    val errorKind: ErrorKind? = null,
    val message: String = "",
) {
    val ok: Boolean get() = errorKind == null && data != null
}

/** HTTP 调用 + 错误分类（对齐 token_eye.py classify_response） */
object ApiClient {

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    suspend fun fetch(
        url: String,
        method: String,
        authHeader: String,
        authPrefix: String,
        key: String,
        extraHeaders: Map<String, String> = emptyMap(),
        envelope: EnvelopeSpec? = null,
    ): FetchResult = withContext(Dispatchers.IO) {
        // URL 合法性单独归类为 CONFIG（配置错误），且在构造 Request 前校验：
        // OkHttp 对非法地址会抛 IllegalArgumentException，原先在 try 之外会直接冲出。
        val uri = runCatching { URI(url) }.getOrNull()
        val scheme = uri?.scheme?.lowercase()
        if (uri == null || uri.host.isNullOrBlank() || (scheme != "http" && scheme != "https")) {
            return@withContext FetchResult(errorKind = ErrorKind.CONFIG, message = "接口地址配置无效")
        }
        try {
            val builder = Request.Builder().url(url)
            if (key.isNotBlank()) builder.header(authHeader, authPrefix + key)
            extraHeaders.forEach { (k, v) -> builder.header(k, v) }
            when (method.uppercase()) {
                "POST" -> builder.post("".toRequestBody())
                "PUT" -> builder.put("".toRequestBody())
                else -> builder.get()
            }
            client.newCall(builder.build()).execute().use { resp ->
                val body = resp.body?.string() ?: ""
                if (!resp.isSuccessful) {
                    val kind = when {
                        resp.code >= 500 -> ErrorKind.SERVER
                        resp.code == 401 || resp.code == 403 -> ErrorKind.AUTH
                        else -> ErrorKind.HTTP
                    }
                    FetchResult(errorKind = kind, message = "HTTP ${resp.code}")
                } else {
                    parseResponse(body, envelope)
                }
            }
        } catch (e: SocketTimeoutException) {
            FetchResult(errorKind = ErrorKind.TIMEOUT, message = "请求超时")
        } catch (e: IOException) {
            // 对外文案固定：e.message 可能含 URL / 内网地址 / 响应片段，不能直接进 UI
            FetchResult(errorKind = ErrorKind.NETWORK, message = "网络连接失败")
        } catch (e: Exception) {
            FetchResult(errorKind = ErrorKind.NETWORK, message = "请求失败")
        }
    }

}

/**
 * 业务码校验（纯函数，对齐 token_eye.py 的 apply_envelope）。
 * 返回 null 表示通过；非 null 为错误文案。
 *
 * 口径与 Mac 侧 apply_envelope（:243 `str(code)` 参与比较）统一：
 * - code 字段不存在 / 为 JsonNull → 放行（未配 envelope 结构或字段缺失）
 * - code 为字符串或数字 primitive → 取文本与 okCodes 比较（数字 200 也按 "200" 命中）
 * - code 为 JsonObject / JsonArray 等畸形结构 → 取 JSON 文本，不可能命中 okCodes →
 *   视为校验失败（绝不 asStringOrNull() 返回 null 后静默放行）
 * - msg 为空串 / 全空白 → 回退「业务码 N」，不把空文案展示到 UI
 */
fun envelopeError(obj: JsonObject, envelope: EnvelopeSpec?): String? {
    if (envelope == null) return null
    val codeEl = resolveField(obj, envelope.codePath)
        ?.takeUnless { it.isJsonNull }
        ?: return null
    val code = if (codeEl.isJsonPrimitive) {
        codeEl.asJsonPrimitive.asString
    } else {
        codeEl.toString()
    }
    if (code in envelope.okCodes) return null
    val msg = resolveField(obj, envelope.msgPath).asStringOrNull()?.takeIf { it.isNotBlank() }
        ?: "业务码 $code"
    return msg.take(80)
}

fun errorLabel(kind: ErrorKind): String = when (kind) {
    ErrorKind.SERVER -> "服务端错误"
    ErrorKind.AUTH -> "鉴权失败"
    ErrorKind.HTTP -> "HTTP 错误"
    ErrorKind.TIMEOUT -> "请求超时"
    ErrorKind.NETWORK -> "网络错误"
    ErrorKind.PARSE -> "解析失败"
    ErrorKind.CONFIG -> "配置错误"
}

/**
 * 响应体解析（顶层纯函数，可单测，不触发 OkHttpClient 初始化）：
 * HTTP 200 后校验「必须是 JsonObject」+ 业务码。
 *
 * 与 token_eye.py 口径一致：HTTP 200 但响应不是 JSON 对象（数组/标量/非 JSON）
 * 一律判 PARSE 错误，不再构造空 JsonObject() 假成功。
 */
internal fun parseResponse(body: String, envelope: EnvelopeSpec?): FetchResult {
    return try {
        val parsed = JsonParser.parseString(body)
        if (!parsed.isJsonObject) {
            return FetchResult(errorKind = ErrorKind.PARSE, message = "响应非 JSON 对象")
        }
        val obj = parsed.asJsonObject
        // 与 Mac 侧 apply_envelope(default_check=True) 同口径：
        // 配了 envelope → 只跑 envelopeError；未配 → 跑默认业务码检查。
        // 刻意用 if/else 而非 `envelope?.let{...} ?: default...`：envelopeError 校验
        // 「通过」时返回 null，Elvis 会把这次通过再误跑一遍默认检查。
        val businessErr = if (envelope != null) {
            envelopeError(obj, envelope)
        } else {
            defaultBusinessCodeCheck(obj)
        }
        if (businessErr != null) {
            return FetchResult(errorKind = ErrorKind.AUTH, message = businessErr)
        }
        FetchResult(data = obj)
    } catch (e: Exception) {
        FetchResult(errorKind = ErrorKind.PARSE, message = "响应解析失败")
    }
}

// 未配 api.envelope 的平台也做保守业务码检查：国内平台常用
// HTTP 200 + {"code":401,...} 表达鉴权失败，只按 HTTP 判会渲染成绿色假成功。
// 规则与 Mac 侧 token_eye.py:default_business_code_check 完全一致：只认明确的错误值，
// 正常响应（无这些字段 / 成功值）零影响。
private val OK_BUSINESS_CODES = setOf("0", "200", "ok", "success", "true", "none", "null")
private val BUSINESS_CODE_KEYS = listOf("code", "errcode", "error_code", "retcode")
private val BAD_CODE_TOKENS = listOf("ERROR", "EXPIRED", "INVALID", "UNAUTHORIZED", "FORBIDDEN", "FAIL")

/**
 * 默认业务码检查（顶层纯函数，可单测）：返回 null 表示通过，非 null 为错误文案。
 * 仅在**未配 api.envelope** 时由 [parseResponse] 调用；[envelopeError] 纯函数语义不变。
 *
 * - 依次检查 code / errcode / error_code / retcode
 * - JsonNull、布尔值、空串、成功值白名单（大小写不敏感）一律放行
 * - 明确错误：数值 >=400 或 <0，或字符串含 ERROR/EXPIRED/INVALID/UNAUTHORIZED/FORBIDDEN/FAIL
 * - 错误文案取 msg / message / error（error 为对象时取其 message / code），回退「业务码 N」，截断 80
 */
internal fun defaultBusinessCodeCheck(obj: JsonObject): String? {
    for (key in BUSINESS_CODE_KEYS) {
        val el = obj.get(key) ?: continue
        if (el.isJsonNull) continue
        // 与 Mac 侧 isinstance(code, bool) → continue 一致
        if (el.isJsonPrimitive && el.asJsonPrimitive.isBoolean) continue
        val text = (if (el.isJsonPrimitive) el.asJsonPrimitive.asString else el.toString()).trim()
        if (text.isEmpty() || text.lowercase() in OK_BUSINESS_CODES) continue
        val bad = text.toDoubleOrNull()?.let { it >= 400.0 || it < 0.0 }
            ?: BAD_CODE_TOKENS.any { text.uppercase().contains(it) }
        if (!bad) continue
        return (firstBusinessMessage(obj) ?: "业务码 $text").take(80)
    }
    return null
}

/** msg / message / error（error 为对象时取 message / code），忽略空串 */
private fun firstBusinessMessage(obj: JsonObject): String? {
    val fromTop = listOf("msg", "message").firstNotNullOfOrNull { key ->
        obj.get(key)?.asStringOrNull()?.takeIf { it.isNotBlank() }
    }
    if (fromTop != null) return fromTop
    val error = obj.get("error") ?: return null
    if (error.isJsonObject) {
        return listOf("message", "code").firstNotNullOfOrNull { key ->
            error.asJsonObject.get(key)?.asStringOrNull()?.takeIf { it.isNotBlank() }
        }
    }
    return error.asStringOrNull()?.takeIf { it.isNotBlank() }
}
