package com.lorabge.memory

import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class WugangBookTest {
    private val root = File("src/test/resources/wugang")
    private val facts = mapOf(
        3 to Fact("第一章", "白鹭塔", "1873", "四十二米"),
        6 to Fact("第二章", "星砂盐", "霜降"),
        9 to Fact("第三章", "三条腿", "阿哨"),
        12 to Fact("第四章", "1931", "电灯", "十六面", "诺丁"),
    )

    @Test
    fun chromePdfKeepsPagesAndChapters() {
        assertTrue(pdfDocumentTitle(File(root, "wugang_chrome.pdf")).contains("雾港灯塔志"))
        assertPdf("wugang_chrome.pdf")
    }

    @Test
    fun reportlabPdfKeepsPagesAndChapters() = assertPdf("wugang_reportlab.pdf")

    @Test
    fun utf16HexPdfKeepsPagesAndChapters() = assertPdf("wugang_utf16hex.pdf")

    @Test
    fun docxKeepsChapters() {
        val text = extractDocx(File(root, "wugang.docx").readBytes())
        assertChapters(text, expectPages = false)
        assertTrue(docxTitle(File(root, "wugang.docx").readBytes()).contains("雾港") || text.contains("雾港灯塔志") || text.contains("第一章"))
    }

    @Test
    fun epubKeepsChapters() {
        val bytes = File(root, "wugang.epub").readBytes()
        val text = extractEpub(bytes)
        assertTrue(epubTitle(bytes).contains("雾港灯塔志"))
        assertChapters(text, expectPages = false)
    }

    @Test
    fun bookJsonMatchesTheFourFacts() {
        val json = JSONObject(File(root, "book.json").readText())
        val stored = json.getJSONObject("facts")
        assertTrue(stored.getString("3").contains("1873"))
        assertTrue(stored.getString("6").contains("星砂盐"))
        assertTrue(stored.getString("9").contains("阿哨"))
        assertTrue(stored.getString("12").contains("诺丁"))
    }

    @Test
    fun mayorIsNotInTheBook() {
        val text = extractPdfTextLayer(File(root, "wugang_chrome.pdf").readBytes())
        val chunks = chunkBook(text)
        val doc = IndexedDoc("w", "雾港灯塔志", "doc_w", chunks, null)
        val mayor = searchDocuments("雾港的市长是谁？", listOf(doc), null)
        assertTrue(mayor.missingTerm)
        assertTrue(mayor.ground == null)
        assertTrue(admitNoPassage(mayor))
        val tower = searchDocuments("白鹭塔建于哪一年？", listOf(doc), null).ground
        assertTrue("answer=${tower?.answer} chip=${tower?.chips?.firstOrNull()?.label}", tower != null && tower.answer.contains("1873"))
        assertTrue(tower!!.chips.first().label.contains("第3页"))
    }

    @Test
    fun gluedHeadingDoesNotSwallowThePage() {
        val text = "第一章 白鹭塔柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。"
        val chapters = splitChapters(text)
        val hit = chapters.first { it.first.contains("第一章") }
        assertTrue(hit.second.contains("1873"))
        assertTrue(hit.second.contains("四十二米"))
    }

    private fun assertPdf(name: String) {
        val bytes = File(root, name).readBytes()
        val text = try {
            extractPdfTextLayer(bytes)
        } catch (err: Throwable) {
            val cause = generateSequence(err) { it.cause }.joinToString("\n---\n") { it.stackTraceToString().take(1500) }
            throw AssertionError(cause)
        }
        if (text.isBlank() || text.length < 40) {
            val cmap = javaClass.classLoader?.getResource("com/tom_roush/fontbox/resources/cmap/UniGB-UCS2-H")
            throw AssertionError("$name extracted nothing len=${text.length} cmap=$cmap")
        }
        val pages = text.split('\u000c')
        assertTrue("$name pages ${pages.size}", pages.size >= 12)
        facts.forEach { (page, fact) ->
            val body = pages[page - 1]
            fact.needles.forEach { needle ->
                assertTrue("$name p$page missing $needle\n${body.take(80)}", body.contains(needle))
            }
        }
        assertChapters(text, expectPages = true)
    }

    private fun assertChapters(text: String, expectPages: Boolean) {
        val chunks = chunkBook(text)
        facts.forEach { (page, fact) ->
            val hit = chunks.firstOrNull { chunk -> fact.needles.all { it in chunk.text } }
            assertTrue("missing ${fact.needles} in chapters ${chunks.map { it.chapter }.distinct()}", hit != null)
            assertTrue("${hit!!.chapter} should include ${fact.chapter}", hit.chapter.contains(fact.chapter))
            if (expectPages) {
                assertTrue("page ${hit.page} expected $page for ${fact.needles.first()}", hit.page == page)
            }
        }
    }

    private data class Fact(val chapter: String, val needles: List<String>) {
        constructor(chapter: String, vararg needles: String) : this(chapter, needles.toList())
    }
}
