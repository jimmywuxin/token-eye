package com.coffeelab.tokeneye.work

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.glance.appwidget.updateAll
import com.coffeelab.tokeneye.core.RefreshEngine
import com.coffeelab.tokeneye.widget.TokenEyeWidget
import java.util.concurrent.TimeUnit

/**
 * 定时刷新（对应 SwiftBar 30s 轮询；Android 周期下限 15 分钟）。
 * 结束后主动更新小部件。
 *
 * 失败语义（2026-10-06 真机实测踩坑后定的方案）：
 * **任何一轮失败都排一个「失败接力」任务**（[enqueueRecovery]，延时 1 分钟），
 * 由它重试；接力任务再失败会排下一个（REPLACE 保证不互相挡）。
 *
 * 为什么不直接用 `Result.retry()`：WorkManager **周期任务不支持 retry**（会被忽略），
 * 周期下限又是 15 分钟、MIUI 省电还会往后压 —— 实测断网恢复后小部件3 分钟没更新，
 * 周期任务根本没被调起。`isPeriodic` 又在 `WorkRequest` 上、Worker 里取不到，
 * 所以统一用「失败 → 排接力」这一条路径，周期/一次性任务行为一致。
 *
 * 关键点：**不能无条件 success** —— 单平台失败在 `RefreshEngine` 内是 `continue`
 * （不抛异常），这里若也 success，WorkManager 认为任务正常完成，既不重试也不退避，
 * 断网一次后小部件就永久停在错误态。
 */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        // 周期任务不supports retry（WorkManager 会忽略），失败时靠[enqueueRecovery] 接力；
        // 一次性任务（手动点/ 失败接力）直接交给 WorkManager 的退避策略。
        // `isPeriodic` 在 WorkRequest 而非 Worker 上，取不到；用「是否周期性」无法判断，
        // 故统一走：失败 → 排接力 + success（接力任务本身失败会继续排下一轮，等价于退避）
        return try {
            val outcome = RefreshEngine.refresh(applicationContext, force = inputData.getBoolean(KEY_FORCE, false))
            // 无论成败都刷小部件：失败轮也会写入「上次数据 + 数据陈旧」的兜底显示
            TokenEyeWidget().updateAll(applicationContext)
            if (outcome.anyFailed) enqueueRecovery(applicationContext)
            Result.success()
        } catch (e: Exception) {
            Log.w(TAG, "refresh crashed, will retry", e)
            enqueueRecovery(applicationContext)
            Result.success()
        }
    }

    companion object {
        private const val TAG = "TokenEye"
        const val KEY_FORCE = "force"
        private const val PERIODIC_NAME = "token-eye-refresh"
        private const val ONESHOT_NAME = "token-eye-refresh-now"
        private const val RECOVERY_NAME = "token-eye-refresh-recovery"

        /**
         * 失败接力：延时 [RECOVERY_DELAY_MINUTES] 分钟跑一轮。
         * 延时给的是「网络恢复 + DNS 生效」的窗口，1 分钟起步、逐次翻倍到 15 分钟封顶
         * （与 WorkManager 默认退避节奏接近），避免断网期间疯狂重试打爆 API。
         */
        private const val RECOVERY_DELAY_MINUTES = 1L
        private const val RECOVERY_MAX_DELAY_MINUTES = 15L

        /** 周期刷新，全局唯一，重复调用安全（KEEP） */
        fun ensureScheduled(context: Context) {
            val request = PeriodicWorkRequestBuilder<RefreshWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        /**
         * 立即刷新一次（手动点「立即刷新」/ 小部件按钮）。
         *
         * 刻意**不传 force**：`force=true` 会跳过「陈旧项必须重拉」的判定，
         * 在 App 内反复点就变成纯打 API。首次点（无陈旧项）时行为与 force 一致。
         */
        fun refreshNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<RefreshWorker>().build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(ONESHOT_NAME, ExistingWorkPolicy.REPLACE, request)
        }

        /**
         * 排一个失败接力任务（任何一轮失败后调用）。
         *
         * 用 [ExistingWorkPolicy.REPLACE] 而非 KEEP：接力任务自己失败时会再排一个，
         * KEEP 会把它自己挡住（同名任务正处于运行态）→ 断网期间彻底停摆。
         * REPLACE 保证「最新一次失败排的最新接力」始终生效。
         */
        fun enqueueRecovery(context: Context) {
            val request = OneTimeWorkRequestBuilder<RefreshWorker>()
                .setInitialDelay(RECOVERY_DELAY_MINUTES, TimeUnit.MINUTES)
                .setBackoffCriteria(
                    androidx.work.BackoffPolicy.EXPONENTIAL,
                    RECOVERY_MAX_DELAY_MINUTES,
                    TimeUnit.MINUTES,
                )
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(RECOVERY_NAME, ExistingWorkPolicy.REPLACE, request)
            Log.i(TAG, "scheduled recovery in ${RECOVERY_DELAY_MINUTES}min")
        }

        /** 供外部（小部件/设置页）查询是否已排接力，不常用 */
        fun recoveryPending(context: Context): Boolean =
            WorkManager.getInstance(context)
                .getWorkInfosForUniqueWork(RECOVERY_NAME).get().any { !it.state.isFinished }
    }
}
