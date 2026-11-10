package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.parseResponse
import com.coffeelab.tokeneye.core.defaultBusinessCodeCheck
import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.EnvelopeSpec
import com.coffeelab.tokeneye.core.ErrorKind
import com.coffeelab.tokeneye.core.ResultParser
import com.coffeelab.tokeneye.core.envelopeError
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 业务码校验（2026-10-18 接智谱时加）。
 *
 * 国内平台普遍用 HTTP 200 + body.code 表达错误：智谱无效 Key 返回
 * {"code":401,"msg":"令牌已过期或验证不正确","success":false}。
 * 只看 HTTP 码会把无效 Key 渲染成「¥?」假绿，与 Mac 侧 apply_envelope 同口径。
 */
class EnvelopeTest {

    private val spec = EnvelopeSpec(codePath = "code", okCodes = listOf("200"), msgPath = "msg")

    private fun obj(s: String) = JsonParser.parseString(s).asJsonObject

    @Test
    fun ok_code_passes() {
        assertNull(envelopeError(obj("""{"code":200,"data":{"availableBalance":9.97}}"""), spec))
    }

    @Test
    fun failed_code_returns_message() {
        val err = envelopeError(
            obj("""{"code":401,"msg":"令牌已过期或验证不正确","success":false}"""), spec
        )
        assertEquals("令牌已过期或验证不正确", err)
    }

    @Test
    fun missing_code_passes() {
        assertNull(envelopeError(obj("""{"balance":1}"""), spec))
    }

    @Test
    fun no_envelope_configured_passes() {
        assertNull(envelopeError(obj("""{"code":401,"msg":"x"}"""), null))
    }

    @Test
    fun string_code_matches() {
        assertNull(envelopeError(obj("""{"code":"200"}"""), spec))
    }

    @Test
    fun config_loader_reads_envelope() {
        val cfg = ConfigLoader.parse(
            """
            {"providers":[{"id":"zhipu","name":"智谱 GLM",
              "api":{"url":"https://example.com","authPrefix":"",
                "envelope":{"codePath":"code","okCodes":[200],"msgPath":"msg"}},
              "parser":{"type":"balance","fields":{"balance":"data.availableBalance"}}}]}
            """.trimIndent()
        )
        val env = cfg.providers[0].api.envelope
        assertNotNull(env)
        assertEquals(listOf("200"), env!!.okCodes)
    }

    @Test
    fun zhipu_balance_shape_parses() {
        val cfg = ConfigLoader.parse(
            """
            {"providers":[{"id":"zhipu","name":"智谱 GLM",
              "api":{"url":"https://example.com"},
              "parser":{"type":"balance","fields":{"balance":"data.availableBalance"}}}]}
            """.trimIndent()
        )
        val data = obj("""{"code":200,"data":{"balance":9.97,"availableBalance":9.97}}""")
        val r = ResultParser.parse(cfg.providers[0], data)
        assertEquals("¥9.97", r.summary)
    }

    @Test
    fun malformed_object_code_is_validation_failure() {
        // 畸形 code（JsonObject）不能靠 asStringOrNull()=null 静默放行：
        // 取 JSON 文本与 okCodes 比较，必然不命中 → 判为业务码校验失败
        val err = envelopeError(obj("""{"code":{"nested":1},"msg":"bad envelope"}"""), spec)
        assertNotNull("畸形 code 应判校验失败，而不是放行", err)
        assertEquals("bad envelope", err)
    }

    @Test
    fun malformed_array_code_is_validation_failure() {
        val err = envelopeError(obj("""{"code":[1,2],"msg":""}"""), spec)
        assertNotNull("数组 code 应判校验失败，而不是放行", err)
        assertTrue("空 msg 应回退「业务码 N」，实际：$err", err!!.startsWith("业务码 "))
    }

    @Test
    fun empty_msg_falls_back_to_business_code() {
        assertEquals("业务码 500", envelopeError(obj("""{"code":500,"msg":""}"""), spec))
    }

    @Test
    fun blank_msg_falls_back_to_business_code() {
        assertEquals("业务码 401", envelopeError(obj("""{"code":401,"msg":"   "}"""), spec))
    }

