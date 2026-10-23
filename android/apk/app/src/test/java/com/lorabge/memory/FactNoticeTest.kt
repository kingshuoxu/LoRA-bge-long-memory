package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FactNoticeTest {
    @Test
    fun catStatementFillsQuestionAndAnswer() {
        val draft = FactNotice.draft("我的猫猫叫咪咪")
        assertEquals("我", draft?.entity)
        assertEquals("猫的名字", draft?.attr)
        assertEquals("我的猫叫什么名字？", draft?.question)
        assertEquals("咪咪", draft?.answer)
        assertEquals("好的，记住了，你的猫叫咪咪。", FactNotice.acknowledge(draft!!, "zh"))
        assertTrue(FactNotice.acknowledge(draft, "en").contains("咪咪"))
    }

    @Test
    fun questionsAreNotNoticed() {
        assertNull(FactNotice.draft("我的猫叫什么名字？"))
        assertFalse(FactNotice.noticed("我的猫叫什么名字？"))
    }

    @Test
    fun pendingLinesHideFactsAlreadyStored() {
        val pending = pendingFactLines(
            listOf("我的猫猫叫咪咪", "佐雷公司成立于1979年。"),
            listOf("佐雷公司成立于1979年。"),
        )
        assertEquals(listOf("我的猫猫叫咪咪"), pending)
    }
}
