package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class TrainBatchTest {
    @Test
    fun twoPersonalFactsAreOneSelfGroup() {
        val cat = ReviewedFact("我", "我的猫叫咪咪", "咪咪", listOf("我的猫叫什么名字？" to "咪咪"), emptyList(), attr = "猫的名字")
        val name = ReviewedFact("我", "我叫徐金朔", "徐金朔", listOf("我叫什么？" to "徐金朔"), emptyList(), attr = "名字")
        val groups = planTrainGroups(listOf(cat, name))
        assertEquals(2, groups.size)
        assertEquals(listOf("我叫徐金朔"), groups[0].map { it.statement })
        assertEquals(listOf("我的猫叫咪咪"), groups[1].map { it.statement })
        val root = Files.createTempDirectory("batch-self").toFile()
        val store = MemoryStore(root)
        store.ensure()
        assertEquals(SELF_EXPERT, store.expertNameFor(groups[0], "expert_999999"))
        assertEquals(stableExpertId("咪咪"), store.expertNameFor(groups[1], "expert_999999"))
        val merged = store.factsForTrain(groups[0])
        assertEquals(listOf("我叫徐金朔"), merged.map { it.statement })
        assertTrue(merged.all { isAboutYou(it) })
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
    fun stuckWaitingBatchIsNotTrainingAndCanBeReset() {
        val four = listOf("我的猫叫咪咪", "我叫徐金朔", "我是徐金朔。", "我的猫猫叫咪咪")
        val batch = SavedBatch(listOf(four), index = 0, phase = "running")
        assertEquals(four.map { it to "waiting" }, batchMarks(batch, "waiting"))
        assertEquals(four.map { it to "queued" }, batchMarks(batch, ""))
        assertEquals(four.map { it to "running" }, batchMarks(batch, "running"))
        assertTrue(shouldRecoverBatch(batch, "waiting"))
        assertTrue(shouldRecoverBatch(batch, ""))
        assertTrue(shouldRecoverBatch(batch, "cancelled"))
        assertFalse(shouldRecoverBatch(batch, "running"))
        assertFalse(shouldRecoverBatch(batch, "done"))
        assertFalse(shouldRecoverBatch(batch, "error"))
        assertFalse(shouldRecoverBatch(null, "waiting"))
        assertFalse(TRAIN_WAITING_DETAIL.contains("整理页"))
        assertTrue(TRAIN_WAITING_DETAIL.contains("现在训练"))
        assertFalse(confirmTrainShown(false, "waiting", four.map { "waiting" }))
        assertFalse(confirmTrainShown(true, "running", four.map { "running" }))
        assertFalse(confirmTrainShown(false, "running", listOf("running", "queued")))
        assertTrue(confirmTrainShown(false, "error", listOf("error")))
        val behind = SavedBatch(listOf(four.take(2), four.drop(2)), 0, "running")
        assertEquals(
            listOf(
                "我的猫叫咪咪" to "waiting",
                "我叫徐金朔" to "waiting",
                "我是徐金朔。" to "queued",
                "我的猫猫叫咪咪" to "queued",
            ),
            batchMarks(behind, "waiting"),
        )
    }

    @Test
    fun successAfterAnEarlierFailureMovesRegisteredSelfFactsToDone() {
        val root = Files.createTempDirectory("batch-recover").toFile()
        val store = MemoryStore(root)
        store.ensure()
        val cat = "我的猫叫咪咪"
        val name = "我叫徐金朔"
        val batch = SavedBatch(listOf(listOf(cat, name)), 0, "error")
        TrainBatchStore.write(store, batch)
        assertEquals(listOf(cat to "error", name to "error"), batchMarks(batch, "error"))
        File(store.trainDir, "expert_self.gguf").writeBytes(
            byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte()) + ByteArray(32),
        )
        File(store.trainDir, "train.log").writeText("[gguf] wrote expert_self.gguf\n✅ Finetune finished.\n")
        File(store.trainDir, "status.json").writeText(
            trainSnapshotJson("done", "done", 20, 20, 4, 0.1788f, 250, "已登记 expert_self", ""),
        )
        File(store.trainDir, "job.json").writeText(
            """
            {"expert":"expert_self","rank":32,"facts":[
              {"entity":"我","attr":"猫的名字","statement":"我的猫叫咪咪","value":"咪咪","qa":[{"q":"我的猫叫什么名字？","a":"咪咪"}]},
              {"entity":"我","attr":"名字","statement":"我叫徐金朔","value":"徐金朔","qa":[{"q":"我叫什么？","a":"徐金朔"}]}
            ]}
            """.trimIndent(),
        )
        assertTrue(migrateFinishedTrain(store))
        val settled = TrainBatchStore.read(store)
        assertEquals("done", settled?.phase)
        assertEquals(listOf(cat to "done", name to "done"), batchMarks(settled!!, "done"))
        val experts = store.listExperts()
        assertEquals(listOf(SELF_EXPERT), experts.map { it.expert })
        val stored = store.readReviewedFacts(SELF_EXPERT).map { it.statement }.toSet()
        assertEquals(setOf(cat, name), stored)
        assertTrue(stored.all { store.readReviewedFacts(SELF_EXPERT).first { fact -> fact.statement == it }.entity == "我" })
        val who = EntityGround.reply("我是谁", EntityGround.load(store), "zh")
        assertTrue(who!!.answer.contains("徐金朔"))
        assertEquals(SELF_EXPERT, who.expert)
        val again = migrateFinishedTrain(store)
        assertFalse(again)
        val stranger = SavedBatch(listOf(listOf("塔佐巴洛公司成立于1978年。")), 0, "error")
        assertEquals(null, reconcileSucceededBatch(stranger, stored))
        assertEquals(listOf("塔佐巴洛公司成立于1978年。" to "error"), batchMarks(stranger, "done", succeeded = false))
        assertEquals(
            listOf(cat to "done", name to "done"),
            batchMarks(batch, "done", succeeded = true),
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