    @Test
    fun non_json_object_body_is_parse_error() {
        // HTTP 200 + 非 JsonObject（数组 / 标量 / 非 JSON）不再构造空 JsonObject() 判成功
        val array = parseResponse("[1,2,3]", spec)
        assertEquals(ErrorKind.PARSE, array.errorKind)
        assertNull(array.data)

        val scalar = parseResponse("123", null)
        assertEquals(ErrorKind.PARSE, scalar.errorKind)

        val invalid = parseResponse("not json", null)
        assertEquals(ErrorKind.PARSE, invalid.errorKind)

        // 对象响应且业务码通过 → 正常返回 data
        val ok = parseResponse("""{"code":200,"data":{"balance":1}}""", spec)
        assertNull(ok.errorKind)
        assertNotNull(ok.data)
    }

    // ------------------------------------------------------------------
    // 默认业务码检查（P0-1 三端一致）：未配 api.envelope 的平台也必须拦住
    // HTTP 200 + {"code":401,...}，否则 DeepSeek/MiniMax 会假绿。
    // 规则与 Mac 侧 token_eye.py:default_business_code_check 一致。
    // ------------------------------------------------------------------

    @Test
    fun default_check_catches_http200_code401_without_envelope() {
        val body = """{"code":401,"msg":"令牌已过期或验证不正确"}"""
        // 纯函数直接断言
        assertEquals("令牌已过期或验证不正确", defaultBusinessCodeCheck(obj(body)))
        // 经 parseResponse 分流（envelope=null）→ AUTH 错误、不放行 data
        val r = parseResponse(body, null)
        assertEquals(ErrorKind.AUTH, r.errorKind)
        assertEquals("令牌已过期或验证不正确", r.message)
        assertNull(r.data)
    }

    @Test
    fun default_check_passes_success_codes_and_normal_body() {
        // 成功值白名单（大小写不敏感）+ 布尔 / JsonNull / 空串 + 无业务码字段，一律原样放行
        val bodies = listOf(
            """{"code":0,"data":{"balance":1}}""",
            """{"code":200,"data":{"balance":1}}""",
            """{"code":"OK"}""",
            """{"errcode":"Success"}""",
            """{"error_code":"true"}""",
            """{"retcode":"none"}""",
            """{"code":"null"}""",
            """{"code":true}""",
            """{"code":null}""",
            """{"code":""}""",
            """{"code":399}""",           // 数值 <400 且 >=0，不算明确错误
            """{"code":"PENDING"}""",     // 无错误关键词，不算明确错误
            """{"balance_infos":[{"total_balance":"12.34"}]}""",  // 完全无业务码字段
        )
        for (b in bodies) {
            val r = parseResponse(b, null)
            assertNull("正常响应必须放行：$b → ${r.errorKind} ${r.message}", r.errorKind)
            assertNotNull("正常响应必须返回 data：$b", r.data)
        }
    }

    @Test
    fun default_check_all_keys_and_error_message_shapes() {
        // 四个键都要检查；字符串错误关键词 / 负数 / error 对象里的 message
        val cases = listOf(
            """{"errcode":"UNAUTHORIZED","message":"登录已失效"}""" to "登录已失效",
            """{"error_code":-1}""" to "业务码 -1",
            """{"retcode":"EXPIRED_TOKEN"}""" to "业务码 EXPIRED_TOKEN",
            """{"code":"INVALID_KEY"}""" to "业务码 INVALID_KEY",
            """{"code":503,"error":{"message":"内部错误"}}""" to "内部错误",
            """{"code":500,"error":{"code":"E500"}}""" to "E500",
            """{"code":403,"error":"Forbidden"}""" to "Forbidden",
        )
        for ((body, expected) in cases) {
            val r = parseResponse(body, null)
            assertEquals("应拦住：$body", ErrorKind.AUTH, r.errorKind)
            assertEquals("错误文案不符：$body", expected, r.message)
        }
    }

    @Test
    fun envelope_configured_does_not_run_default_check() {
        // 配了 envelope 就只跑 envelopeError：即使 body 里另有 errcode=500，
        // 也不该被默认检查误伤（验证用 if/else 而非 Elvis 分流）
        val r = parseResponse("""{"code":200,"errcode":500,"data":{"balance":1}}""", spec)
        assertNull(r.errorKind)
        assertNotNull(r.data)
        // 配了 envelope 且业务码失败 → 走 envelopeError 文案
        val failed = parseResponse("""{"code":500,"msg":"业务失败"}""", spec)
        assertEquals(ErrorKind.AUTH, failed.errorKind)
        assertEquals("业务失败", failed.message)
    }
}
