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
 * 结束后主动更新小部件（含异常轮）。
 *
 * 失败语义（2026-10-06 真机实测踩坑后定的方案）：
 * **任何一轮失败都排一个「失败接力」任务**（[enqueueRecovery]），由它重试。
 *
 * 为什么不直接用 `Result.retry()`：WorkManager **周期任务不支持 retry**（会被忽略），
 * 周期下限又是 15 分钟、MIUI 省电还会往后压。`isPeriodic` 又在 WorkRequest 上、
 * Worker 里取不到，所以统一用「失败 → 排接力 + success」这一条路径。
 *
 * 接力延时由**连续失败次数**驱动，存在 SharedPreferences：1 → 2 → 4 → 8 → 15 分钟
 * 逐次翻倍、15 分钟封顶；任意一轮完全成功即清零（[clearFailStreak]）。
 * 断网期间不会每 1 分钟重试全部 API，网络恢复后又能较快收敛。`setBackoffCriteria`
 * 因接力任务同样不会 `Result.retry()` 而无效，故不再设置（注释与实现保持一致）。
 */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        return try {
            val outcome = RefreshEngine.refresh(applicationContext, force = inputData.getBoolean(KEY_FORCE, false))
            // 无论成败都刷小部件：失败轮也会写入「上次数据 + 数据陈旧」的兜底显示
            TokenEyeWidget().updateAll(applicationContext)
            if (outcome.anyFailed) {
                enqueueRecovery(applicationContext)
            } else {
                clearFailStreak(applicationContext)
            }
            Result.success()
        } catch (e: Exception) {
            Log.w(TAG, "refresh crashed, will retry", e)
            // 异常轮也要刷小部件：否则 refresh 崩溃时小部件完全不更新、用户无提示
            runCatching { TokenEyeWidget().updateAll(applicationContext) }
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
        private const val PREFS = "token_eye_worker"
        private const val KEY_FAIL_STREAK = "fail_streak"

        private fun prefs(context: Context) =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        /** 读 +1 + 存，返回新的连续失败次数 */
        private fun bumpFailStreak(context: Context): Int {
            val p = prefs(context)
            val next = p.getInt(KEY_FAIL_STREAK, 0) + 1
            p.edit().putInt(KEY_FAIL_STREAK, next).apply()
            return next
        }

        /** 一轮完全成功 → 连续失败计数清零（Worker 与 App 内手动刷新共用） */
        fun clearFailStreak(context: Context) {
            prefs(context).edit().putInt(KEY_FAIL_STREAK, 0).apply()
        }

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
         * 延时按连续失败次数递增（成功轮清零）；用 [ExistingWorkPolicy.REPLACE] 而非 KEEP：
         * 接力任务自己失败时会再排一个，KEEP 会把它自己挡住（同名任务正处于运行态）→
         * 断网期间彻底停摆。REPLACE 保证「最新一次失败排的最新接力」始终生效。
         */
        fun enqueueRecovery(context: Context) {
            val streak = bumpFailStreak(context)
            val delay = recoveryDelayMinutes(streak)
            val request = OneTimeWorkRequestBuilder<RefreshWorker>()
                .setInitialDelay(delay, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(RECOVERY_NAME, ExistingWorkPolicy.REPLACE, request)
            Log.i(TAG, "scheduled recovery in ${delay}min (consecutive failures=$streak)")
        }

        /** 供外部（小部件/设置页）查询是否已排接力，不常用 */
        fun recoveryPending(context: Context): Boolean =
            WorkManager.getInstance(context)
                .getWorkInfosForUniqueWork(RECOVERY_NAME).get().any { !it.state.isFinished }
    }
}

private const val RECOVERY_MAX_DELAY_MINUTES = 15L

/** 连续失败第 streak 次后的接力延时：1,2,4,8,15,15... 分钟（顶层纯函数，可纯 JVM 单测） */
internal fun recoveryDelayMinutes(streak: Int): Long {
    if (streak <= 1) return 1L
    var delay = 1L
    repeat((streak - 1).coerceAtMost(5)) {
        delay = (delay * 2).coerceAtMost(RECOVERY_MAX_DELAY_MINUTES)
    }
    return delay
}
