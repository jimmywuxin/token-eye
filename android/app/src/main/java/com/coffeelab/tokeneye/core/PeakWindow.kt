package com.coffeelab.tokeneye.core

import java.time.LocalDateTime
import java.time.ZoneId

/**
 * 峰/谷时段判定 — Android 端镜像 swiftbar/parsers/peak_window.py 的纯逻辑模块。
 *
 * 设计目标：DeepSeek 等平台 API 不返回当前时段字段，按官方公示的本地时区规则自行判定。
 *
 * 用法：
 *   val info = PeakWindow.classify(LocalDateTime.now(ZoneId.of(spec.tz)), spec)
 *   info.label         // "⚡高峰" 或 "🌙空闲"
 *   info.windowStr     // "高峰" / "空闲" / "周末"
 *   info.isPeak        // true / false
 *   info.secondsToSwitch  // 距下次切换秒数（高峰→距空闲；空闲/周末→距高峰）
 */
object PeakWindow {

    data class Info(
        val isPeak: Boolean,
        val label: String,          // 菜单栏展示文本（"⚡高峰" 或 "🌙空闲"）
        val windowStr: String,      // 详情行基础文本（"高峰" / "空闲" / "周末"）
        val secondsToSwitch: Int,   // 距下次切换的秒数（≥0）
        val tz: String,             // 实际使用的时区名
    )

    /** 当前本地小时是否落在任一区间内（左闭右开 [start,end)） */
    fun isPeakHour(localDt: LocalDateTime, ranges: List<IntRange>): Boolean =
        ranges.any { it.contains(localDt.hour) }

    /**
     * 核心判定入口。
     *
     * @param localDt 本地时区的 LocalDateTime（时区由 spec.tz 决定；调用方可用 LocalDateTime.now(zone)）
     * @param spec PeakWindowSpec 配置
     */
    fun classify(localDt: LocalDateTime, spec: PeakWindowSpec): Info {
        val tzId = try { ZoneId.of(spec.tz).id } catch (e: Exception) { "Asia/Shanghai" }

        val isWeekday = localDt.dayOfWeek.value in spec.weekdays  // DayOfWeek.MONDAY.value=1..SUNDAY.value=7
        val inWindow = isPeakHour(localDt, spec.hours)
        val isPeak = isWeekday && inWindow

        val label = if (isPeak) spec.peakLabel else spec.offPeakLabel
        val windowStr = when {
            isPeak -> "高峰"
            !isWeekday -> "周末"
            else -> "空闲"
        }

        val secondsToSwitch = secondsToNextSwitch(localDt, spec, isPeak)
        return Info(isPeak, label, windowStr, secondsToSwitch, tzId)
    }

    /**
     * 计算距下次切换秒数（与 parsers/peak_window.py next_switch 口径一致）。
     * - 高峰中（且今天是高峰日）：到当前所在区间结束（end=24 视为次日 00:00）
     * - 空闲/周末：到下一个「高峰日」的第一个区间起点（最多向后找 7 天，跳过非高峰日）
     */
    fun secondsToNextSwitch(localNow: LocalDateTime, spec: PeakWindowSpec, isPeak: Boolean): Int {
        val sortedRanges = spec.hours.sortedBy { it.first }
        if (sortedRanges.isEmpty()) return 0

        return if (isPeak) {
            // 当前所在区间 → 到 endExclusive（IntRange 的 last 是 inclusive = end-1，所以 end = last+1）
            val cur = sortedRanges.firstOrNull { it.contains(localNow.hour) } ?: sortedRanges.last()
            val endHour = cur.last + 1  // [9,12) → endHour=12
            if (endHour >= 24) {
                // 跨零点：到次日 00:00
                val nextMidnight = localNow.toLocalDate().plusDays(1).atStartOfDay()
                java.time.Duration.between(localNow, nextMidnight).seconds.toInt().coerceAtLeast(0)
            } else {
                val minutesLeft = (endHour - localNow.hour) * 60 - localNow.minute
                (minutesLeft * 60 - localNow.second).coerceAtLeast(0)
            }
        } else {
            // 下一个高峰日的第一个区间起点（跳过非高峰日）
            val starts = sortedRanges.map { it.first }
            for (offset in 0..7L) {
                val day = localNow.toLocalDate().plusDays(offset)
                if (day.dayOfWeek.value !in spec.weekdays) continue
                val dayStarts = if (offset == 0L) starts.filter { it > localNow.hour } else starts
                val first = dayStarts.firstOrNull() ?: continue
                val target = day.atTime(first, 0)
                return java.time.Duration.between(localNow, target).seconds.toInt().coerceAtLeast(0)
            }
            0
        }
    }

    /** 把秒数格式化成简短文案（与 swiftbar/parsers/peak_window.py 的 format_countdown 一致） */
    fun formatCountdown(seconds: Int): String {
        if (seconds <= 0) return ""
        val h = seconds / 3600
        val rem = seconds % 3600
        val m = rem / 60
        return when {
            h > 0 && m > 0 -> "${h}h${m}m"
            h > 0 -> "${h}h"
            else -> "${m}m"
        }
    }
}