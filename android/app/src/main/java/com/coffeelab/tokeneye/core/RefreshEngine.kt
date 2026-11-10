package com.coffeelab.tokeneye.core

import android.content.Context
import android.util.Log
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext

/**
 * 刷新引擎：并发拉取所有启用的 provider → 解析 → 告警判定 → 持久化快照。
 * 对应 token_eye.py 的 process_provider + alert_check + notify_recovered。
 *
 * 整个 refresh 跑在 [Dispatchers.IO]：配置解析、Keystore 解密、快照 IO 都不落到
 * 调用方（Compose / WorkManager）的线程。网络拉取用 [coroutineScope] + async/awaitAll
 * 真并发；结果按 providers 顺序聚合、快照只写一次，避免并发写同一文件。
 */
object RefreshEngine {

    private const val TAG = "TokenEye"

    /** 陈旧提示行的前缀（用于去重：连续失败只保留最后一条，别堆成一长串） */
    private const val STALE_PREFIX = "⚠️ 更新失败："

    /** 刷新结果 = 快照 + 本轮是否有平台拉取失败（供 Worker 决定 retry）。 */
    data class Outcome(val snapshot: Snapshot, val anyFailed: Boolean)

    /** 并发阶段的单项中间结果：不写任何共享状态，聚合阶段串行处理 */
    private data class Item(
        val p: Provider,
        val result: ProviderResult,
        val failed: Boolean,
        val successAt: Long?,
        val data: JsonObject?,
        val evaluateAlert: Boolean,
    )

    suspend fun refresh(context: Context, force: Boolean = false): Outcome = withContext(Dispatchers.IO) {
        val config = ConfigRepository.load(context)
        val secrets = SecretStore.getInstance(context)
        val prev = SnapshotStore.load(context)
        // 中国法定节假日/调休表（assets/holidays/，仅 spec.holidays=true 的平台生效）
        val holidays = HolidayTable.load(context)
        val now = System.currentTimeMillis()
        val enabled = config.providers.filter { it.enabled }

        // 一次性读入所有密钥：进程级单例 + 单次解密，不在组合/循环里反复读加密 prefs。
        // 加密主钥失效时整轮转成「需重新录入密钥」的可见错误行，不静默、不发网络请求。
        val keys: Map<String, String> = try {
            enabled.associate { it.id to secrets.get(it.id) }
        } catch (e: SecretStoreInvalidatedException) {
            val snap = Snapshot(
                fetchedAt = now,
                results = enabled.map { keyInvalidatedResult(it) },
                successAt = prev.successAt,
                alertedIds = prev.alertedIds,
            )
            SnapshotStore.save(context, snap)
            return@withContext Outcome(snap, true)
        }

        // 阶段 1：真并发拉取 + 解析（每项只依赖入参，不写文件/不共享可变状态）。
        // map + awaitAll 都保序，结果与 config.providers 顺序一致。
        val items: List<Item> = coroutineScope {
            enabled.map { p ->
                async(Dispatchers.IO) {
                    computeItem(p, keys[p.id].orEmpty(), config, prev, holidays, now, force)
                }
            }.awaitAll()
        }

        // 阶段 2：按 providers 顺序串行聚合、判告警、一次写快照（避免并发写同一文件）
        val results = mutableListOf<ProviderResult>()
        val newSuccessAt = mutableMapOf<String, Long>()
        val alerted = prev.alertedIds.toMutableSet()
        var anyFailed = false
        for (item in items) {
            results.add(item.result)
            item.successAt?.let { newSuccessAt[item.p.id] = it }
            if (item.failed) {
                anyFailed = true
                Log.w(TAG, "refresh failed: ${item.p.id}")
            } else if (item.evaluateAlert) {
                evaluateAlert(context, item.p, item.result, config, alerted, item.data)
            }
        }

        val snapshot = Snapshot(
            fetchedAt = now,
            results = results,
            successAt = newSuccessAt,
            alertedIds = alerted.toList(),
        )
        SnapshotStore.save(context, snapshot)
        Outcome(snapshot, anyFailed)
    }

