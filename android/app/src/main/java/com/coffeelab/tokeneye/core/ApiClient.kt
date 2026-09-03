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
import java.util.concurrent.TimeUnit

enum class ErrorKind { SERVER, AUTH, HTTP, TIMEOUT, NETWORK, PARSE }

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
    ): FetchResult = withContext(Dispatchers.IO) {
        val builder = Request.Builder().url(url)
        if (key.isNotBlank()) builder.header(authHeader, authPrefix + key)
        extraHeaders.forEach { (k, v) -> builder.header(k, v) }
        when (method.uppercase()) {
            "POST" -> builder.post("".toRequestBody())
            "PUT" -> builder.put("".toRequestBody())
            else -> builder.get()
        }
        try {
            client.newCall(builder.build()).execute().use { resp ->
                val body = resp.body?.string() ?: ""
                if (!resp.isSuccessful) {
                    val kind = when {
                        resp.code >= 500 -> ErrorKind.SERVER
                        resp.code == 401 || resp.code == 403 -> ErrorKind.AUTH
                        else -> ErrorKind.HTTP
                    }
                    return@withContext FetchResult(
                        errorKind = kind,
                        message = "HTTP ${resp.code}",
                    )
                }
                try {
                    val parsed = JsonParser.parseString(body)
                    val obj = if (parsed.isJsonObject) parsed.asJsonObject else JsonObject()
                    FetchResult(data = obj)
                } catch (e: Exception) {
                    FetchResult(errorKind = ErrorKind.PARSE, message = "响应非 JSON：${e.message ?: ""}")
                }
            }
        } catch (e: SocketTimeoutException) {
            FetchResult(errorKind = ErrorKind.TIMEOUT, message = "请求超时")
        } catch (e: IOException) {
            FetchResult(errorKind = ErrorKind.NETWORK, message = "网络错误：${e.message ?: ""}")
        } catch (e: Exception) {
            FetchResult(errorKind = ErrorKind.NETWORK, message = e.message ?: "未知错误")
        }
    }
}

fun errorLabel(kind: ErrorKind): String = when (kind) {
    ErrorKind.SERVER -> "服务端错误"
    ErrorKind.AUTH -> "鉴权失败"
    ErrorKind.HTTP -> "HTTP 错误"
    ErrorKind.TIMEOUT -> "请求超时"
    ErrorKind.NETWORK -> "网络错误"
    ErrorKind.PARSE -> "解析失败"
}
