package com.coffeelab.tokeneye.core

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.security.GeneralSecurityException

/**
 * 加密存储所需的极简键值接口：把 Android [SharedPreferences] 隔在实现层，
 * 让失效恢复编排能在纯 JVM 单测里用 fake 验证（无需 Robolectric / Android Keystore）。
 */
internal interface KeyValueStore {
    fun getString(key: String, def: String): String
    fun putString(key: String, value: String)
    fun remove(key: String)
}

/** 加密 prefs 工厂：create() 可能因密钥失效抛异常，resetInvalidated() 清理失效状态 */
internal interface KeyValueStoreFactory {
    fun create(): KeyValueStore
    fun resetInvalidated()
}

/**
 * 「需重新录入密钥」：加密主钥失效（改锁屏密码 / 备份恢复 / keyset 损坏）后抛出，
 * 由 RefreshEngine 转成可见错误行，不静默吞掉、也不返回空 key 冒充「未配置」。
 */
class SecretStoreInvalidatedException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * API Key 加密存储（Android Keystore 主钥 + EncryptedSharedPreferences，对应 Mac 版 Keychain）。
 *
 * 进程级单例（[getInstance]）：避免每轮 refresh 都 new 实例、重复打开加密 prefs。
 * 密钥失效时捕获 KeyPermanentlyInvalidatedException / GeneralSecurityException，
 * 删除失效的加密 prefs 文件与 MasterKey keyset 后抛 [SecretStoreInvalidatedException]。
 */
class SecretStore internal constructor(private val factory: KeyValueStoreFactory) {

    @Volatile
    private var cached: KeyValueStore? = null

    private fun store(): KeyValueStore {
        cached?.let { return it }
        return synchronized(this) {
            cached?.let { return it }
            try {
                factory.create().also { cached = it }
            } catch (e: Exception) {
                if (isKeyInvalidated(e)) {
                    // 清理失效状态，使下次调用能重建空的加密 prefs；
                    // 但本轮绝不静默降级，而是向上抛明确状态。
                    runCatching { factory.resetInvalidated() }
                    cached = null
                    throw SecretStoreInvalidatedException("加密密钥已失效，需重新录入密钥", e)
                }
                throw e
            }
        }
    }

    fun get(providerId: String): String = store().getString("key:$providerId", "")

    fun set(providerId: String, value: String) = store().putString("key:$providerId", value)

    fun remove(providerId: String) = store().remove("key:$providerId")

    companion object {
        @Volatile
        private var instance: SecretStore? = null

        fun getInstance(context: Context): SecretStore =
            instance ?: synchronized(this) {
                instance ?: SecretStore(AndroidKeyValueStoreFactory(context.applicationContext))
                    .also { instance = it }
            }

        /** 纯 JVM 单测注入 fake 工厂 */
        internal fun createForTest(factory: KeyValueStoreFactory): SecretStore = SecretStore(factory)

        /** 沿 cause 链判定是否为「加密主钥失效」类异常 */
        private fun isKeyInvalidated(e: Throwable): Boolean =
            generateSequence(e) { it.cause }.take(8).any { t ->
                // KeyPermanentlyInvalidatedException 继承链最终是 GeneralSecurityException
                t is GeneralSecurityException ||
                    t.javaClass.name.contains("KeyPermanentlyInvalidated") ||
                    t.javaClass.name.contains("AEADBadTag") ||
                    t.message?.contains("Key permanently invalidated", ignoreCase = true) == true
            }
    }
}

/** Android 实现：EncryptedSharedPreferences + MasterKey */
private class AndroidKeyValueStoreFactory(private val context: Context) : KeyValueStoreFactory {

    override fun create(): KeyValueStore {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        val prefs = EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
        return SharedPrefsStore(prefs)
    }

    override fun resetInvalidated() {
        // 1) 删除失效的 EncryptedSharedPreferences 文件
        runCatching { context.deleteSharedPreferences(PREFS_NAME) }
        // 2) 删除 MasterKey 的 Tink keyset（androidx.security.crypto 默认 SharedPreferences）
        runCatching { context.deleteSharedPreferences(MASTER_KEY_PREFS) }
        // 3) 从 Android Keystore 删除默认主钥别名，下次 create() 重新生成
        runCatching {
            val ks = java.security.KeyStore.getInstance("AndroidKeyStore")
            ks.load(null)
            ks.deleteEntry(MASTER_KEY_ALIAS)
        }
    }

    private companion object {
        const val PREFS_NAME = "token_eye_secrets"
        const val MASTER_KEY_PREFS = "__androidx_security_master_key_preference_set_"
        const val MASTER_KEY_ALIAS = "_androidx_security_master_key_"
    }
}

private class SharedPrefsStore(private val prefs: SharedPreferences) : KeyValueStore {
    override fun getString(key: String, def: String): String = prefs.getString(key, def) ?: def
    override fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }
    override fun remove(key: String) {
        prefs.edit().remove(key).apply()
    }
}
