package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

class TrainBatchTest {
    @Test
    fun twoPersonalFactsAreOneSelfGroup() {
        val cat = ReviewedFact("我", "我的猫叫咪咪", "咪咪", listOf("我的猫叫什么名字？" to "咪咪"), emptyList(), attr = "猫的名字")
        val name = ReviewedFact("我", "我叫徐金朔", "徐金朔", listOf("我叫什么？" to "徐金朔"), emptyList(), attr = "名字")
        val groups = planTrainGroups(listOf(cat, name))
        assertEquals(1, groups.size)
        assertEquals(listOf("我的猫叫咪咪", "我叫徐金朔"), groups[0].map { it.statement })
        val root = Files.createTempDirectory("batch-self").toFile()
        val store = MemoryStore(root)
        store.ensure()
        assertEquals(SELF_EXPERT, store.expertNameFor(groups[0], "expert_999999"))
        val merged = store.factsForTrain(groups[0])
        assertEquals(setOf("我的猫叫咪咪", "我叫徐金朔"), merged.map { it.statement }.toSet())
        assertTrue(merged.all { it.entity == "我" })
    }

    @Test
    fun companyFactWaitsBehindTheSelfGroup() {
        val cat = ReviewedFact("我", "我的猫叫咪咪", "咪咪", emptyList(), emptyList())
        val company = ReviewedFact("塔佐巴洛", "塔佐巴洛公司成立于1978年。", "1978", emptyList(), emptyList())
        val groups = planTrainGroups(listOf(cat, company))
        assertEquals(2, groups.size)
        assertEquals(listOf("我的猫叫咪咪"), groups[0].map { it.statement })
        assertEquals(listOf("塔佐巴洛公司成立于1978年。"), groups[1].map { it.statement })
        val running = SavedBatch(groups.map { group -> group.map { it.statement } }, index = 0, phase = "running")
        assertEquals(
            listOf("我的猫叫咪咪" to "running", "塔佐巴洛公司成立于1978年。" to "queued"),
            batchMarks(running, "running"),
        )
        val queued = enqueueStatement(running, "佩莫公司的总部在特希市。")
        assertEquals(3, queued.groups.size)
        assertEquals(listOf("佩莫公司的总部在特希市。"), queued.groups[2])
        assertEquals(running, enqueueStatement(running, "我的猫叫咪咪"))
    }

    @Test
    fun finishedBatchMarksEveryFactDone() {
        val batch = SavedBatch(listOf(listOf("我的猫叫咪咪", "我叫徐金朔")), index = 0, phase = "done")
        assertEquals(
            listOf("我的猫叫咪咪" to "done", "我叫徐金朔" to "done"),
            batchMarks(batch, "done"),
        )
        val failed = batch.copy(phase = "running")
        assertEquals(
            listOf("我的猫叫咪咪" to "error", "我叫徐金朔" to "error"),
            batchMarks(failed, "error"),
        )
    }

    @Test
    fun batchFileRoundTrip() {
        val root = Files.createTempDirectory("batch-file").toFile()
        val store = MemoryStore(root)
        val batch = SavedBatch(listOf(listOf("我的猫叫咪咪", "我叫徐金朔")), 0, "running")
        TrainBatchStore.write(store, batch)
        assertEquals(batch, TrainBatchStore.read(store))
        TrainBatchStore.clear(store)
        assertEquals(null, TrainBatchStore.read(store))
    }
}
