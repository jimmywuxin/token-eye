package com.coffeelab.tokeneye.core

import com.google.gson.JsonObject
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * 解析层，移植 token_eye.py parse_provider 的 balance / plan_usage 两类。
 * status 类型按 Key 有效性简化处理（HTTP 200 即可用）。
 */
object ResultParser {

    private const val DEFAULT_CURRENCY_SYMBOL = "¥"

    fun currencySymbol(display: DisplaySpec, currency: String?): String {
        val c = currency ?: "CNY"
        return display.currencySymbols[c]
            ?: (if (c == "USD") "$" else DEFAULT_CURRENCY_SYMBOL)
    }

    fun parse(
        p: Provider,
        data: JsonObject,
        globalAlerts: Map<String, AlertSpec> = emptyMap(),
        holidays: Map<String, Boolean> = emptyMap(),
    ): ProviderResult {
        return when (p.parser.type) {
            "balance" -> parseBalance(p, data, globalAlerts, holidays)
            "plan_usage" -> parsePlanUsage(p, data, globalAlerts)
            else -> parseStatus(p, data)
        }
    }

    fun parseBalance(
        p: Provider,
        data: JsonObject,
        globalAlerts: Map<String, AlertSpec> = emptyMap(),
        holidays: Map<String, Boolean> = emptyMap(),
    ): ProviderResult {
        val fields = p.parser.fields
        val rawBalance = resolveField(data, fields["balance"])
        val currency = resolveField(data, fields["currency"] ?: "currency")?.asStringOrNull() ?: "CNY"
        val symbol = currencySymbol(p.display, currency)
        val available = (resolveField(data, "is_available")).asBoolOrNull() ?: true
        val balanceNum = rawBalance.asDoubleOrNull()
        val balanceStr = balanceNum?.let { String.format("%.2f", it) } ?: rawBalance.asStringOrNull() ?: "?"
        val minBalance = resolveMinBalance(p, globalAlerts)

        val status = when {
            !available -> Status.WARN
            minBalance != null && balanceNum != null && balanceNum < minBalance -> Status.WARN
            balanceNum == null -> Status.ERR
            else -> Status.OK
        }
        val details = mutableListOf<String>().apply {
            add("${p.name}：$symbol$balanceStr")
            if (minBalance != null) add("阈值：$symbol${String.format("%.2f", minBalance)}（低于告警）")
            add("货币：$currency")
        }

        // 峰/谷时段标记（peakWindow）：summary 追加标签 + details 追加「状态 距下次切换 X」
        // 镜像 swiftbar/token_eye.py 的渲染；tz 名称非法时退回 Asia/Shanghai；时段计算失败静默跳过
        // spec.holidays=true 时叠加 assets/holidays/<年>.json 的法定节假日/调休（见 HolidayTable）
        var summary = "$symbol$balanceStr"
        p.parser.peakWindow?.let { spec ->
            try {
                val zone = try { ZoneId.of(spec.tz) } catch (e: Exception) { ZoneId.of("Asia/Shanghai") }
                val info = PeakWindow.classify(
                    LocalDateTime.now(zone), spec,
                    if (spec.holidays) holidays else emptyMap(),
                )
                summary = "$summary ${info.label}"
                val arrow = if (info.isPeak) "距空闲" else "距高峰"
                val cd = PeakWindow.formatCountdown(info.secondsToSwitch)
                details.add(if (cd.isEmpty()) info.windowStr else "${info.windowStr} $arrow $cd")
            } catch (_: Exception) { /* 渲染期异常兜底，不影响余额显示 */ }
        }

        return ProviderResult(
            id = p.id, name = p.name, status = status,
            summary = summary,
            details = details,
            balanceNum = balanceNum,
            consoleUrl = p.consoleUrl,
        )
    }

