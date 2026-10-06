package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.ResultParser
import com.coffeelab.tokeneye.core.resolveField
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

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

    @Test
    fun parsePlanUsage_worstOfBothWindows_notBest() {
        // 无 minPct 时status 完全由 worst 决定 —— 这里隔离验证「取最差」：
        // interval 正常(90) + weekly 耗尽(0) 必须判 ERR，而不是被 interval 拉回 OK。
        // 回归背景：曾误用 minByOrNull{ordinal}，而 Status 序为 OK<WARN<ERR，等于取最好。
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"minimax","name":"MiniMax",
              "api":{"url":"https://x"},
              "parser":{"type":"plan_usage","arrayPath":"model_remains",
                "fields":{"model":"model_name","intervalPct":"current_interval_remaining_percent","weeklyPct":"current_weekly_remaining_percent"},
                "showModels":["general"],"modelLabels":{"general":""},
                "windowLabels":{"interval":"5h","weekly":"7d"}}}]}
            """.trimIndent()
        )
        val p = config.providers[0]
        fun parse(interval: Double, weekly: Double) = ResultParser.parse(
            p,
            JsonParser.parseString(
                """{"model_remains":[{"model_name":"general","current_interval_remaining_percent":$interval,"current_weekly_remaining_percent":$weekly}]}"""
            ).asJsonObject,
        ).status

        // 取最差：weekly 差就整体差，不被正常的 interval 拉回 OK
        assertEquals(com.coffeelab.tokeneye.core.Status.ERR, parse(90.0, 0.0))    // weekly 耗尽
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, parse(90.0, 8.0))   // weekly 临近
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, parse(8.0, 90.0))    // interval 差
        assertEquals(com.coffeelab.tokeneye.core.Status.ERR, parse(0.0, 90.0))    // interval 耗尽
        assertEquals(com.coffeelab.tokeneye.core.Status.OK, parse(90.0, 90.0))    // 都正常
    }

    @Test
    fun parsePlanUsage_honorsPctDirection() {
        // pctDirection 语义必须与 Mac 侧 _to_used 一致：
        //   "remaining"（默认）→ 接口返回剩余 %，翻转成已用
        //   "used"              → 接口返回已用 %，直接用
        // 回归背景：Android 曾硬编码 100-remaining，配 "used" 的provider 会被算反。
        fun parseWith(direction: String, rawInterval: Double): com.coffeelab.tokeneye.core.ProviderResult {
            val cfg = ConfigLoader.parse(
                """
                {"providers":[{"id":"m","name":"M",
                  "api":{"url":"https://x"},
                  "parser":{"type":"plan_usage","arrayPath":"model_remains",
                    "pctDirection":"$direction",
                    "fields":{"model":"model_name","intervalPct":"pct","weeklyPct":"pct"},
                    "showModels":["general"]}}]}
                """.trimIndent()
            )
            return ResultParser.parse(
                cfg.providers[0],
                JsonParser.parseString(
                    """{"model_remains":[{"model_name":"general","pct":$rawInterval}]}"""
                ).asJsonObject,
            )
        }

        // 剩余 30% → 已用 70% → OK
        assertEquals(70.0, parseWith("remaining", 30.0).usedPct!!, 0.001)
        // 已用 30%（used 口径）→ OK；两种口径同值应得同一结果
        assertEquals(30.0, parseWith("used", 30.0).usedPct!!, 0.001)
        // 剩余 5% → 已用 95% → WARN
        assertEquals(com.coffeelab.tokeneye.core.Status.WARN, parseWith("remaining", 5.0).status)
        // 已用 100%（used 口径）→ 耗尽 ERR
        assertEquals(com.coffeelab.tokeneye.core.Status.ERR, parseWith("used", 100.0).status)
        // 越界值被夹到 [0,100]
        assertEquals(100.0, parseWith("used", 150.0).usedPct!!, 0.001)
        assertEquals(0.0, parseWith("used", -20.0).usedPct!!, 0.001)
    }

    /**
     * 回归：手机版「国庆期间显示成工作日空闲、倒计时指向一个并不存在的高峰」。
     *
     * 链路 = 配置 `parser.peakWindow.holidays` 开关 → 是否叠加节假日表 → 详情行文案。
     * 少了任何一环（配置没随包更新 / holidays 开关被读成 false / 表没传进去），
     * 都会退化成纯 weekdays 判定，症状完全一样，所以必须在端到端这一层钉住。
     *
     * 节假日表按「今天」动态构造（今天起 21 天全放假，其中某个工作日显式置为调休上班），
     * 这样无论测试在哪天跑结论都成立，不受真实日历影响。
     */
    @Test
    fun peakWindow_holidays_flag_reaches_the_render_line() {
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"deepseek","name":"DeepSeek",
              "api":{"url":"https://x","authHeader":"Authorization","authPrefix":"Bearer "},
              "parser":{"type":"balance",
                "fields":{"balance":"balance_infos.0.total_balance","currency":"balance_infos.0.currency"},
                "peakWindow":{"tz":"Asia/Shanghai","weekdays":[1,2,3,4,5],
                  "hours":[[9,12],[14,18]],"holidays":true,
                  "peakLabel":"⚡高峰","offPeakLabel":"🌙空闲"}},
              "display":{"unit":"¥","label":"余额"}}]}
            """.trimIndent()
        )
        val p = config.providers[0]
        assertEquals(true, p.parser.peakWindow!!.holidays)  // 开关必须被真正读进来

        val data = JsonParser.parseString(
            """{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"9.93"}]}"""
        ).asJsonObject
        val r = ResultParser.parse(p, data, config.alerts, syntheticHolidayTable())

        // 今天是「法定节假日」→ 必须判为节假日，而不是「空闲 距高峰 55m」
        val line = r.details.firstOrNull { it.startsWith("节假日") || it.startsWith("高峰") || it.startsWith("空闲") }
        assertNotNull("详情行缺少峰谷时段文案：${r.details}", line)
        assertTrue("节假日当天应显示「节假日」，实际：$line", line!!.startsWith("节假日"))
        assertTrue("倒计时应指向下一个工作日的第一个高峰档，实际：$line", line.contains("距高峰"))
    }

    /** holidays 开关为 true 但调用方没传表时，必须退化为纯 weekdays（表为空 → 不可能判出「节假日」） */
    @Test
    fun peakWindow_empty_holiday_table_degrades_to_weekdays() {
        val config = ConfigLoader.parse(
            """
            {"providers":[{"id":"deepseek","name":"DeepSeek",
              "api":{"url":"https://x","authHeader":"Authorization","authPrefix":"Bearer "},
              "parser":{"type":"balance",
                "fields":{"balance":"balance_infos.0.total_balance","currency":"balance_infos.0.currency"},
                "peakWindow":{"tz":"Asia/Shanghai","weekdays":[1,2,3,4,5],
                  "hours":[[9,12],[14,18]],"holidays":true}},
              "display":{"unit":"¥","label":"余额"}}]}
            """.trimIndent()
        )
        val p = config.providers[0]
        val data = JsonParser.parseString(
            """{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"9.93"}]}"""
        ).asJsonObject
        val r = ResultParser.parse(p, data, config.alerts, emptyMap())
        val line = r.details.first { it.startsWith("空闲") || it.startsWith("节假日") || it.startsWith("高峰") }
        assertFalse("空表时不应判出「节假日」，实际：$line", line.startsWith("节假日"))
    }

    companion object {
        /**
         * 造一张「今天起连续放假、其中 3 天后那个工作日调休上班」的表。
         * 覆盖 PeakWindow 搜索窗口（21 天）内必然存在至少一个工作日，结论稳定。
         */
        private fun syntheticHolidayTable(): Map<String, Boolean> {
            val today = LocalDate.now(ZoneId.of("Asia/Shanghai"))
            val table = mutableMapOf<String, Boolean>()
            var resumeDay: LocalDate? = null
            for (i in 0..20) {
                val d = today.plusDays(i.toLong())
                table[d.toString()] = true
                if (i >= 3 && resumeDay == null && d.dayOfWeek.value <= 5) resumeDay = d
            }
            resumeDay?.let { table[it.toString()] = false }  // 调休上班 → 算工作日
            return table
        }
    }
}
