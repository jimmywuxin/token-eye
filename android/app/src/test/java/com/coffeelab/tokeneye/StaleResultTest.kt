package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ConfigLoader
import com.coffeelab.tokeneye.core.ErrorKind
import com.coffeelab.tokeneye.core.ProviderResult
import com.coffeelab.tokeneye.core.RefreshEngine
import com.coffeelab.tokeneye.core.Status
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 失败兜底显示（2026-10-06 修「小部件隔一段时间就卡在网络错误、不自愈」）。
 *
 * 背景：原来单平台拉取失败时把结果整条替换成 ERR 文案，**覆盖了快照**，
 * 而 `RefreshWorker` 又无条件 `Result.success()`（单平台失败在 refresh() 内是
 * continue、不抛异常）→ WorkManager 认为任务正常完成，不重试不退避。
 * 于是断网一次后，小部件的余额位置就一直显示「网络错误」。
 */
class StaleResultTest {

    private val provider = ConfigLoader.parse(
        """
        {"providers":[{"id":"deepseek","name":"DeepSeek",
          "api":{"url":"https://x"},
          "parser":{"type":"balance","fields":{"balance":"data.balance"}}}]}
        """.trimIndent()
    ).providers[0]

    private fun okResult(balance: Double) = ProviderResult(
        id = "deepseek", name = "DeepSeek", status = Status.OK,
        summary = "¥$balance", details = listOf("DeepSeek：¥$balance"),
        balanceNum = balance, consoleUrl = "https://console",
    )

    @Test
    fun keepsLastGoodData_marksStale() {
        // 有历史成功数据 → 余额照常显示，只置 stale 标记 + 追加失败说明
        val r = RefreshEngine.staleResult(provider, okResult(9.93), ErrorKind.NETWORK, "连接超时")
        assertEquals("¥9.93", r.summary)          // 数字没被「网络错误」顶掉
        assertEquals(9.93, r.balanceNum!!, 0.0001) // 余额字段仍可用于告警判定
        assertEquals(Status.OK, r.status)          // status 保持真实值，不被WARN 污染
        assertTrue("应标记为陈旧", r.stale)
        assertTrue(r.details.last().contains("更新失败"))
        assertTrue(r.details.last().contains("网络错误"))
    }

    @Test
    fun firstFetchFailure_hasNoFallback_showsError() {
        // 首轮就失败、无历史 → 只能显示错误本身
        val r = RefreshEngine.staleResult(provider, null, ErrorKind.NETWORK, "连接超时")
        assertEquals(Status.ERR, r.status)
        assertTrue(r.summary.contains("网络错误"))
        assertTrue("错误态不该标 stale（那是陈旧态）", !r.stale)
    }

    @Test
    fun previousAlsoError_doesNotKeepStaleError() {
        // 上次也是 ERR → 不再套一层，直接显示本轮错误（否则会永远套下去）
        val prevErr = ProviderResult(
            "deepseek", "DeepSeek", Status.ERR, "网络错误：上轮",
            listOf("网络错误"), consoleUrl = "https://console",
        )
        val r = RefreshEngine.staleResult(provider, prevErr, ErrorKind.TIMEOUT, "本轮超时")
        assertEquals(Status.ERR, r.status)
        assertTrue(r.summary.contains("请求超时"))
        assertEquals("本轮超时", r.summary.split("：").last())
    }

    @Test
    fun nokeyIsNotTreatedAsGoodData() {
        // NOKEY 态不是「成功数据」，失败时不该拿它当兜底
        val noKey = ProviderResult(
            "deepseek", "DeepSeek", Status.NOKEY, "未配置密钥", listOf("在应用内填写"),
        )
        val r = RefreshEngine.staleResult(provider, noKey, ErrorKind.NETWORK, "超时")
        assertEquals(Status.ERR, r.status)
    }

    @Test
    fun repeatedFailures_doNotStackDetails() {
        // 连续多轮失败：stale 幂等、不叠加 details 行（否则一次断网堆出一长串提示）
        val once = RefreshEngine.staleResult(provider, okResult(9.93), ErrorKind.NETWORK, "超时")
        val twice = RefreshEngine.staleResult(provider, once, ErrorKind.NETWORK, "超时")
        assertEquals(once.details.size, twice.details.size)
        assertTrue(twice.stale)
    }
}
