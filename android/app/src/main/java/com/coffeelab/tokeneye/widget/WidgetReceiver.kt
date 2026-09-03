package com.coffeelab.tokeneye.widget

import android.content.Context
import android.appwidget.AppWidgetManager
import android.content.Intent
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

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == "android.appwidget.action.APPWIDGET_ENABLED") {
            RefreshWorker.ensureScheduled(context)
        }
    }
}
