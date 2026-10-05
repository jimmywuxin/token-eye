package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.ConfigRepository
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 配置来源的约定（2026-10-05 删除 filesDir 覆盖机制后新增）。
 *
 * 背景：旧实现是「filesDir/providers.json（用户剪贴板导入）> assets 内置版」，
 * 遮蔽一旦建立就永不过期 —— 启用/停用开关也会往 filesDir 写整份配置，
 * 于是「点一次开关」就能让手机端配置永久停在旧版本。今天 Android 节假日期间
 * 峰谷倒计时误判为工作日，根因就是这份被遮蔽住的旧配置缺 `peakWindow.holidays`。
 *
 * 现在的约定：配置本体**只有** assets 一份，运行时唯一可改的是启用状态。
 */
class ConfigRepositoryTest {

    private val twoProviders = """
        {"providers":[
          {"id":"alpha","name":"Alpha",
            "api":{"url":"https://a.example.com"},
            "parser":{"type":"balance","fields":{"balance":"b"}}},
          {"id":"beta","name":"Beta","enabled":false,
            "api":{"url":"https://b.example.com"},
            "parser":{"type":"balance","fields":{"balance":"b"}}}
        ]}
    """.trimIndent()

    @Test
    fun no_overrides_keeps_config_as_is() {
        val config = ConfigLoader.parse(twoProviders)
        val out = ConfigRepository.applyEnabledOverrides(config, emptyMap())
        assertEquals(listOf("alpha", "beta"), out.providers.map { it.id })
        // 配置里 beta 显式 enabled=false，不带覆盖时应原样保留
        assertTrue(out.providers[0].enabled)
        assertFalse(out.providers[1].enabled)
    }

    @Test
    fun override_disables_a_platform() {
        val config = ConfigLoader.parse(twoProviders)
        val out = ConfigRepository.applyEnabledOverrides(config, mapOf("alpha" to false))
        assertFalse("覆盖应把 alpha 关掉", out.providers[0].enabled)
        assertFalse(out.providers[1].enabled)
    }

    @Test
    fun override_can_reenable_platform_disabled_in_config() {
        val config = ConfigLoader.parse(twoProviders)
        val out = ConfigRepository.applyEnabledOverrides(config, mapOf("beta" to true))
        assertTrue("覆盖应能把配置里关掉的 beta 打开", out.providers[1].enabled)
    }

    @Test
    fun override_only_touches_enabled_and_never_drops_providers() {
        val config = ConfigLoader.parse(twoProviders)
        val out = ConfigRepository.applyEnabledOverrides(config, mapOf("alpha" to false))
        // 平台数量、id、name、api.url 都不能因叠加覆盖而变化 —— 覆盖只该动 enabled
        assertEquals(2, out.providers.size)
        assertEquals("alpha", out.providers[0].id)
        assertEquals("Alpha", out.providers[0].name)
        assertEquals("https://a.example.com", out.providers[0].api.url)
        // peakWindow 这类配置本体字段也不该被覆盖动过
        assertEquals(null, out.providers[0].parser.peakWindow)
    }

    @Test
    fun unknown_id_in_overrides_is_ignored() {
        val config = ConfigLoader.parse(twoProviders)
        val out = ConfigRepository.applyEnabledOverrides(config, mapOf("ghost" to false))
        assertEquals(2, out.providers.size)
        assertTrue(out.providers[0].enabled)
    }
}
