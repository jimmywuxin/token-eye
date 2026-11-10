package com.coffeelab.tokeneye.widget

import android.content.Context
import android.appwidget.AppWidgetManager
import android.content.Intent
import android.util.Log
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import com.coffeelab.tokeneye.work.RefreshWorker

class WidgetReceiver : GlanceAppWidgetReceiver() {

    override val glanceAppWidget: GlanceAppWidget = TokenEyeWidget()

    override fun onEnabled(context: Context) {
        super.onEnabled(context)
        RefreshWorker.ensureScheduled(context)
    }

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        super.onUpdate(context, appWidgetManager, appWidgetIds)
        RefreshWorker.ensureScheduled(context)
    }

    /**
     * receiver 必须 `exported=true` 才能收到系统 AppWidgetManager 的广播（否则小部件
     * 无法正常添加/更新），因此**不能加自定义 signature permission**（会挡掉系统广播）。
     * 改为在入口校验 intent 来源特征：只放行 AppWidget / Glance 命名空间的 action，
     * 忽略来路不明的自定义广播（它最多只能触发一次幂等的 ensureScheduled）。
     */
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action == null || !isTrustedAction(action)) {
            runCatching { Log.w(TAG, "ignored non-appwidget broadcast") }
            return
        }
        super.onReceive(context, intent)
        if (action == AppWidgetManager.ACTION_APPWIDGET_ENABLED) {
            RefreshWorker.ensureScheduled(context)
        }
    }

    private companion object {
        const val TAG = "TokenEye"
        fun isTrustedAction(action: String): Boolean =
            action.startsWith("android.appwidget.action.") ||
                action.startsWith("androidx.glance.")
    }
}
