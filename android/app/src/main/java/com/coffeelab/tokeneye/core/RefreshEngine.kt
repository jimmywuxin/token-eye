package com.coffeelab.tokeneye.core

import android.content.Context
import android.util.Log

/**
 * 刷新引擎：并发拉取所有启用的 provider → 解析 → 告警判定 → 持久化快照。
 * 对应 token_eye.py 的 process_provider + alert_check + notify_recovered。
 */
object RefreshEngine {

    private const val TAG = "TokenEye"

    /** 陈旧提示行的前缀（用于去重：连续失败只保留最后一条，别堆成一长串） */
    private const val STALE_PREFIX = "⚠️ 更新失败："

    /** 刷新结果 = 快照 + 本轮是否有平台拉取失败（供 Worker 决定 retry）。 */
    data class Outcome(val snapshot: Snapshot, val anyFailed: Boolean)

    suspend fun refresh(context: Context, force: Boolean = false): Outcome {
        val config = ConfigRepository.load(context)
        val secrets = SecretStore(context)
        val prev = SnapshotStore.load(context)
        // 中国法定节假日/调休表（assets/holidays/，仅 spec.holidays=true 的平台生效）
        val holidays = HolidayTable.load(context)
        val now = System.currentTimeMillis()

        // 告警解析需要全局 alerts，传入 parse
        val results = mutableListOf<ProviderResult>()
        val newSuccessAt = mutableMapOf<String, Long>()
        val alerted = prev.alertedIds.toMutableSet()
        var anyFailed = false

        for (p in config.providers.filter { it.enabled }) {
            val key = secrets.get(p.id)
            if (key.isBlank()) {
                results.add(ProviderResult(p.id, p.name, Status.NOKEY, "未配置密钥", listOf("在应用内填写该平台的 API Key")))
                continue
            }

            // 缓存：未到期且非强制刷新时沿用上次结果
            val ttl = (config.cacheTtl[p.parser.type] ?: 300L) * 1000
            val lastSuccess = prev.successAt[p.id] ?: 0L
            val prevResult = prev.results.firstOrNull { it.id == p.id }
            if (!force && prevResult != null && now - lastSuccess < ttl) {
                results.add(prevResult)
                newSuccessAt[p.id] = lastSuccess
                continue
            }

            val fetch = ApiClient.fetch(
                url = p.api.url,
                method = p.api.method,
                authHeader = p.api.authHeader,
                authPrefix = p.api.authPrefix,
                key = key,
                extraHeaders = p.api.headers,
            )
            if (!fetch.ok) {
                anyFailed = true
                val kind = fetch.errorKind ?: ErrorKind.NETWORK
                results.add(staleResult(p, prevResult, kind, fetch.message))
                // successAt 保持「上次成功」的真实时间戳不变：失败不是成功。
                // 下一轮照常判定过期 → 会重新拉取（这是想要的），真正的快速自愈
                // 靠 Worker 的 Result.retry() 退避，不靠伪造时间戳。
                if (lastSuccess > 0L) newSuccessAt[p.id] = lastSuccess
                Log.w(TAG, "refresh failed: ${p.id} ${errorLabel(kind)}")
                continue
            }

            val parsed = ResultParser.parse(p, fetch.data!!, config.alerts, holidays)
            results.add(parsed)
            newSuccessAt[p.id] = now
            evaluateAlert(context, p, parsed, config, alerted)
        }

        val snapshot = Snapshot(
            fetchedAt = now,
            results = results,
            successAt = newSuccessAt,
            alertedIds = alerted.toList(),
        )
        SnapshotStore.save(context, snapshot)
        return Outcome(snapshot, anyFailed)
    }

    /**
     * 拉取失败时该展示什么（纯函数，可单测—— 原来这段逻辑埋在 refresh() 里，
     * 依赖 Context + 真实网络，没法验证）。
     *
     * 有上次**成功**数据 → 原样保留 summary（余额/百分比照常显示，用户最需要的），
     * 只置 [ProviderResult.stale] 让 UI 提示「数据陈旧」；
     * 没有可用历史（首轮就失败 / 上次是 NOKEY 或 ERR）→ 只能显示错误本身。
     *
     * status 刻意不动：数据本身没变（余额还是那个余额），降成 WARN 会与「余额真的
     * 低于阈值」的告警混淆，且连续多轮失败会叠加放大。
     */
    fun staleResult(
        p: Provider,
        prevResult: ProviderResult?,
        kind: ErrorKind,
        message: String,
    ): ProviderResult {
        val label = errorLabel(kind)
        // 只有 OK / WARN（真实数据）才能兜底：NOKEY 是「未配置密钥」不是数据，
        // ERR 是上轮的错误信息 —— 拿它们兜底会让错误态套错误态、永不平息
        val hasGoodData = prevResult != null &&
            (prevResult.status == Status.OK || prevResult.status == Status.WARN)
        return if (hasGoodData) {
            // 只保留最后一条失败说明：连续多轮失败时不要往details 堆成一长串
            val kept = prevResult!!.details.filterNot { it.startsWith(STALE_PREFIX) }
            prevResult.copy(
                stale = true,
                details = kept + "$STALE_PREFIX$label",
            )
        } else {
            ProviderResult(
                p.id, p.name, Status.ERR,
                "$label：$message",
                listOf(label, message),
                consoleUrl = p.consoleUrl,
            )
        }
    }

    /** 阈值告警 + 恢复通知，alertedIds 去重（对应 flag 文件机制） */
    private fun evaluateAlert(
        context: Context,
        p: Provider,
        result: ProviderResult,
        config: EyeConfig,
        alerted: MutableSet<String>,
    ) {
        val minBalance = p.alert?.minBalance ?: config.alerts[p.id]?.minBalance ?: p.parser.defaultMinBalance
        val minPct = p.alert?.minPct ?: config.alerts[p.id]?.minPct

        val isLow = when {
            minBalance != null && result.balanceNum != null -> result.balanceNum!! < minBalance
            minPct != null && result.usedPct != null -> result.usedPct!! >= minPct
            else -> false
        }
        val wasAlerted = p.id in alerted

        if (isLow && !wasAlerted) {
            AlertNotifier.notifyAlert(context, p.name, result.summary)
            alerted.add(p.id)
            Log.d(TAG, "alert sent: ${p.id}")
        } else if (!isLow && wasAlerted) {
            AlertNotifier.notifyRecovered(context, p.name, result.summary)
            alerted.remove(p.id)
            Log.d(TAG, "recovery sent: ${p.id}")
        }
    }
}
