package com.coffeelab.tokeneye.core

import android.content.Context
import android.util.Log

/**
 * 刷新引擎：并发拉取所有启用的 provider → 解析 → 告警判定 → 持久化快照。
 * 对应 token_eye.py 的 process_provider + alert_check + notify_recovered。
 */
object RefreshEngine {

    private const val TAG = "TokenEye"

    suspend fun refresh(context: Context, force: Boolean = false): Snapshot {
        val config = ConfigRepository.load(context)
        val secrets = SecretStore(context)
        val prev = SnapshotStore.load(context)
        val now = System.currentTimeMillis()

        // 告警解析需要全局 alerts，传入 parse
        val results = mutableListOf<ProviderResult>()
        val newSuccessAt = mutableMapOf<String, Long>()
        val alerted = prev.alertedIds.toMutableSet()

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
                val kind = fetch.errorKind ?: ErrorKind.NETWORK
                results.add(
                    ProviderResult(
                        p.id, p.name, Status.ERR,
                        "${errorLabel(kind)}：${fetch.message}",
                        listOf(errorLabel(kind), fetch.message),
                        consoleUrl = p.consoleUrl,
                    )
                )
                continue
            }

            val parsed = ResultParser.parse(p, fetch.data!!, config.alerts)
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
        return snapshot
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