    /**
     * plan_usage：优先按剩余百分比字段推断状态（≥20 可用 / 10-20 耗尽临近 / <10 耗尽），
     * 与 Mac 版新接口口径一致；usedPct = 100 - remaining（pctDirection="remaining" 时翻转）。
     */
    fun parsePlanUsage(p: Provider, data: JsonObject, globalAlerts: Map<String, AlertSpec> = emptyMap()): ProviderResult {
        val parser = p.parser
        val fields = parser.fields
        val arr = (resolveField(data, parser.arrayPath))?.takeIf { it.isJsonArray }?.asJsonArray
        val showModels = parser.showModels
        val labels = parser.modelLabels
        val intervalLabel = parser.windowLabels["interval"] ?: "5h"
        val weeklyLabel = parser.windowLabels["weekly"] ?: "7d"

        if (arr == null || arr.size() == 0) {
            return ProviderResult(p.id, p.name, Status.ERR, "无套餐数据", listOf("接口未返回 model_remains"), consoleUrl = p.consoleUrl)
        }

        // 源数据口径由 parser.pctDirection 控制（默认 "remaining" = 接口返回剩余 %；
        // 未来有 provider 直接返回已用 % 时配 "used" 即可）。解析层统一翻成「已用 %」
        // 再分档/告警，与 Mac 侧 _to_used 口径一致。
        val toUsed = { raw: Double ->
            if (parser.pctDirection == "used") raw.coerceIn(0.0, 100.0)
            else (100.0 - raw).coerceIn(0.0, 100.0)
        }

        // 注：intervalStatus / weeklyStatus 是 AGENTS.md 标注的废弃字段（状态一律按已用 % 分档），
        // 此处不再读取——读了也从不上用，纯死配置。
        data class WindowVal(val rawPct: Double?, val boost: Double?, val resetMs: Double?)

        val byModel = arr.mapNotNull { el ->
            if (!el.isJsonObject) return@mapNotNull null
            val o = el.asJsonObject
            val model = resolveField(o, fields["model"])?.asStringOrNull() ?: return@mapNotNull null
            if (showModels != null && model !in showModels) return@mapNotNull null
            val label = labels[model] ?: ""
            val interval = WindowVal(
                rawPct = resolveField(o, fields["intervalPct"])?.asDoubleOrNull(),
                boost = resolveField(o, fields["intervalBoost"])?.asDoubleOrNull(),
                resetMs = resolveField(o, fields["resetMs"])?.asDoubleOrNull(),
            )
            val weekly = WindowVal(
                rawPct = resolveField(o, fields["weeklyPct"])?.asDoubleOrNull(),
                boost = resolveField(o, fields["weeklyBoost"])?.asDoubleOrNull(),
                resetMs = null,
            )
            model to (label to (interval to weekly))
        }.toMap()

        if (byModel.isEmpty()) {
            return ProviderResult(p.id, p.name, Status.ERR, "无可用模型", consoleUrl = p.consoleUrl)
        }

        // 取主模型（showModels 第一个或首个）作为小部件摘要
        val mainModel = showModels?.firstOrNull { it in byModel } ?: byModel.keys.first()
        val (mainLabel, mainWindows) = byModel[mainModel]!!
        val (interval, weekly) = mainWindows
        val intervalUsed = interval.rawPct?.let(toUsed)
        val weeklyUsed = weekly.rawPct?.let(toUsed)

        // 分档与 Mac 侧（swiftbar/token_eye.py 的 USED_WARN_PCT=80 / USED_OVER_PCT=100）对齐：
        // 已用 <80 → OK，80-99 → WARN，≥100 耗尽 → ERR
        fun usedStatus(used: Double?): Status = when {
            used == null -> Status.ERR
            used >= 100.0 -> Status.ERR
            used >= 80.0 -> Status.WARN
            else -> Status.OK
        }

        // 取最差：Status 枚举序为 OK<WARN<ERR< NOKEY，ordinal 越大越差 → 必须 maxBy
        // （曾误用 minBy，等于取最好：interval 正常 + weekly 无数据时整体判 OK 显示绿色）
        val worst = listOf(usedStatus(intervalUsed), usedStatus(weeklyUsed))
            .maxByOrNull { it.ordinal } ?: Status.ERR

        val summaryParts = mutableListOf<String>()
        intervalUsed?.let { summaryParts.add("$intervalLabel 剩${formatPct(100 - it)}%") }
        weeklyUsed?.let { summaryParts.add("$weeklyLabel 剩${formatPct(100 - it)}%") }

        val details = byModel.entries.flatMap { (model, pair) ->
            val (label, windows) = pair
            val shown = (if (label.isBlank()) model else "$model $label")
            buildList {
                add(shown)
                windows.first.rawPct?.let { add("  $intervalLabel 剩余 ${formatPct(100 - toUsed(it))}%（已用 ${formatPct(toUsed(it))}%）") }
                windows.second.rawPct?.let { add("  $weeklyLabel 剩余 ${formatPct(100 - toUsed(it))}%（已用 ${formatPct(toUsed(it))}%）") }
                windows.first.boost?.let { add("  5h 加速 ${formatPct(it / 10)}‰") }
                windows.first.resetMs?.let { add("  重置于 ${PeakWindow.formatCountdown((it.toLong() / 1000).toInt())}") }
            }
        }

        // 告警基准：与 Mac 侧一致取「已用 %」，主模型 interval 为准（无数据按 0 已用 → 必然触发告警）
        val usedForAlert = intervalUsed ?: 0.0
        val minPct = p.alert?.minPct ?: resolveMinPct(p, globalAlerts)
        val status = if (minPct != null && usedForAlert >= minPct) Status.WARN else worst

        return ProviderResult(
            id = p.id, name = p.name, status = status,
            summary = summaryParts.joinToString(" · ").ifBlank { "无数据" },
            details = details,
            usedPct = usedForAlert,
            consoleUrl = p.consoleUrl,
        )
    }

    fun parseStatus(p: Provider, data: JsonObject): ProviderResult {
        val actual = resolveField(data, p.parser.okField)?.asStringOrNull()
        val ok = if (p.parser.okValue.isNotBlank()) actual == p.parser.okValue else actual != null
        val label = p.display.label.ifBlank { "可用" }
        return ProviderResult(
            id = p.id, name = p.name,
            status = if (ok) Status.OK else Status.ERR,
            summary = label,
            details = listOf(if (ok) "API Key 有效" else "API Key 无效"),
            consoleUrl = p.consoleUrl,
        )
    }

    /** 阈值链：provider.alert.minBalance > 全局 alerts.{id}.minBalance > parser.defaultMinBalance */
    private fun resolveMinBalance(p: Provider, globalAlerts: Map<String, AlertSpec>): Double? =
        p.alert?.minBalance ?: globalAlerts[p.id]?.minBalance ?: p.parser.defaultMinBalance

    private fun resolveMinPct(p: Provider, globalAlerts: Map<String, AlertSpec>): Double? =
        p.alert?.minPct ?: globalAlerts[p.id]?.minPct

    private fun formatPct(v: Double): String =
        if (v == v.toLong().toDouble()) v.toLong().toString() else String.format("%.1f", v)
}
