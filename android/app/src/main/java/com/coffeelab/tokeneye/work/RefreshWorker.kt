package com.coffeelab.tokeneye.work

import android.content.Context
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
 * 定时刷新（对应 SwiftBar 30s 轮询；Android 系统下限 15 分钟）。
 * 结束后主动更新小部件。
 */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        return try {
            RefreshEngine.refresh(applicationContext, force = inputData.getBoolean(KEY_FORCE, false))
            TokenEyeWidget().updateAll(applicationContext)
            Result.success()
        } catch (e: Exception) {
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
