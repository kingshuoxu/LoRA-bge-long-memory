package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TrainReportTest {
    private fun lowMemory(process: String = "com.lorabge.memory:train", at: Long = 80) = TrainExit(
        reason = TRAIN_EXIT_LOW_MEMORY,
        reasonName = "LOW_MEMORY",
        status = 9,
        description = "lmk",
        importance = 125,
        pssKb = 1_800_000,
        rssKb = 2_400_000,
        timestampMs = at,
        process = process,
    )

    @Test
    fun lowMemoryIsAPlainChineseCard() {
        val exit = lowMemory()
        assertEquals("内存不足被系统终止", trainFailurePhrase(exit))
        val signaled = exit.copy(reason = TRAIN_EXIT_SIGNALED, reasonName = "SIGNALED", description = "low memory killer")
        assertEquals("内存不足被系统终止", trainFailurePhrase(signaled))
        assertEquals("内存不足被系统终止", trainFailurePhrase(exitFromChildCode(137)))
        assertEquals("训练进程崩溃", trainFailurePhrase(exitFromChildCode(128 + 11)))
        assertTrue(trainFailurePhrase(null).contains("训练进程已经停住"))
        val shown = formatTrainProgress("zh", TrainSnapshot(state = "error", detail = trainFailurePhrase(exit), logTail = ""))
        assertTrue(shown.contains("失败"))
        assertTrue(shown.contains("内存不足被系统终止"))
        assertFalse(shown.contains("训练进程已经停住"))
        assertFalse(shown.contains("lmk"))
        assertFalse(shown.contains("LOW_MEMORY"))
        assertFalse(shown.contains("signal"))
    }

    @Test
    fun diagnosticsCarryConfigProgressExitAndLog() {
        val config = TrainConfig(
            rank = 8,
            seqLen = 64,
            batch = 1,
            gradAccum = 1,
            backend = "CPU",
            threads = 1,
            chatReleased = true,
            startedMs = 10,
        )
        val snap = TrainSnapshot(
            state = "error",
            stage = "train",
            step = 2,
            total = 12,
            epoch = 1,
            epochs = 4,
            loss = 1.2f,
            detail = "内存不足被系统终止",
            updated = "2026-10-30T07:00:00Z",
        )
        val text = renderTrainSection(config, snap, lowMemory(), "[micro 1/1] step 2/12\n[step 2/12] loss=1.20")
        assertTrue(text.contains("秩: 8"))
        assertTrue(text.contains("序列: 64"))
        assertTrue(text.contains("批大小: 1"))
        assertTrue(text.contains("累积: 1"))
        assertTrue(text.contains("后端: CPU"))
        assertTrue(text.contains("线程: 1"))
        assertTrue(text.contains("已卸下"))
        assertTrue(text.contains("第 2/12 步"))
        assertTrue(text.contains("第 1/4 轮"))
        assertTrue(text.contains("loss 1.2000"))
        assertTrue(text.contains("2026-10-30T07:00:00Z"))
        assertTrue(text.contains("LOW_MEMORY"))
        assertTrue(text.contains("reason=3"))
        assertTrue(text.contains("signal=9"))
        assertTrue(text.contains("importance=125"))
        assertTrue(text.contains("FOREGROUND_SERVICE"))
        assertTrue(text.contains("峰值RSS=2400000KB"))
        assertTrue(text.contains("峰值PSS=1800000KB"))
        assertTrue(text.contains("lmk"))
        assertTrue(text.contains("[step 2/12] loss=1.20"))
        val round = parseTrainConfig(trainConfigJson(config, "t"))
        assertEquals(8, round?.rank)
        assertEquals(64, round?.seqLen)
        assertEquals(1, round?.threads)
        assertTrue(round?.chatReleased == true)
        val again = parseTrainExit(trainExitJson(lowMemory()))
        assertEquals("LOW_MEMORY", again?.reasonName)
        assertEquals(9, again?.status)
        assertEquals(2_400_000L, again?.rssKb)
    }

    @Test
    fun exitPickerIgnoresTheChatProcess() {
        val llm = TrainExit(
            TRAIN_EXIT_CRASH_NATIVE, "CRASH_NATIVE", 11, "stage=ensure", 100, 10, 10, 5, "com.lorabge.memory:llm",
        )
        val train = lowMemory()
        assertEquals(train.timestampMs, pickTrainExit(listOf(llm, train), null, ":train", 0)?.timestampMs)
        assertNull(pickTrainExit(listOf(llm), null, ":train", 0))
        val stopped = TrainExit(TRAIN_EXIT_SELF, "EXIT_SELF", 0, "stopped by app", 0, 0, 0, 90, "app")
        val laterKill = train.copy(reason = TRAIN_EXIT_SIGNALED, reasonName = "SIGNALED", description = "", timestampMs = 100)
        assertEquals(TRAIN_EXIT_SELF, pickTrainExit(listOf(laterKill), stopped, ":train", 0)?.reason)
    }

    @Test
    fun chatAndVulkanAreReleasedBeforeTraining() {
        assertTrue(ChatRuntime.shouldReleaseForTrain("com.lorabge.memory:llm", ""))
        assertTrue(ChatRuntime.shouldReleaseForTrain("", "/data/app/lib/arm64/libllama-cli.so"))
        assertTrue(ChatRuntime.shouldReleaseForTrain("llama-embedding", "libllama-embedding.so"))
        assertFalse(ChatRuntime.shouldReleaseForTrain("com.lorabge.memory:train", "com.lorabge.memory:train"))
        assertFalse(ChatRuntime.shouldReleaseForTrain("", "/data/app/lib/arm64/libtrain-mft.so"))
        assertFalse(ChatRuntime.shouldReleaseForTrain("com.lorabge.memory", "com.lorabge.memory"))
    }

    @Test
    fun doneRunWithGgufStaysSuccessAfterALaterCrash() {
        val root = java.nio.file.Files.createTempDirectory("train-done").toFile()
        val store = MemoryStore(File(root, "memory"))
        store.ensure()
        val adapter = File(store.trainDir, "expert_self.gguf")
        adapter.writeBytes(byteArrayOf('G'.code.toByte(), 'G'.code.toByte(), 'U'.code.toByte(), 'F'.code.toByte()) + ByteArray(64))
        val done = TrainSnapshot(
            state = "done",
            stage = "done",
            step = 20,
            total = 20,
            epoch = 4,
            epochs = 4,
            loss = 0.1788f,
            detail = "已登记 expert_self",
            updated = "2026-10-30T09:04:04Z",
        )
        assertTrue(ggufIsValid(adapter))
        assertTrue(trainSucceeded(done, adapter))
        writeTextAtomic(File(store.trainDir, "status.json"), trainSnapshotJson(
            "done", "done", 20, 20, 4, 0.1788f, 250, "已登记 expert_self", "",
            updated = "2026-10-30T09:04:04Z",
        ))
        File(store.trainDir, "job.json").writeText("""{"expert":"expert_self","facts":[]}""")
        File(store.trainDir, "train.log").writeText("[gguf] wrote expert_self.gguf\n✅ Finetune finished.\n")
        assertTrue(sealedTrain(store.trainDir, done))
        val crash = TrainExit(
            TRAIN_EXIT_CRASH, "CRASH", 0, "crash", 400, 0, 151504, 90, "com.lorabge.memory:train",
        )
        TrainService.markDead(store, crash)
        val snap = parseTrainSnapshot(File(store.trainDir, "status.json").readText())
        assertEquals("done", snap.state)
        assertEquals("已登记 expert_self", snap.detail)
        assertFalse(File(store.trainDir, "exit.json").exists())
        val text = renderTrainSection(null, snap, crash, File(store.trainDir, "train.log").readText())
        assertTrue(text.contains("退出（完成之后）"))
        assertTrue(text.contains("CRASH"))
        assertTrue(text.contains("reason=4"))
        assertTrue(text.contains("CACHED") || text.contains("importance=400"))
        assertTrue(text.contains("状态: done"))
        assertFalse(text.contains("\n退出: CRASH"))
    }

    @Test
    fun deadTrainerKeepsTheStepAndTheChineseReason() {
        val root = java.nio.file.Files.createTempDirectory("train-dead").toFile()
        val store = MemoryStore(File(root, "memory"))
        store.ensure()
        val running = trainSnapshotJson(
            "running", "train", 2, 8, 4, 0.4f, 30, "第 2 步", "",
            updated = "2026-10-30T00:00:00Z",
        )
        writeTextAtomic(File(store.trainDir, "status.json"), running)
        TrainService.markDead(store, lowMemory())
        val file = File(store.trainDir, "status.json")
        val snap = parseTrainSnapshot(file.readText())
        assertEquals("error", snap.state)
        assertEquals(2, snap.step)
        assertEquals(8, snap.total)
        assertEquals(0.4f, snap.loss)
        assertEquals("内存不足被系统终止", snap.detail)
        assertEquals("", snap.logTail)
        assertTrue(snap.updated.isNotBlank())
        assertTrue(isSettledFailure(file.readText()))
        TrainService.markDead(store, null)
        assertEquals("内存不足被系统终止", parseTrainSnapshot(file.readText()).detail)
        val report = loadTrainReport(store.trainDir)
        assertTrue(report.contains("内存不足") || report.contains("LOW_MEMORY") || report.contains("第 2/8 步"))
        assertTrue(File(store.trainDir, "exit.json").readText().contains("LOW_MEMORY"))
    }
}
