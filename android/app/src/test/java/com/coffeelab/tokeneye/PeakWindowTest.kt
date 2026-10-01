package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.HolidayTable
import com.coffeelab.tokeneye.core.PeakWindow
import com.coffeelab.tokeneye.core.PeakWindowSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.LocalDateTime
import java.time.ZoneId

/** 镜像 swiftbar/parsers/peak_window.py 的语义；DeepSeek 默认配置。 */
class PeakWindowTest {

    private val spec = PeakWindowSpec(
        tz = "Asia/Shanghai",
        weekdays = listOf(1, 2, 3, 4, 5),
        hours = listOf(9 until 12, 14 until 18),
    )

    /** 构造指定 weekday（周一=1..周日=7）的北京时间 */
    private fun at(hour: Int, minute: Int = 0, weekday: Int = 1): LocalDateTime {
        // 2026-01-05 是周一
        val base = LocalDateTime.of(2026, 1, 5, hour, minute)
        return base.plusDays((weekday - 1).toLong())
    }

    @Test
    fun weekday_peak_morning() {
        val info = PeakWindow.classify(at(10, 30, weekday = 1), spec)
        assertTrue(info.isPeak)
        assertEquals("⚡高峰", info.label)
        assertEquals("高峰", info.windowStr)
    }

    @Test
    fun weekday_offpeak_gap() {
        val info = PeakWindow.classify(at(13, 0, weekday = 2), spec)
        assertFalse(info.isPeak)
        assertEquals("🌙空闲", info.label)
        assertEquals("空闲", info.windowStr)
    }

    @Test
    fun weekday_offpeak_evening() {
        val info = PeakWindow.classify(at(20, 0, weekday = 3), spec)
        assertFalse(info.isPeak)
        assertEquals("空闲", info.windowStr)
    }

    @Test
    fun weekend_is_offpeak_even_in_window() {
        val info = PeakWindow.classify(at(10, 30, weekday = 6), spec)
        assertFalse(info.isPeak)
        assertEquals("周末", info.windowStr)
    }

    @Test
    fun sunday_evening() {
        val info = PeakWindow.classify(at(22, 0, weekday = 7), spec)
        assertFalse(info.isPeak)
        assertEquals("周末", info.windowStr)
    }

    @Test
    fun boundary_exclusive_end() {
        // 12:00 不算在 [9,12) 内
        val info = PeakWindow.classify(at(12, 0, weekday = 1), spec)
        assertFalse(info.isPeak)
        // 09:00 算
        val info2 = PeakWindow.classify(at(9, 0, weekday = 1), spec)
        assertTrue(info2.isPeak)
    }

    @Test
    fun boundary_exclusive_end_second_window() {
        val info = PeakWindow.classify(at(18, 0, weekday = 1), spec)
        assertFalse(info.isPeak)
        val info2 = PeakWindow.classify(at(17, 59, weekday = 1), spec)
        assertTrue(info2.isPeak)
    }