    /** 单个 provider 的拉取 + 解析（只依赖入参，可在任意 dispatcher 跑） */
    private suspend fun computeItem(
        p: Provider,
        key: String,
        config: EyeConfig,
        prev: Snapshot,
        holidays: Map<String, Boolean>,
        now: Long,
        force: Boolean,
    ): Item {
        if (key.isBlank()) {
            return Item(
                p,
                ProviderResult(p.id, p.name, Status.NOKEY, "未配置密钥", listOf("在应用内填写该平台的 API Key")),
                failed = false, successAt = null, data = null, evaluateAlert = false,
            )
        }

        // 缓存：未到期且非强制刷新时沿用上次结果。上一轮 stale 时必须重拉
        // （见 canReuse 注释，避免网络恢复那一轮被 TTL 挡住、永远停在陈旧态）。
        val ttl = (config.cacheTtl[p.parser.type] ?: 300L) * 1000
        val lastSuccess = prev.successAt[p.id] ?: 0L
        val prevResult = prev.results.firstOrNull { it.id == p.id }
        if (canReuse(force, prevResult, lastSuccess, now, ttl) && prevResult != null) {
            return Item(p, prevResult, failed = false, successAt = lastSuccess,
                data = null, evaluateAlert = false)
        }

        val fetch = ApiClient.fetch(
            url = p.api.url,
            method = p.api.method,
            authHeader = p.api.authHeader,
            authPrefix = p.api.authPrefix,
            key = key,
            extraHeaders = p.api.headers,
            envelope = p.api.envelope,
        )
        if (!fetch.ok) {
            val kind = fetch.errorKind ?: ErrorKind.NETWORK
            // successAt 保持「上次成功」的真实时间戳不变：失败不是成功。
            return Item(
                p, staleResult(p, prevResult, kind, fetch.message),
                failed = true,
                successAt = if (lastSuccess > 0L) lastSuccess else null,
                data = null, evaluateAlert = false,
            )
        }

        val parsed = ResultParser.parse(p, fetch.data!!, config.alerts, holidays)
        return Item(p, parsed, failed = false, successAt = now,
            data = fetch.data, evaluateAlert = true)
    }

    /** 加密密钥失效时的可见错误行（与「未配置密钥」区分，提示用户重新录入） */
    private fun keyInvalidatedResult(p: Provider) = ProviderResult(
        p.id, p.name, Status.ERR,
        "密钥已失效，请重新录入 API Key",
        listOf("加密密钥因修改锁屏密码或备份恢复失效", "请在 App 内重新填写该平台的 API Key"),
        consoleUrl = p.consoleUrl,
    )

    /**
     * 这次是否可以直接复用上次结果（纯函数，供单测）。
     *
     * 三个条件缺一不可：
     * - 非强制刷新
     * - 上次有结果
     * - **上次结果不是陈旧的** —— 否则网络刚恢复的那一轮若距上次「成功」不足 TTL
     *   （balance 300s），就会复用旧结果、压根不发请求 → anyFailed=false →
     *   Worker 报 SUCCESS → 不再重试 → 永远停在陈旧态（2026-10-06 真机实测踩到）
     * - 且距上次成功未超 TTL
     */
    fun canReuse(
        force: Boolean,
        prevResult: ProviderResult?,
        lastSuccess: Long,
        now: Long,
        ttlMillis: Long,
    ): Boolean = !force && prevResult != null && !prevResult.stale && now - lastSuccess < ttlMillis

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
            // 只保留最后一条失败说明：连续多轮失败时不要往 details 堆成一长串
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
        data: JsonObject?,
    ) {
        // 与解析层共用同一条阈值链（含 parser.fields.alertThreshold 一级），避免两处漂移
        val minBalance = ResultParser.resolveMinBalance(p, config.alerts, data)
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
