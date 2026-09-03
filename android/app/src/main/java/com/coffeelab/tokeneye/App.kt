package com.coffeelab.tokeneye

import android.app.Application
import com.coffeelab.tokeneye.core.AlertNotifier
import com.coffeelab.tokeneye.work.RefreshWorker

class App : Application() {

    override fun onCreate() {
        super.onCreate()
        AlertNotifier.createChannels(this)
        RefreshWorker.ensureScheduled(this)
    }
}
