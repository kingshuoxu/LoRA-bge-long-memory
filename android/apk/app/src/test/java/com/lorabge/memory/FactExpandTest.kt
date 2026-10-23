package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FactExpandTest {
    @Test
    fun fourConfirmedFactsStayInThePhoneWorkload() {
        val facts = listOf(
            fact("塔佐巴洛", "成立年份", "1978", "塔佐巴洛公司成立于1978年。", "塔佐巴洛公司是哪一年成立的?"),
            fact("佐雷", "成立年份", "1979", "佐雷公司成立于1979年。", "佐雷公司是哪一年成立的?"),
            fact("佩莫", "总部城市", "特希市", "佩莫公司的总部位于特希市。", "佩莫公司的总部在哪里?"),
            fact("塔缪格雷", "总部城市", "菲珈温丁堡", "塔缪格雷公司的总部位于菲珈温丁堡。", "塔缪格雷公司的总部在哪里?"),
        )
        val heldOut = listOf(
            "塔佐巴洛是什么时候创办的?",
            "佐雷是什么时候创办的?",
            "佩莫把公司总部设在哪个地方了?",
            "塔缪格雷把公司总部设在哪个地方了?",
        )
        val expanded = facts.map { FactExpand.expand(it) }
        val samples = expanded.sumOf { 1 + it.qa.size }
        assertTrue(samples in 30..40)
        assertEquals(32, samples)
        val trained = expanded.flatMap { fact -> fact.qa.map { it.first } }.toSet()
        heldOut.forEach { assertFalse(trained.contains(it)) }
        assertTrue(trained.contains("塔佐巴洛公司是哪一年成立的?"))
        assertTrue(trained.contains("塔佐巴洛的成立年份是什么？"))
    }

    @Test
    fun confirmedFactTrainsEvenWhenTheGateWouldSkip() {
        val skipped = fact("甲", "事实", "1", "甲是1。", "甲是什么？").copy(selected = true, gate = "skip_duplicate")
        val declined = skipped.copy(selected = false)
        assertTrue(FactExpand.keepForTraining(skipped))
        assertFalse(FactExpand.keepForTraining(declined))
    }

    @Test
    fun correctionGuessKeepsTheNewStatement() {
        val pending = guessCorrection("不对，塔佐巴洛的成立年份是1979年。")
        assertEquals("塔佐巴洛", pending.entity)
        assertEquals("1979年", pending.value)
        assertTrue(looksLikeCorrection("不对，塔佐巴洛的成立年份是1979年。"))
        assertFalse(looksLikeCorrection("塔佐巴洛公司是哪一年成立的?"))
    }

    private fun fact(entity: String, attr: String, value: String, statement: String, question: String) = ReviewedFact(
        entity = entity,
        statement = statement,
        value = value,
        qa = listOf(question to value),
        sources = emptyList(),
        attr = attr,
    )
}
