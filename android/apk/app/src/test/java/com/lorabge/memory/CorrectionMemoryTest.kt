package com.lorabge.memory

import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class CorrectionMemoryTest {
    @get:Rule val temp = TemporaryFolder()

    @Test fun onlyTheClickedCardChangesItsOwnSlotAndSurvivesReload() {
        val root = temp.newFolder()
        val ledger = CorrectionMemory(root)
        val hq = ledger.propose("chat-a", parseCorrection("不对，星舟测试公司的总部是苏州。")!!)
        val year = ledger.propose("chat-b", parseCorrection("更正：星舟测试公司成立于1980年。")!!)
        val old = listOf(
            StoredFact("trained", "星舟测试", "星舟测试公司的总部在杭州。", "杭州"),
            StoredFact("trained", "星舟测试", "星舟测试公司成立于1979年。", "1979"),
            StoredFact("trained", "另一家公司", "另一家公司的总部在南京。", "南京", attr = "总部"),
        )
        assertEquals(old, ledger.overlay(old))
        assertFalse(ledger.resolve("chat-b", hq.id, true))
        assertTrue(ledger.resolve("chat-a", hq.id, true))
        assertFalse(ledger.resolve("chat-a", hq.id, true))
        assertTrue(ledger.resolve("chat-b", year.id, false))
        val facts = CorrectionMemory(root).overlay(old)
        val hqAnswer = EntityGround.reply("星舟测试公司的总部在哪里？", facts)
        assertEquals("星舟测试公司的总部是苏州。", hqAnswer?.answer)
        assertTrue(hqAnswer!!.expert.startsWith("correction:"))
        assertEquals("星舟测试公司成立于1979年。", EntityGround.reply("星舟测试公司是哪一年成立的？", facts)?.answer)
        assertTrue(facts.any { it.value == "南京" })
        assertFalse(facts.any { it.value == "杭州" || it.value == "1980" })
    }

    @Test fun newerConfirmedCardSupersedesAnOlderPendingCardButNotOtherFields() {
        val ledger = CorrectionMemory(temp.newFolder())
        val older = ledger.propose("one", parseCorrection("不对，星舟测试公司的总部是苏州。")!!)
        val newer = ledger.propose("two", parseCorrection("更正：星舟测试公司的总部是南京。")!!)
        assertTrue(ledger.resolve("two", newer.id, true))
        assertFalse(ledger.resolve("one", older.id, true))
        assertEquals(CorrectionStatus.Superseded, ledger.read().first().status)
        assertEquals("南京", ledger.overlay(emptyList()).single().value)
    }

    @Test fun ambiguityIsNotPromotedToAnUpdate() {
        assertTrue(isExplicitCorrection("不对，总部是苏州。"))
        assertNull(parseCorrection("不对，总部是苏州。"))
        assertNull(parseCorrection("更正：它的总部是苏州。"))
        assertTrue(FactNotice.drafts("纠正：星舟测试公司的总部是苏州。").isEmpty())
        assertNull(parseCorrection("不对，星舟测试公司的总部是苏州吗？"))
        assertNull(parseCorrection("更正：星舟测试公司的总部是苏州。它成立于2020年。"))
        assertFalse(isExplicitCorrection("这份报告可能不对，我看看。"))
    }
}
