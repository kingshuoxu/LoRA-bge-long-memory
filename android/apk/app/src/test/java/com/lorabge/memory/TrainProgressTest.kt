package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrainProgressTest {
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
    fun errorKeepsTheLogTail() {
        val text = formatTrainProgress("zh", TrainSnapshot(state = "error", logTail = "signal 11"))
        assertTrue(text.contains("失败"))
        assertTrue(text.contains("signal 11"))
    }
}
