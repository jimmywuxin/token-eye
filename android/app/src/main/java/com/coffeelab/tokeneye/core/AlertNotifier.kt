package com.coffeelab.tokeneye.core

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.coffeelab.tokeneye.MainActivity
import com.coffeelab.tokeneye.R

/** 告警/恢复通知（对应 osascript display notification） */
object AlertNotifier {

    private const val CHANNEL_ALERTS = "alerts"
    private const val CHANNEL_STATUS = "status"

    fun createChannels(context: Context) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ALERTS, "余额/用量告警", NotificationManager.IMPORTANCE_DEFAULT)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_STATUS, "恢复通知", NotificationManager.IMPORTANCE_LOW)
        )
    }

    private fun canNotify(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= 33) {
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED
        } else {
            NotificationManagerCompat.from(context).areNotificationsEnabled()
        }

    private fun build(context: Context, channel: String, title: String, message: String, id: Int) {
        if (!canNotify(context)) return
        val intent = Intent(context, MainActivity::class.java)
        val pi = PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_widget_logo)
            .setContentTitle(title)
            .setContentText(message)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(id, notification)
        } catch (e: SecurityException) {
            // 未授权通知权限，忽略
        }
    }

    fun notifyAlert(context: Context, name: String, current: String) {
        build(context, CHANNEL_ALERTS, "$name 低于阈值", "当前 $current", name.hashCode())
    }

    fun notifyRecovered(context: Context, name: String, current: String) {
        build(context, CHANNEL_STATUS, "$name 已恢复", "当前 $current", name.hashCode())
    }
}
