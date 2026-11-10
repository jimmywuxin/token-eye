package com.coffeelab.tokeneye

import com.coffeelab.tokeneye.core.ProviderResult
import com.coffeelab.tokeneye.core.Snapshot
import com.coffeelab.tokeneye.core.SnapshotStore
import com.coffeelab.tokeneye.core.Status
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** SnapshotStore 原子写（纯 JVM，用临时目录，不依赖 Android Context） */
class SnapshotStoreTest {

    private fun tempDir(): File = Files.createTempDirectory("tokeneye-snapshot").toFile()

    @Test
    fun save_then_load_roundtrip() {
        val dir = tempDir()
        val snap = Snapshot(
            fetchedAt = 123456L,
            results = listOf(ProviderResult("deepseek", "DeepSeek", Status.OK, "¥9.93", balanceNum = 9.93)),
            successAt = mapOf("deepseek" to 123000L),
            alertedIds = listOf("minimax"),
        )
        assertTrue(SnapshotStore.saveToDir(dir, snap))
        val loaded = SnapshotStore.loadFromDir(dir)
        assertEquals(123456L, loaded.fetchedAt)
        assertEquals(1, loaded.results.size)
        assertEquals("¥9.93", loaded.results[0].summary)
        assertEquals(9.93, loaded.results[0].balanceNum!!, 0.001)
        assertEquals(123000L, loaded.successAt["deepseek"])
        assertEquals(listOf("minimax"), loaded.alertedIds)
    }

    @Test
    fun save_overwrites_old_and_leaves_no_tmp_file() {
        val dir = tempDir()
        // 先写一份「旧」快照
        assertTrue(SnapshotStore.saveToDir(dir, Snapshot(fetchedAt = 1L, results = emptyList())))
        // 再覆盖写，验证 renameTo 覆盖成功且不留 .tmp 残file
        val next = Snapshot(
            fetchedAt = 2L,
            results = listOf(ProviderResult("z", "Z", Status.WARN, "低", balanceNum = 1.0)),
        )
        assertTrue(SnapshotStore.saveToDir(dir, next))
        assertEquals(2L, SnapshotStore.loadFromDir(dir).fetchedAt)
        assertFalse("原子写不应残留 .tmp 文件", File(dir, "snapshot.json.tmp").exists())
    }

    @Test
    fun load_missing_or_corrupt_returns_empty_snapshot() {
        val dir = tempDir()
        assertTrue(SnapshotStore.loadFromDir(dir).results.isEmpty())
        File(dir, "snapshot.json").writeText("{ not json")
        assertTrue(SnapshotStore.loadFromDir(dir).results.isEmpty())
    }
}
