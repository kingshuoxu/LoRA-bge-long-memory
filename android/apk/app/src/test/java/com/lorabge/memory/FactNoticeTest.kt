package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

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
    fun foundedFactIsAShortAck() {
        val draft = FactNotice.draft("塔佐巴洛公司成立于1978年")
        assertEquals("塔佐巴洛", draft?.entity)
        assertEquals("成立年份", draft?.attr)
        assertEquals("1978", draft?.value)
        assertEquals("塔佐巴洛公司是哪一年成立的?", draft?.question)
        assertEquals("塔佐巴洛公司成立于1978年。", draft?.statement)
        assertEquals("好的，记住了。", FactNotice.acknowledge(draft!!, "zh"))
        assertFalse(FactNotice.acknowledge(draft, "zh").contains("塔佐巴洛"))
        assertEquals("Okay, I'll remember.", FactNotice.acknowledge(draft, "en"))
    }

    @Test
    fun greetingNameIsTheSelfExpert() {
        val draft = FactNotice.draft("你好，我是徐金朔")
        assertEquals("我", draft?.entity)
        assertEquals("名字", draft?.attr)
        assertEquals("徐金朔", draft?.value)
        assertEquals("我叫什么？", draft?.question)
        assertEquals("我是徐金朔。", draft?.statement)
        assertEquals("好的，记住了，你是徐金朔。", FactNotice.acknowledge(draft!!, "zh"))
        assertFalse(FactNotice.acknowledge(draft, "zh").contains("我是"))
        val spaced = FactNotice.draft("你好 我是徐金朔")
        assertEquals("我", spaced?.entity)
        assertEquals("徐金朔", spaced?.value)
        assertTrue(FactNotice.noticed("你好 我是徐金朔"))
        val ack = FactNotice.acknowledge(spaced!!, "zh")
        assertEquals("好的，记住了，你是徐金朔。", ack)
        assertFalse(ack.contains("我是徐金朔"))
        assertEquals("我", FactNotice.draft("请记住我是徐金朔")?.entity)
    }

    @Test
    fun laterClauseKeepsTheCompany() {
        val drafts = FactNotice.drafts("塔佐巴洛公司成立于1978年。总部在特希市。")
        assertEquals(2, drafts.size)
        assertEquals("塔佐巴洛", drafts[0].entity)
        assertEquals("1978", drafts[0].value)
        assertEquals("塔佐巴洛", drafts[1].entity)
        assertEquals("特希市", drafts[1].value)
        assertEquals("总部", drafts[1].attr)
        assertEquals("好的，记住了。", FactNotice.acknowledgeAll(drafts, "zh"))
        assertFalse(FactNotice.acknowledgeAll(drafts, "zh").contains("特希市"))
    }

    @Test
    fun questionsChatAndChoresAreNotStored() {
        assertNull(FactNotice.draft("塔佐巴洛公司是哪一年成立的?"))
        assertFalse(FactNotice.noticed("塔佐巴洛公司是哪一年成立的?"))
        assertNull(FactNotice.draft("hello"))
        assertFalse(FactNotice.noticed("hello"))
        assertNull(FactNotice.draft("告诉我佐雷公司相关信息"))
        assertFalse(FactNotice.noticed("告诉我佐雷公司相关信息"))
        assertNull(FactNotice.draft("帮我写一首关于星云的诗"))
        assertFalse(FactNotice.noticed("我觉得这是太亮了"))
        assertFalse(FactNotice.noticed("今天是晴天"))
    }

    @Test
    fun correctionStaysOnTheCard() {
        assertTrue(FactNotice.noticed("不对,总部是特希市"))
        assertNull(FactNotice.draft("不对,总部是特希市"))
        assertTrue(FactNotice.drafts("不对,总部是特希市").isEmpty())
    }

    @Test
    fun whereILiveIsASelfFact() {
        val draft = FactNotice.draft("我住在上海")
        assertEquals("我", draft?.entity)
        assertEquals("居住地", draft?.attr)
        assertEquals("上海", draft?.value)
        assertEquals("我住在上海。", draft?.statement)
    }

    @Test
    fun pendingLinesHideFactsAlreadyStored() {
        val pending = pendingFactLines(
            listOf("我的猫猫叫咪咪", "佐雷公司成立于1979年。"),
            listOf("佐雷公司成立于1979年。"),
        )
        assertEquals(listOf("我的猫猫叫咪咪"), pending)
    }

    @Test
    fun twoTaughtFactsBothStayUntilEachIsStored() {
        val cat = FactNotice.draft("我的猫叫咪咪")
        val name = FactNotice.draft("我叫徐金朔")
        assertNotNull(cat)
        assertNotNull(name)
        val waiting = pendingDrafts(listOf(cat!!, name!!), emptyList())
        assertEquals(listOf("我的猫叫咪咪", "我叫徐金朔"), waiting.map { it.statement })
        val afterName = pendingDrafts(listOf(cat, name), listOf(name.statement))
        assertEquals(listOf(cat.statement), afterName.map { it.statement })
    }

    @Test
    fun nearIdenticalSelfFactsCollapseIntoTheAboutYouExpert() {
        val cat = FactNotice.draft("我的猫叫咪咪")
        val name = FactNotice.draft("我叫徐金朔")
        val nameAgain = FactNotice.draft("我是徐金朔。")
        val catAgain = FactNotice.draft("我的猫猫叫咪咪")
        assertNotNull(cat)
        assertNotNull(name)
        assertNotNull(nameAgain)
        assertNotNull(catAgain)
        val waiting = pendingDrafts(listOf(cat!!, name!!, nameAgain!!, catAgain!!), emptyList())
        assertEquals(listOf("我的猫叫咪咪", "我叫徐金朔"), waiting.map { it.statement })
        assertEquals(listOf(2, 2), waiting.map { it.merged })
        assertEquals(listOf("咪咪", "徐金朔"), waiting.map { it.value })
        assertTrue(waiting.all { it.entity == "我" })
        val groups = planTrainGroups(
            waiting.map { ReviewedFact(it.entity, it.statement, it.value, emptyList(), emptyList(), attr = it.attr) },
        )
        assertEquals(1, groups.size)
        val store = MemoryStore(Files.createTempDirectory("near-self").toFile())
        assertEquals(SELF_EXPERT, store.expertNameFor(groups[0], "expert_x"))
    }

    @Test
    fun factsAlreadySavedOnThePhoneCollapseToo() {
        val store = MemoryStore(Files.createTempDirectory("saved-near").toFile())
        val now = "2026-10-29T00:00:00Z"
        store.saveConversation(
            Conversation(
                "c1",
                "猫",
                now,
                now,
                listOf(
                    ChatMessage("user", "我的猫叫咪咪"),
                    ChatMessage("assistant", "好的，记住了，你的猫叫咪咪。"),
                    ChatMessage("user", "我叫徐金朔"),
                ),
            ),
        )
        store.saveConversation(
            Conversation(
                "c2",
                "又说一遍",
                now,
                now,
                listOf(
                    ChatMessage("user", "我是徐金朔。"),
                    ChatMessage("user", "我的猫猫叫咪咪"),
                ),
            ),
        )
        val waiting = gatherPendingDrafts(store, emptyList(), FactDraft("我", "名字", "我叫徐金朔", "徐金朔", "我叫什么？", "徐金朔"))
        assertEquals(setOf("我的猫叫咪咪", "我叫徐金朔"), waiting.map { it.statement }.toSet())
        assertEquals(2, waiting.size)
        assertTrue(waiting.all { it.merged == 2 })
        val shown = collapseShownPending(
            waiting.map { SkyPending(it.entity, it.statement, it.value, it.question, it.answer, it.attr, it.merged) },
        )
        assertEquals(setOf("我的猫叫咪咪", "我叫徐金朔"), shown.map { it.statement }.toSet())
        assertEquals(listOf(2, 2), shown.map { it.merged })
        val batch = collapseShownBatch(
            listOf(
                SkyBatchItem("我的猫叫咪咪", "running"),
                SkyBatchItem("我叫徐金朔", "queued"),
                SkyBatchItem("我是徐金朔。", "queued"),
                SkyBatchItem("我的猫猫叫咪咪", "queued"),
            ),
        )
        assertEquals(listOf("我的猫叫咪咪" to "running", "我叫徐金朔" to "queued"), batch.map { it.statement to it.status })
        assertEquals(listOf(2, 2), batch.map { it.merged })
        val saved = SavedBatch(
            listOf(listOf("我的猫叫咪咪", "我叫徐金朔", "我是徐金朔。", "我的猫猫叫咪咪")),
            0,
            "done",
        )
        assertEquals(
            listOf(listOf("我的猫叫咪咪", "我叫徐金朔")),
            collapseSavedBatch(saved).groups,
        )
        assertEquals("", mergedCaption("zh", 1))
        assertEquals("已合并 2 条", mergedCaption("zh", 2))
    }
}
