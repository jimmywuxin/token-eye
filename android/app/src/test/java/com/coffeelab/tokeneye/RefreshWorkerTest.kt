package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.work.recoveryDelayMinutes
import org.junit.Assert.assertEquals
import org.junit.Test

/** 失败接力退避：连续失败次数驱动 1→2→4→8→15 分钟封顶（顶层纯函数，纯 JVM 可测） */
class RefreshWorkerTest {

    @Test
    fun recovery_delay_doubles_then_caps_at_15() {
        assertEquals(1L, recoveryDelayMinutes(0))
        assertEquals(1L, recoveryDelayMinutes(1))
        assertEquals(2L, recoveryDelayMinutes(2))
        assertEquals(4L, recoveryDelayMinutes(3))
        assertEquals(8L, recoveryDelayMinutes(4))
        assertEquals(15L, recoveryDelayMinutes(5))
        assertEquals(15L, recoveryDelayMinutes(10))
        assertEquals(15L, recoveryDelayMinutes(100))
    }
}
