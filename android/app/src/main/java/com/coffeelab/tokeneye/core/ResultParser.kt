package com.coffeelab.tokeneye.core

import com.google.gson.JsonObject

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

    fun parse(p: Provider, data: JsonObject, globalAlerts: Map<String, AlertSpec> = emptyMap()): ProviderResult {
        return when (p.parser.type) {
            "balance" -> parseBalance(p, data, globalAlerts)
            "plan_usage" -> parsePlanUsage(p, data, globalAlerts)
            else -> parseStatus(p, data)
        }
    }

    fun parseBalance(p: Provider, data: JsonObject, globalAlerts: Map<String, AlertSpec> = emptyMap()): ProviderResult {
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
        val details = buildList {
            add("${p.name}：$symbol$balanceStr")
            if (minBalance != null) add("阈值：$symbol${String.format("%.2f", minBalance)}（低于告警）")
            add("货币：$currency")
        }
        return ProviderResult(
            id = p.id, name = p.name, status = status,
            summary = "$symbol$balanceStr",
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

        data class WindowVal(val remaining: Double?, val statusText: String, val boost: Double?, val resetMs: Double?)

        val byModel = arr.mapNotNull { el ->
            if (!el.isJsonObject) return@mapNotNull null
            val o = el.asJsonObject
            val model = resolveField(o, fields["model"])?.asStringOrNull() ?: return@mapNotNull null
            if (showModels != null && model !in showModels) return@mapNotNull null
            val label = labels[model] ?: ""
            val interval = WindowVal(
                remaining = resolveField(o, fields["intervalPct"])?.asDoubleOrNull(),
                statusText = resolveField(o, fields["intervalStatus"])?.asStringOrNull() ?: "",
                boost = resolveField(o, fields["intervalBoost"])?.asDoubleOrNull(),
                resetMs = resolveField(o, fields["resetMs"])?.asDoubleOrNull(),
            )
            val weekly = WindowVal(
                remaining = resolveField(o, fields["weeklyPct"])?.asDoubleOrNull(),
                statusText = resolveField(o, fields["weeklyStatus"])?.asStringOrNull() ?: "",
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

        fun remainingStatus(r: Double?): Status = when {
            r == null -> Status.ERR
            r >= 20.0 -> Status.OK
            r >= 10.0 -> Status.WARN
            else -> Status.WARN  // 剩余 <10 视为耗尽临近/耗尽，统一 WARN 呈现
        }

        val worst = listOf(remainingStatus(interval.remaining), remainingStatus(weekly.remaining))
            .minByOrNull { it.ordinal } ?: Status.ERR

        val summaryParts = mutableListOf<String>()
        interval.remaining?.let { summaryParts.add("$intervalLabel 剩${formatPct(it)}%") }
        weekly.remaining?.let { summaryParts.add("$weeklyLabel 剩${formatPct(it)}%") }

        val details = byModel.entries.flatMap { (model, pair) ->
            val (label, windows) = pair
            val shown = (if (label.isBlank()) model else "$model $label")
            buildList {
                add(shown)
                windows.first.remaining?.let { add("  $intervalLabel 剩余 ${formatPct(it)}%（已用 ${formatPct(100 - it)}%）") }
                windows.second.remaining?.let { add("  $weeklyLabel 剩余 ${formatPct(it)}%（已用 ${formatPct(100 - it)}%）") }
                windows.first.boost?.let { add("  5h 加速 ${formatPct(it / 10)}‰") }
                windows.first.resetMs?.let { add("  重置于 ${formatMs(it.toLong())}") }
            }
        }

        val usedForAlert = 100 - (interval.remaining ?: 100.0)
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

    fun parse(p: Provider, data: JsonObject): ProviderResult = when (p.parser.type) {
        "balance" -> parseBalance(p, data)
        "plan_usage" -> parsePlanUsage(p, data)
        else -> parseStatus(p, data)
    }

    /** 阈值链：provider.alert.minBalance > 全局 alerts.{id}.minBalance > parser.defaultMinBalance */
    private fun resolveMinBalance(p: Provider, globalAlerts: Map<String, AlertSpec>): Double? =
        p.alert?.minBalance ?: globalAlerts[p.id]?.minBalance ?: p.parser.defaultMinBalance

    private fun resolveMinPct(p: Provider, globalAlerts: Map<String, AlertSpec>): Double? =
        p.alert?.minPct ?: globalAlerts[p.id]?.minPct

    private fun formatPct(v: Double): String =
        if (v == v.toLong().toDouble()) v.toLong().toString() else String.format("%.1f", v)

    private fun formatMs(ms: Long): String {
        val sec = ms / 1000
        val h = sec / 3600
        val m = (sec % 3600) / 60
        return if (h > 0) "${h}h${m}m" else "${m}m"
    }
}
