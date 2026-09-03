package com.coffeelab.tokeneye.core

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** API Key 加密存储（Android Keystore 主钥 + EncryptedSharedPreferences，对应 Mac 版 Keychain） */
class SecretStore(context: Context) {

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "token_eye_secrets",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun get(providerId: String): String =
        prefs.getString("key:$providerId", "") ?: ""

    fun set(providerId: String, value: String) {
        prefs.edit().putString("key:$providerId", value).apply()
    }

    fun remove(providerId: String) {
        prefs.edit().remove("key:$providerId").apply()
    }

    fun configuredIds(): Set<String> =
        prefs.all.keys.filter { it.startsWith("key:") }.map { it.removePrefix("key:") }.toSet()
}
