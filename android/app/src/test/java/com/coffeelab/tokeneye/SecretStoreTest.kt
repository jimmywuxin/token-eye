package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.KeyValueStore
import com.coffeelab.tokeneye.core.KeyValueStoreFactory
import com.coffeelab.tokeneye.core.SecretStore
import com.coffeelab.tokeneye.core.SecretStoreInvalidatedException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SecretStore 失效路径（纯 JVM）：用可注入的 fake 工厂模拟「加密主钥失效」，
 * 验证会清理失效状态并抛出明确的「需重新录入密钥」异常，而不是静默返回空 key。
 * 不依赖 Robolectric / Android Keystore / android.jar 异常实例。
 */
class SecretStoreTest {

    private class FakeStore : KeyValueStore {
        val data = mutableMapOf<String, String>()
        override fun getString(key: String, def: String): String = data[key] ?: def
        override fun putString(key: String, value: String) {
            data[key] = value
        }
        override fun remove(key: String) {
            data.remove(key)
        }
    }

    @Test
    fun normal_get_set_remove() {
        val store = FakeStore()
        val s = SecretStore.createForTest(object : KeyValueStoreFactory {
            override fun create(): KeyValueStore = store
            override fun resetInvalidated() {}
        })
        assertEquals("", s.get("deepseek"))
        s.set("deepseek", "sk-xxx")
        assertEquals("sk-xxx", s.get("deepseek"))
        s.remove("deepseek")
        assertEquals("", s.get("deepseek"))
    }

    @Test
    fun invalidated_key_resets_and_throws_explicit_exception() {
        var resetCalled = 0
        val factory = object : KeyValueStoreFactory {
            override fun create(): KeyValueStore {
                // 模拟 Android Keystore 抛 KeyPermanentlyInvalidatedException（用等价文案，
                // 纯 JVM 不依赖 android.jar 异常实例）
                throw RuntimeException("Key permanently invalidated")
            }
            override fun resetInvalidated() {
                resetCalled++
            }
        }
        val s = SecretStore.createForTest(factory)
        val ex = assertThrows(SecretStoreInvalidatedException::class.java) { s.get("deepseek") }
        assertEquals(1, resetCalled)
        assertTrue("错误文案应提示重新录入密钥，实际：${ex.message}", ex.message!!.contains("重新录入"))
    }

    @Test
    fun general_security_exception_also_treated_as_invalidation() {
        var resetCalled = 0
        val factory = object : KeyValueStoreFactory {
            override fun create(): KeyValueStore {
                throw java.security.GeneralSecurityException("keystore unavailable")
            }
            override fun resetInvalidated() {
                resetCalled++
            }
        }
        val s = SecretStore.createForTest(factory)
        assertThrows(SecretStoreInvalidatedException::class.java) { s.get("x") }
        assertEquals(1, resetCalled)
    }

    @Test
    fun unrelated_exception_is_not_swallowed_as_invalidation() {
        val factory = object : KeyValueStoreFactory {
            override fun create(): KeyValueStore = throw IllegalStateException("disk full")
            override fun resetInvalidated() {}
        }
        val s = SecretStore.createForTest(factory)
        // 非密钥失效异常不应被伪装成「需重新录入」，也不该触发 reset
        assertThrows(IllegalStateException::class.java) { s.get("x") }
    }
}