    @Test
    fun seconds_to_switch_during_first_window() {
        // 10:00 高峰中，距空闲（12:00）剩 2h
        val info = PeakWindow.classify(at(10, 0, weekday = 1), spec)
        assertEquals(2 * 3600, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_during_gap() {
        // 13:00 空闲中，距高峰（14:00）剩 1h
        val info = PeakWindow.classify(at(13, 0, weekday = 1), spec)
        assertEquals(3600, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_after_last_window() {
        // 20:00 空闲晚间，距次日 09:00 高峰 = 13h
        val info = PeakWindow.classify(at(20, 0, weekday = 1), spec)
        assertEquals(13 * 3600, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_friday_evening_skips_weekend() {
        // 周五 20:00 → 下一个高峰是周一 09:00（61h），不是周六 09:00
        val info = PeakWindow.classify(at(20, 0, weekday = 5), spec)
        assertEquals(61 * 3600, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_saturday_morning_skips_to_monday() {
        // 周六 09:30（落在时段内但周末）→ 周一 09:00 = 47h30m
        val info = PeakWindow.classify(at(9, 30, weekday = 6), spec)
        assertEquals("周末", info.windowStr)
        assertEquals(47 * 3600 + 30 * 60, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_sunday_evening_to_monday() {
        // 周日 23:00 → 周一 09:00 = 10h
        val info = PeakWindow.classify(at(23, 0, weekday = 7), spec)
        assertEquals(10 * 3600, info.secondsToSwitch)
    }

    @Test
    fun seconds_to_switch_allday_peak_crosses_midnight() {
        // 全天高峰（[0,24)）周五 23:00 高峰中 → 次日 00:00 翻转
        val allDay = spec.copy(hours = listOf(0 until 24))
        val info = PeakWindow.classify(at(23, 0, weekday = 5), allDay)
        assertTrue(info.isPeak)
        assertEquals(3600, info.secondsToSwitch)
    }

    @Test
    fun format_countdown() {
        assertEquals("", PeakWindow.formatCountdown(0))
        assertEquals("0m", PeakWindow.formatCountdown(59))
        assertEquals("1m", PeakWindow.formatCountdown(60))
        assertEquals("1h", PeakWindow.formatCountdown(3600))
        assertEquals("1h1m", PeakWindow.formatCountdown(3660))
        assertEquals("2h2m", PeakWindow.formatCountdown(7320))
        // ≥ 1 天取 d+h 两级（跨整段假期时 153h18m 没法读）
        assertEquals("23h59m", PeakWindow.formatCountdown(86399))
        assertEquals("1d", PeakWindow.formatCountdown(86400))
        assertEquals("1d1h", PeakWindow.formatCountdown(90000))
        assertEquals("6d22h", PeakWindow.formatCountdown(599400))  // 国庆 10-01 10:30 → 10-08 09:00
        assertEquals("6d9h", PeakWindow.formatCountdown(551880))   // 153h18m
        assertEquals("9d13h", PeakWindow.formatCountdown(824400))  // 春节长空窗
    }

    @Test
    fun invalid_tz_falls_back() {
        val badSpec = spec.copy(tz = "Not/A/Real_Zone")
        val info = PeakWindow.classify(at(10, 30, weekday = 1), badSpec)
        assertEquals("Asia/Shanghai", info.tz)  // 兜底
        assertTrue(info.isPeak)
    }

    @Test
    fun custom_only_morning_peak() {
        val morningOnly = spec.copy(hours = listOf(9 until 12))
        assertTrue(PeakWindow.classify(at(10, 0), morningOnly).isPeak)
        assertFalse(PeakWindow.classify(at(14, 0), morningOnly).isPeak)
    }

    @Test
    fun result_keys() {
        val info = PeakWindow.classify(at(10, 30), spec)
        for (k in listOf("isPeak", "label", "windowStr", "secondsToSwitch", "tz")) {
            // 通过 toString() 验证所有字段都被序列化（Info 是 data class）
            assertTrue(info.toString().isNotEmpty())
        }
    }

    // ------------------------------------------------------------------
    // 中国法定节假日 / 调休（镜像 parsers/peak_window.py 的 holidays 叠加逻辑）
    // ------------------------------------------------------------------

    private val holidaySpec = spec.copy(holidays = true)

    /** 按具体日期构造北京时间，如 on("2026-10-01", 10, 30) */
    private fun on(date: String, hour: Int, minute: Int = 0): LocalDateTime {
        val (y, m, d) = date.split("-").map { it.toInt() }
        return LocalDateTime.of(y, m, d, hour, minute)
    }

    /** 读取 Android 侧打包的节假日数据（单测工作目录为 app/，兼容 android/ 与 app/ 两种） */
    private fun assetHolidays(name: String): Map<String, Boolean> {
        val file = listOf(
            "src/main/assets/holidays/$name",
            "app/src/main/assets/holidays/$name",
            "../app/src/main/assets/holidays/$name",
        ).map { File(it) }.firstOrNull { it.isFile }
        assertNotNull("assets/holidays/$name 未随仓库打包", file)
        return HolidayTable.parse(file!!.readText())
    }

    @Test
    fun holiday_table_parse_and_asset_packed() {
        val table = assetHolidays("2026.json")
        assertEquals(true, table["2026-10-01"])   // 国庆放假
        assertEquals(false, table["2026-09-20"])  // 调休上班（周日）
        assertEquals(39, table.size)

        // 纯解析：内联 JSON
        val inline = HolidayTable.parse("""{"days":[{"date":"2026-10-01","isOffDay":true},{"date":"2026-09-20","isOffDay":false}]}""")
        assertEquals(mapOf("2026-10-01" to true, "2026-09-20" to false), inline)
        assertTrue(HolidayTable.parse("{ not json").isEmpty())
        assertTrue(HolidayTable.parse("""{"days":[]}""").isEmpty())
    }

    @Test
    fun holiday_is_offpeak_all_day() {
        val table = assetHolidays("2026.json")
        val info = PeakWindow.classify(on("2026-10-01", 10, 30), holidaySpec, table)  // 周四 10:30
        assertFalse(info.isPeak)
        assertTrue(info.isHoliday)
        assertEquals("节假日", info.windowStr)
        assertEquals("🌙空闲", info.label)
        assertEquals(599400, info.secondsToSwitch)  // → 10-08（周四）09:00 = 6d22h30m
    }

    @Test
    fun makeup_saturday_counts_as_workday() {
        val table = assetHolidays("2026.json")
        val peak = PeakWindow.classify(on("2026-10-10", 10, 30), holidaySpec, table)  // 周六调休上班
        assertTrue(peak.isPeak)
        assertEquals("高峰", peak.windowStr)
        val idle = PeakWindow.classify(on("2026-10-10", 20, 0), holidaySpec, table)
        assertFalse(idle.isPeak)
        assertEquals("空闲", idle.windowStr)  // 算工作日，不是「周末」
    }

    @Test
    fun plain_weekend_still_weekend() {
        val table = assetHolidays("2026.json")
        val info = PeakWindow.classify(on("2026-09-19", 10, 30), holidaySpec, table)  // 周六，非调休
        assertFalse(info.isPeak)
        assertEquals("周末", info.windowStr)
    }

    @Test
    fun spring_festival_long_gap_lookahead() {
        val table = assetHolidays("2026.json")
        // 02-14（周六）是春节调休上班日，20:00 后 → 下一个工作日 02-24（周二）09:00 = 9d13h
        val info = PeakWindow.classify(on("2026-02-14", 20, 0), holidaySpec, table)
        assertEquals("空闲", info.windowStr)
        assertEquals(824400, info.secondsToSwitch)
    }

    @Test
    fun without_table_behaves_as_before() {
        // 不传表（或 spec.holidays=false）→ 旧口径：国庆当天照旧算高峰
        val info = PeakWindow.classify(on("2026-10-01", 10, 30), spec, emptyMap())
        assertTrue(info.isPeak)
        assertFalse(info.isHoliday)
    }
}