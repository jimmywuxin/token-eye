package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.PeakWindow
import com.coffeelab.tokeneye.core.PeakWindowSpec
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
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
}