package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.ResultParser
import com.coffeelab.tokeneye.core.resolveField
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ParserTest {

    @Test
    fun resolveField_dotPath_and_arrayIndex() {
        val json = JsonParser.parseString(
            """{"a":{"b":[{"c":1},{"c":2}]}}"""
        )
        assertEquals(2.0, resolveField(json, "a.b.1.c")!!.asDouble, 0.001)
        assertNull(resolveField(json, "a.b.5.c"))
        assertNull(resolveField(json, "x.y.z"))
    }

    @Test
    fun parseBalance_deepseek_shape() {
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"deepseek","name":"DeepSeek",
              "api":{"url":"https://x","authHeader":"Authorization","authPrefix":"Bearer "},
              "parser":{"type":"balance","fields":{"balance":"balance_infos.0.total_balance","currency":"balance_infos.0.currency"}},
              "display":{"unit":"¥","label":"余额"},
              "alert":{"minBalance":5.0}}]}
            """.trimIndent()
        )
        val p = config.providers[0]
        val data = JsonParser.parseString(
            """{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"123.45"}]}"""
        ).asJsonObject
        val r = ResultParser.parse(p, data, config.alerts)
        assertEquals("¥123.45", r.summary)
        assertEquals(123.45, r.balanceNum!!, 0.001)
        assertEquals(com.coffeelab.tokeneye.core.Status.OK, r.status)
    }

    @Test
    fun parseBalance_belowThreshold_warns() {
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"deepseek","name":"DeepSeek",
              "api":{"url":"https://x"},
              "parser":{"type":"balance","fields":{"balance":"data.balance"}},
              "alert":{"minBalance":10.0}},
             {"id":"d2","name":"D2","api":{"url":"https://x"},
              "parser":{"type":"balance","fields":{"balance":"data.balance"}}}],
             "alerts":{"d2":{"minBalance":10.0}}}
            """.trimIndent()
        )
        val data = JsonParser.parseString("""{"data":{"balance":3.0}}""").asJsonObject
        val r1 = ResultParser.parse(config.providers[0], data, config.alerts)
        val r2 = ResultParser.parse(config.providers[1], data, config.alerts)
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, r1.status)
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, r2.status)
    }

    @Test
    fun configLoader_dropsCookieRefreshProviders() {
        // Android 没有浏览器 Cookie 刷新能力：带 refreshParam 的平台必须被剔除
        val config = ConfigLoader.parse(
            """
            {"providers":[
              {"id":"deepseek","name":"DeepSeek","api":{"url":"https://x"},
               "parser":{"type":"balance","fields":{"balance":"data.balance"}}},
              {"id":"mimo","name":"MiMo","refreshParam":"refresh-mimo-cookie",
               "api":{"url":"https://x"},
               "parser":{"type":"balance","fields":{"balance":"data.balance"}}}
            ]}
            """.trimIndent()
        )
        assertEquals(1, config.providers.size)
        assertEquals("deepseek", config.providers[0].id)
    }

    @Test
    fun parsePlanUsage_percentStatus() {
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"minimax","name":"MiniMax",
              "api":{"url":"https://x"},
              "parser":{"type":"plan_usage","arrayPath":"model_remains",
                "fields":{"model":"model_name","intervalPct":"current_interval_remaining_percent","weeklyPct":"current_weekly_remaining_percent","resetMs":"remains_time"},
                "showModels":["general"],"modelLabels":{"general":""},
                "windowLabels":{"interval":"5h","weekly":"7d"}},
              "alert":{"minPct":80}}]}
            """.trimIndent()
        )
        val p = config.providers[0]
        val ok = JsonParser.parseString(
            """{"model_remains":[{"model_name":"general","current_interval_remaining_percent":66.0,"current_weekly_remaining_percent":90.0}]}"""
        ).asJsonObject
        val rOk = ResultParser.parse(p, ok, config.alerts)
        assertEquals(com.coffeelab.tokeneye.core.Status.OK, rOk.status)
        assertEquals(34.0, rOk.usedPct!!, 0.001)

        val near = JsonParser.parseString(
            """{"model_remains":[{"model_name":"general","current_interval_remaining_percent":8.0,"current_weekly_remaining_percent":90.0}]}"""
        ).asJsonObject
        val rNear = ResultParser.parse(p, near, config.alerts)
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, rNear.status)
        assertEquals(92.0, rNear.usedPct!!, 0.001)
    }
}
