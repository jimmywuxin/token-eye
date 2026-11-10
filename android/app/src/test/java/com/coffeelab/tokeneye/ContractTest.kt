package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ApiSpec
import com.coffeelab.tokeneye.core.EnvelopeSpec
import com.coffeelab.tokeneye.core.ParserSpec
import com.coffeelab.tokeneye.core.Provider
import com.coffeelab.tokeneye.core.ResultParser
import com.coffeelab.tokeneye.core.Status
import com.coffeelab.tokeneye.core.defaultBusinessCodeCheck
import com.coffeelab.tokeneye.core.envelopeError
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/**
 * 跨端口径契约测试：与 Mac/Linux 的 tests/test_contract.py 消费同一份
 * tests/fixtures/cross_platform_cases.json。改判定规则先改 fixture，三端一起跑。
 */
class ContractTest {

    private val gson = Gson()

    /** Gradle 单测工作目录通常是 android/app，逐级向上找仓库根。 */
    private fun fixture(): JsonObject {
        val startDir = System.getProperty("user.dir") ?: "."
        var dir: File? = File(startDir)
        repeat(8) {
            dir?.let { d ->
                val f = File(d, "tests/fixtures/cross_platform_cases.json")
                if (f.isFile) return JsonParser.parseString(f.readText()).asJsonObject
            }
            dir = dir?.parentFile
        }
        fail("找不到 tests/fixtures/cross_platform_cases.json（起点 $startDir）")
        return JsonObject()
    }

    private fun balanceProvider(fields: JsonObject): Provider = Provider(
        id = "deepseek",
        name = "DeepSeek",
        api = ApiSpec(url = "https://example.invalid"),
        parser = ParserSpec(
            type = "balance",
            fields = fields.entrySet().associate { it.key to it.value.asString },
        ),
    )

    @Test
    fun cross_platform_contract_cases() {
        val fx = fixture()
        assertEquals(1, fx.get("schema").asInt)
        val cases = fx.getAsJsonArray("cases")
        assertTrue("fixture 不能为空", cases.size() > 0)
        val balanceFields = fx.getAsJsonObject("balance_fields")
        val ids = mutableSetOf<String>()

        for (element in cases) {
            val c = element.asJsonObject
            val id = c.get("id").asString
            assertTrue("case id 重复: $id", ids.add(id))
            val consumers = c.getAsJsonArray("consumers").map { it.asString }
            if ("android" !in consumers) continue

            val data = c.getAsJsonObject("data")
            val expect = c.getAsJsonObject("expect")
            when (c.get("kind").asString) {
                "business_code" -> {
                    val envJson = c.get("envelope")
                    val err: String? = if (envJson == null || envJson.isJsonNull) {
                        defaultBusinessCodeCheck(data)
                    } else {
                        envelopeError(data, gson.fromJson(envJson, EnvelopeSpec::class.java))
                    }
                    if (expect.get("fetch_ok").asBoolean) {
                        assertNull("$id 应放行（正常响应/成功业务码）", err)
                    } else {
                        assertNotNull("$id 应拦截业务错误，不能假绿", err)
                    }
                }
                "balance_parse" -> {
                    val r = ResultParser.parseBalance(balanceProvider(balanceFields), data)
                    if (expect.get("status_class").asString == "ok") {
                        assertEquals("$id", Status.OK, r.status)
                    } else {
                        assertNotEquals("$id 假绿：字段缺失/不可解析不得判 OK", Status.OK, r.status)
                    }
                }
                else -> fail("$id 未知 kind")
            }
        }
    }
}
