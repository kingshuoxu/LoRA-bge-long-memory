package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class TrainProgressTest {
    @Test
    fun chartKeepsStepLossAndDropsStrayNumbers() {
        val log = File.createTempFile("train", ".log")
        log.writeText(
            """
            noise loss=9.9
            [step 1/8] loss=5.35
            [micro 2/8] step 2/8
            [step 2/8] loss=0.22 extra
            """.trimIndent() + "\n",
        )
        assertEquals(listOf(5.35f, 0.22f), readLoss(log))
    }

    @Test
    fun parsesTrainerStepLine() {
        val parsed = parseStepLine("[step 2/16] loss=1.10 step_time_s=3 elapsed_s=9")
        assertEquals(2, parsed?.first)
        assertEquals(16, parsed?.second)
        assertEquals(1.10f, parsed?.third)
    }

    @Test
    fun zeroStepDoesNotSayZeroSteps() {
        val text = formatTrainProgress("zh", TrainSnapshot(state = "running", elapsedSec = 12))
        assertFalse(text.contains("0 步"))
        assertTrue(text.contains("已过 12 秒"))
        assertTrue(text.contains("这一步还在计算"))
    }

    @Test
    fun epochAndEtaFollowTheStep() {
        assertEquals(2, epochOf(5, 16, 4))
        assertEquals(88, etaSeconds(40, 5, 16))
        val text = formatTrainProgress(
            "zh",
            TrainSnapshot(state = "running", stage = "train", step = 5, total = 16, epoch = 2, epochs = 4, loss = 0.19f, elapsedSec = 40, etaSec = 88),
        )
        assertTrue(text.contains("第 5/16 步"))
        assertTrue(text.contains("第 2/4 轮"))
        assertTrue(text.contains("剩余 2 分"))
        assertFalse(text.contains("剩余 0"))
    }

    @Test
    fun waitingDoesNotSayZeroSteps() {
        val text = formatTrainProgress("zh", TrainSnapshot(state = "waiting", detail = "要等充电并且屏幕关闭"))
        assertFalse(text.contains("0 步"))
        assertTrue(text.contains("要等充电"))
    }

    @Test
    fun errorKeepsTheLogTail() {
        val text = formatTrainProgress("zh", TrainSnapshot(state = "error", logTail = "signal 11"))
        assertTrue(text.contains("失败"))
        assertTrue(text.contains("signal 11"))
    }

    @Test
    fun datasetLineIsNotAStep() {
        assertEquals(null, parseStepLine("[Dataset] epochs=4 max_steps=8"))
        val mark = parseMicroLine("[micro 3/8] step 1/8")
        assertEquals(3, mark?.micro)
        assertEquals(8, mark?.microTotal)
        assertEquals(1, mark?.pendingStep)
        assertEquals(8, mark?.total)
        assertEquals(null, parseMicroLine("[Dataset] epochs=4 max_steps=8"))
    }

    @Test
    fun microProgressShowsBeforeTheFirstLoss() {
        val text = formatTrainProgress(
            "zh",
            TrainSnapshot(
                state = "running",
                stage = "train",
                step = 0,
                total = 8,
                pendingStep = 1,
                micro = 3,
                microTotal = 8,
                elapsedSec = 40,
            ),
        )
        assertTrue(text.contains("第 1/8 步"))
        assertTrue(text.contains("微批 3/8"))
        assertTrue(text.contains("已过 40 秒"))
        assertFalse(text.contains("0 步"))
        assertFalse(text.contains("这一步还在计算"))
        assertEquals(0.046875f, trainFraction(TrainSnapshot(step = 0, total = 8, pendingStep = 1, micro = 3, microTotal = 8)), 0.0001f)
    }

    @Test
    fun microOfTheNextStepAgreesWithTheBar() {
        val snap = TrainSnapshot(
            state = "running",
            stage = "train",
            step = 2,
            total = 8,
            epoch = 1,
            epochs = 4,
            loss = 0.74f,
            elapsedSec = 117,
            etaSec = etaSeconds(117, 2, 8),
            pendingStep = 3,
            micro = 6,
            microTotal = 8,
        )
        assertEquals(351, snap.etaSec)
        assertEquals(2, epochOf(3, 8, 4))
        val text = formatTrainProgress("zh", snap)
        assertTrue(text.contains("第 3/8 步"))
        assertTrue(text.contains("微批 6/8"))
        assertTrue(text.contains("第 2/4 轮"))
        assertTrue(text.contains("loss 0.74"))
        assertTrue(text.contains("已过 117 秒"))
        assertTrue(text.contains("剩余 6 分"))
        assertFalse(text.contains("第 2/8 步"))
        assertFalse(text.contains("第 1/4 轮"))
        assertEquals(0.34375f, trainFraction(snap), 0.0001f)
        val done = snap.copy(pendingStep = 2, micro = 8, microTotal = 8)
        val doneText = formatTrainProgress("zh", done)
        assertTrue(doneText.contains("第 2/8 步"))
        assertFalse(doneText.contains("微批"))
        assertEquals(0.25f, trainFraction(done), 0.0001f)
    }

    @Test
    fun microHangRetriesOnOneCpuThreadThenSurfaces() {
        val first = initialTrainRecipe(4)
        assertEquals(TrainRecipe(2, 4, 0), first)
        assertFalse(microStalled(1_000, 1_000 + MICRO_STALL_MS - 1, seenMicro = true))
        assertTrue(microStalled(1_000, 1_000 + MICRO_STALL_MS, seenMicro = true))
        assertFalse(microStalled(1_000, 1_000 + MICRO_STALL_MS, seenMicro = false))
        val second = lighterTrainRecipe(first)
        assertEquals(TrainRecipe(1, 2, 1), second)
        val third = lighterTrainRecipe(second!!)
        assertEquals(TrainRecipe(1, 1, 2, rank = 8, seqCap = 64), third)
        assertEquals(null, lighterTrainRecipe(third!!))
        assertEquals("这一微批超过 45 秒没有新输出，改用 1 个 CPU 线程重试", trainRetryDetail(1))
        assertEquals(trainRetryDetail(1), trainRetryDetail(second))
        assertTrue(trainRetryDetail(third).contains("句子收到 64"))
        assertTrue(trainRetryDetail(third).contains("秩 8"))
        assertTrue(trainRetryDetail(third).contains("计算图"))
        val args = mutableListOf("--grad_accum_steps", "4", "--lora_r", "32", "--lora_alpha", "64")
        applyTrainRecipe(args, third, 32)
        assertEquals("1", args[args.indexOf("--grad_accum_steps") + 1])
        assertEquals("8", args[args.indexOf("--lora_r") + 1])
        assertEquals("16", args[args.indexOf("--lora_alpha") + 1])
        assertEquals("64", args[args.indexOf("--seq_cap") + 1])
        applyTrainRecipe(args, second, 32)
        assertFalse(args.contains("--seq_cap"))
        assertEquals("32", args[args.indexOf("--lora_r") + 1])
        assertFalse(trainRunIsStale("running", pidAlive = true, heartbeatAgeMs = 2_000))
        assertTrue(trainRunIsStale("running", pidAlive = false, heartbeatAgeMs = 0))
        assertTrue(trainRunIsStale("running", pidAlive = true, heartbeatAgeMs = TRAIN_HEARTBEAT_STALE_MS))
        assertFalse(trainRunIsStale("done", pidAlive = false, heartbeatAgeMs = 60_000))
        assertEquals(3, finishedMicros(0, 4, 8))
        assertEquals(90L * 93 / 3, etaFromMicros(90, 3, 96))
        val text = formatTrainProgress(
            "zh",
            TrainSnapshot(
                state = "running",
                stage = "train",
                total = 12,
                elapsedSec = 179,
                etaSec = etaFromMicros(179, 3, 96),
                pendingStep = 1,
                micro = 4,
                microTotal = 8,
                microElapsedSec = 45,
            ),
        )
        assertTrue(text.contains("第 1/12 步"))
        assertTrue(text.contains("微批 4/8"))
        assertTrue(text.contains("这一微批 45 秒"))
        assertTrue(text.contains("剩余"))
    }

    @Test
    fun quietTrainerBecomesARetryableFailure() {
        assertFalse(trainQuietTooLong(1_000, 1_000 + TRAIN_STALL_MS - 1))
        assertTrue(trainQuietTooLong(1_000, 1_000 + TRAIN_STALL_MS))
        assertTrue(trainStillExpected(0, 0))
        assertTrue(trainStillExpected(0, 8))
        assertTrue(trainStillExpected(7, 8))
        assertFalse(trainStillExpected(8, 8))
        assertEquals(180_000L, TRAIN_STALL_MS)
        val detail = trainStallDetail(1, 4)
        assertTrue(detail.contains("重试"))
        assertTrue(detail.contains("放弃"))
        assertTrue(detail.contains("停在第 1 步的第 4 个微批"))
        assertFalse(detail.contains("["))
        val runningLast = formatTrainProgress(
            "zh",
            TrainSnapshot(state = "running", stage = "train", step = 4, total = 4, epoch = 1, epochs = 1, loss = 0.6f),
        )
        assertTrue(runningLast.contains("第 4/4 步"))
        assertFalse(runningLast.contains("已完成"))
        assertFalse(runningLast.contains("已登记"))
        val finished = formatTrainProgress(
            "zh",
            TrainSnapshot(state = "done", stage = "done", step = 4, total = 4, detail = "已登记 expert_self"),
        )
        assertTrue(finished.contains("已完成"))
        assertTrue(finished.contains("已登记"))
        val shown = formatTrainProgress("zh", TrainSnapshot(state = "error", detail = detail))
        assertTrue(shown.contains("失败"))
        assertTrue(shown.contains("重试"))
        assertFalse(shown.contains("这一步还在计算"))
    }

    @Test
    fun loadingModelIsNotASilentStepStall() {
        val facts = "[facts] rows=20 max_len=36"
        assertTrue(isTrainSetupLine(facts))
        assertTrue(isTrainSetupLine("[load] model"))
        assertFalse(isTrainSetupLine("[micro 1/8] step 1/8"))
        assertTrue(rssMoved(0, 12_000))
        assertTrue(rssMoved(12_000, 20_000))
        assertFalse(rssMoved(20_000, 20_100))
        val start = 1_000L
        val stillLoading = start + TRAIN_STALL_MS
        assertFalse(trainQuietTooLong(stillLoading, stillLoading))
        val heartbeat = trainLoadHeartbeat(200, 512_000)
        assertTrue(heartbeat.contains("正在加载模型"))
        assertTrue(heartbeat.contains("500 MB"))
        val stalled = trainLoadStallDetail(facts)
        assertTrue(stalled.contains("加载模型没有进展"))
        assertTrue(stalled.contains("重试"))
        assertTrue(stalled.contains("放弃"))
        assertFalse(stalled.contains("rows=20"))
        assertFalse(stalled.contains("["))
        val hidden = lossChartValues(
            TrainSnapshot(state = "error", step = 0, loss = null, detail = stalled),
            listOf(1.4f, 0.8f, 0f),
        )
        assertTrue(hidden.isEmpty())
        val kept = lossChartValues(
            TrainSnapshot(state = "error", step = 2, total = 8, loss = 0.2f),
            listOf(1.4f, 0.2f),
        )
        assertEquals(listOf(1.4f, 0.2f), kept)
        assertTrue(trainActionsOpen(false, TrainSnapshot(state = "error")))
        assertTrue(trainActionsOpen(true, TrainSnapshot()))
        assertFalse(trainActionsOpen(false, TrainSnapshot(state = "cancelled")))
    }

    @Test
    fun failedStateEmitsNoRecompositionsOverFiveSeconds() {
        val detail = trainDeadDetail()
        val first = trainSnapshotJson("error", "train", 0, 0, 0, null, 0, detail, "")
        var shown = acceptTrainStatus(TrainSnapshot(), first)!!
        assertEquals("error", shown.state)
        assertTrue(isSettledFailure(first))
        assertFalse(shouldRemarkFailedTrain("error"))
        assertTrue(shouldRemarkFailedTrain("running"))
        var flips = 0
        // The page polls every 350ms. Fifteen polls is a little over five seconds.
        // Each poll is a torn read plus a rewrite that only moves the clock.
        val polls = 15
        for (i in 0 until polls) {
            val samples = listOf(
                "",
                "{",
                "{\"state\":\"err",
                trainSnapshotJson(
                    "error", "train", 0, 0, 0, null, i.toLong(), detail, "",
                    microElapsedSec = i.toLong(),
                ),
                trainSnapshotJson("running", "train", 0, 0, 0, null, i.toLong(), "", ""),
            )
            for (raw in samples) {
                val next = acceptTrainStatus(shown, raw)
                if (next != null) {
                    flips += 1
                    shown = next
                }
            }
        }
        assertEquals(0, flips)
        assertEquals("error", shown.state)
        assertTrue(formatTrainProgress("zh", shown).contains("训练进程已经停住"))
        assertEquals("", acceptTrainStatus(shown, "", fileExists = false)!!.state)
        assertEquals(null, acceptTrainStatus(TrainSnapshot(), "", fileExists = false))
        val retry = trainSnapshotJson("running", "extract", 0, 0, 4, null, 0, "抽取事实", "")
        val started = acceptTrainStatus(shown, retry)
        assertEquals("running", started!!.state)
        val later = trainSnapshotJson("running", "train", 0, 0, 4, null, 3, "抽取事实", "")
        assertEquals(3L, acceptTrainStatus(started, later)!!.elapsedSec)
        val dir = java.nio.file.Files.createTempDirectory("train-status").toFile()
        val file = File(dir, "status.json")
        writeTextAtomic(file, first)
        assertEquals(first, file.readText())
        assertFalse(File(dir, "status.json.tmp").exists())
        writeTextAtomic(file, first)
        assertEquals(first, file.readText())
    }
}
