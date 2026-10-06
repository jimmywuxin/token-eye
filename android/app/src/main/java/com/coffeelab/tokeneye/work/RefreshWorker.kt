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
 * 定时刷新（对应 SwiftBar 30s轮询；Android 周期下限 15 分钟）。
 * 结束后主动更新小部件。
 *
 * 失败语义：只要有平台没拉成功就返回 `Result.retry()`，让 WorkManager 按退避策略
 * 尽快再试。**不能无条件 success** —— 单平台失败在 `RefreshEngine` 内是
 * `continue`（不抛异常），这里若也 success，WorkManager 会认为任务正常完成、
 * 既不重试也不退避，断网一次后小部件就永久停在错误态（2026-10-06 实测症状）。
 */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        return try {
            val outcome = RefreshEngine.refresh(applicationContext, force = inputData.getBoolean(KEY_FORCE, false))
            // 无论成败都刷小部件：失败轮也会写入「上次数据 + 更新失败」的兜底显示
            TokenEyeWidget().updateAll(applicationContext)
            if (outcome.anyFailed) Result.retry() else Result.success()
        } catch (e: Exception) {
            Log.w("TokenEye", "refresh crashed, will retry", e)
            Result.retry()
        }
    }

    companion object {
        const val KEY_FORCE = "force"
        private const val PERIODIC_NAME = "token-eye-refresh"
        private const val ONESHOT_NAME = "token-eye-refresh-now"

        /** 周期刷新，全局唯一，重复调用安全（KEEP） */
        fun ensureScheduled(context: Context) {
            val request = PeriodicWorkRequestBuilder<RefreshWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        /** 立即刷新一次（手动触发 / 小部件按钮） */
        fun refreshNow(context: Context, force: Boolean = true) {
            val request = OneTimeWorkRequestBuilder<RefreshWorker>()
                .setInputData(androidx.work.Data.Builder().putBoolean(KEY_FORCE, force).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(ONESHOT_NAME, ExistingWorkPolicy.REPLACE, request)
        }
    }
}
