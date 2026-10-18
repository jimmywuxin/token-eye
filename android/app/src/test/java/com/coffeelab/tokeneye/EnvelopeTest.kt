package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.EnvelopeSpec
import com.coffeelab.tokeneye.core.ResultParser
import com.coffeelab.tokeneye.core.envelopeError
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
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
}
