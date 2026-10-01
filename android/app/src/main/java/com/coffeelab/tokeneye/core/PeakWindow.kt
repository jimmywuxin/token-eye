package com.coffeelab.tokeneye.core

import java.time.Duration
import java.time.LocalDateTime
import java.time.LocalDate
import java.time.ZoneId

/**
 * 峰/谷时段判定 — Android 端镜像 swiftbar/parsers/peak_window.py 的纯逻辑模块。
 *
 * 设计目标：DeepSeek 等平台 API 不返回当前时段字段，按官方公示的本地时区规则自行判定。
 *
 * 规则（DeepSeek 峰谷定价）：
 * - 高峰：本地时区周一至周五（**不含中国法定节假日**）在 hours 区间内
 * - 空闲：其余时段 —— 午休/夜间、周末、**法定节假日全天**
 * - 特例：**调休上班的周末**算工作日（落在区间内即高峰）
 *
 * 法定节假日/调休由国务院逐年公告，**没有算法规律**，只能查表：由
 * [HolidayTable] 从 assets/holidays/<年>.json 读入后传入 `holidays`；
 * 传空表时退化为纯 weekdays 判定（与旧版行为一致）。
 *
 * 用法：
 *   val info = PeakWindow.classify(LocalDateTime.now(ZoneId.of(spec.tz)), spec, holidays)
 *   info.label         // "⚡高峰" 或 "🌙空闲"
 *   info.windowStr     // "高峰" / "空闲" / "周末" / "节假日"
 *   info.isPeak        // true / false
 *   info.secondsToSwitch  // 距下次切换秒数（高峰→距空闲；空闲/周末/节假日→距高峰）
 */
object PeakWindow {

    /** 向后搜索下一个工作日的天数上限（春节 9 连休 + 前后周末也够用） */
    private const val MAX_LOOKAHEAD_DAYS = 21L

    data class Info(
        val isPeak: Boolean,
        val label: String,          // 菜单栏展示文本（"⚡高峰" 或 "🌙空闲"）
        val windowStr: String,      // 详情行基础文本（"高峰" / "空闲" / "周末" / "节假日"）
        val secondsToSwitch: Int,   // 距下次切换的秒数（≥0）
        val tz: String,             // 实际使用的时区名
        val isHoliday: Boolean = false,  // 当前是否法定节假日/调休放假
    )

    /** 当前本地小时是否落在任一区间内（左闭右开 [start,end)） */
    fun isPeakHour(localDt: LocalDateTime, ranges: List<IntRange>): Boolean =
        ranges.any { it.contains(localDt.hour) }

    /** 某天是否算「工作日」（节假日/调休表优先于 weekdays 规则）。 */
    fun isWorkday(day: LocalDate, spec: PeakWindowSpec, holidays: Map<String, Boolean> = emptyMap()): Boolean {
        val off = holidays[day.toString()]
        if (off != null) return !off
        return day.dayOfWeek.value in spec.weekdays
    }

    /** 某天是否是法定节假日/调休放假（仅用于展示文案「节假日」）。 */
    fun isHoliday(day: LocalDate, holidays: Map<String, Boolean> = emptyMap()): Boolean =
        holidays[day.toString()] == true

    /**
     * 核心判定入口。
     *
     * @param localDt 本地时区的 LocalDateTime（时区由 spec.tz 决定；调用方可用 LocalDateTime.now(zone)）
     * @param spec PeakWindowSpec 配置
     * @param holidays 节假日表（键为 "YYYY-MM-DD"，值为是否放假），见 [HolidayTable]；空表则只按 weekdays 判定
     */
    fun classify(
        localDt: LocalDateTime,
        spec: PeakWindowSpec,
        holidays: Map<String, Boolean> = emptyMap(),
    ): Info {
        val tzId = try { ZoneId.of(spec.tz).id } catch (e: Exception) { "Asia/Shanghai" }

        val isWork = isWorkday(localDt.toLocalDate(), spec, holidays)
        val onHoliday = isHoliday(localDt.toLocalDate(), holidays)
        val inWindow = isPeakHour(localDt, spec.hours)
        val isPeak = isWork && inWindow

        val label = if (isPeak) spec.peakLabel else spec.offPeakLabel
        val windowStr = when {
            isPeak -> "高峰"
            !isWork -> if (onHoliday) "节假日" else "周末"
            else -> "空闲"  // 调休上班的周末也走这里：算工作日，非区间内即空闲
        }

        val secondsToSwitch = secondsToNextSwitch(localDt, spec, isPeak, holidays)
        return Info(isPeak, label, windowStr, secondsToSwitch, tzId, onHoliday)
    }

    /**
     * 计算距下次切换秒数（与 parsers/peak_window.py next_switch 口径一致）。
     * - 高峰中（且今天是工作日）：到当前所在区间结束（end=24 视为次日 00:00）
     * - 空闲/周末/节假日：到下一个「工作日」的第一个区间起点（最多向后找 21 天）
     */
    fun secondsToNextSwitch(
        localNow: LocalDateTime,
        spec: PeakWindowSpec,
        isPeak: Boolean,
        holidays: Map<String, Boolean> = emptyMap(),
    ): Int {
        val sortedRanges = spec.hours.sortedBy { it.first }
        if (sortedRanges.isEmpty()) return 0

        return if (isPeak) {
            // 当前所在区间 → 到 endExclusive（IntRange 的 last 是 inclusive = end-1，所以 end = last+1）
            val cur = sortedRanges.firstOrNull { it.contains(localNow.hour) } ?: sortedRanges.last()
            val endHour = cur.last + 1  // [9,12) → endHour=12
            if (endHour >= 24) {
                // 跨零点：到次日 00:00
                val nextMidnight = localNow.toLocalDate().plusDays(1).atStartOfDay()
                Duration.between(localNow, nextMidnight).seconds.toInt().coerceAtLeast(0)
            } else {
                val minutesLeft = (endHour - localNow.hour) * 60 - localNow.minute
                (minutesLeft * 60 - localNow.second).coerceAtLeast(0)
            }
        } else {
            // 下一个工作日的第一个区间起点（跳过节假日与非工作日）
            val starts = sortedRanges.map { it.first }
            for (offset in 0..MAX_LOOKAHEAD_DAYS) {
                val day = localNow.toLocalDate().plusDays(offset)
                if (!isWorkday(day, spec, holidays)) continue
                val dayStarts = if (offset == 0L) starts.filter { it > localNow.hour } else starts
                val first = dayStarts.firstOrNull() ?: continue
                val target = day.atTime(first, 0)
                return Duration.between(localNow, target).seconds.toInt().coerceAtLeast(0)
            }
            0
        }
    }

    /**
     * 把秒数格式化成简短文案（与 swiftbar/parsers/peak_window.py 的 format_countdown 一致）。
     * 取两级单位：≥ 1 天 → `6d9h`（整点省略小时 → `6d`）；否则 `1h30m` / `2h` / `45m`。
     */
    fun formatCountdown(seconds: Int): String {
        if (seconds <= 0) return ""
        val h = seconds / 3600
        val m = (seconds % 3600) / 60
        if (h >= 24) {
            val d = h / 24
            val hh = h % 24
            return if (hh > 0) "${d}d${hh}h" else "${d}d"
        }
        return when {
            h > 0 && m > 0 -> "${h}h${m}m"
            h > 0 -> "${h}h"
            else -> "${m}m"
        }
    }
}
