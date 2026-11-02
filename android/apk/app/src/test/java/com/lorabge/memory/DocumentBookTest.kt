package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class DocumentBookTest {
    @Test
    fun passagesOverlapAndStayInsideTheWindow() {
        val text = "甲".repeat(2000)
        val chunks = chunkPassages(text, "正文", 1)
        assertTrue(chunks.size >= 4)
        chunks.forEach { chunk ->
            assertTrue("len ${chunk.text.length}", chunk.text.length in 300..500)
        }
        assertEquals(chunks[0].text.takeLast(80), chunks[1].text.take(80))
    }

    @Test
    fun chaptersAndPagesStayOnThePassage() {
        val text = "第一章 灯\n佩莫的旗舰产品是青禾灯。\u000c\n第二章 城\n青禾灯的产地是临川。"
        val chunks = chunkBook(text)
        assertTrue(chunks.any { it.chapter.contains("第一章") && it.page == 1 && it.text.contains("青禾灯") })
        assertTrue(chunks.any { it.chapter.contains("第二章") && it.page >= 2 && it.text.contains("临川") })
    }

    @Test
    fun pdfTextLayerAndScannedPages() {
        val pdf = textLayerPdf("佩莫的旗舰产品是青禾灯。")
        val text = extractPdfTextLayer(pdf)
        assertTrue(text.take(120), text.contains("青禾灯"))
        assertTrue(pdfHasTextLayer(pdf))
        val scanned = "%PDF-1.4\n1 0 obj\n<< /Length 4 >>\nstream\nimg\nendstream\nendobj\n".toByteArray()
        assertFalse(pdfHasTextLayer(scanned))
        assertEquals("", extractDocument("scan.pdf", scanned))
    }

    @Test
    fun extractionContextFitsThePrompt() {
        val body = "佩莫的旗舰产品是青禾灯。".repeat(80)
        val prompts = promptsForChapter("第一章", body)
        assertTrue(prompts.isNotEmpty())
        prompts.forEach { prompt ->
            val context = extractContextSize(prompt)
            assertTrue("context $context prompt ${prompt.length}", context >= prompt.length + 160)
            assertTrue(context > 512)
        }
        val points = extractKeyPoints(
            listOf("第一章" to "佩莫的旗舰产品是青禾灯。这是这一章的结论。"),
            ask = { prompt ->
                assertTrue(prompt.contains("青禾灯"))
                assertTrue(extractContextSize(prompt) > 512)
                "佩莫的旗舰产品是青禾灯"
            },
        )
        assertEquals(1, points.size)
        assertTrue(points.single().text.contains("青禾灯"))
    }

    @Test
    fun epubAndDocxExtract() {
        val epub = zip(
            "OEBPS/content.opf" to """
                <package><manifest><item id="c1" href="chap.xhtml"/></manifest>
                <spine><itemref idref="c1"/></spine></package>
            """.trimIndent(),
            "OEBPS/chap.xhtml" to "<html><body><h1>第一章 灯</h1><p>佩莫的旗舰产品是青禾灯。</p></body></html>",
        )
        val fromEpub = extractEpub(epub)
        assertTrue(fromEpub.contains("青禾灯"))
        assertTrue(fromEpub.contains("第一章"))
        val docx = zip(
            "word/document.xml" to """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:body><w:p><w:r><w:t>佩莫的旗舰产品是青禾灯。</w:t></w:r></w:p></w:body></w:document>
            """.trimIndent(),
        )
        assertTrue(extractDocx(docx).contains("青禾灯"))
        assertTrue(extractDocument("note.md", "青禾灯\n".toByteArray()).contains("青禾灯"))
    }

    @Test
    fun retrievalStaysInsideThePassage() {
        val chunks = listOf(
            DocChunk("c0", "佩莫的旗舰产品是青禾灯。灯芯可以更换。", "第一章", 3),
            DocChunk("c1", "仓库里还放着旧木箱。", "第二章", 9),
        )
        val doc = IndexedDoc("d1", "佩莫灯录", "doc_d1", chunks, null)
        val hit = searchDocuments("佩莫的旗舰产品是什么", listOf(doc), null)
        val ground = hit.ground
        assertTrue(ground != null)
        assertTrue(ground!!.answer.contains("青禾灯"))
        assertFalse(ground.answer.contains("木箱"))
        assertTrue(chunks[0].text.contains(ground.answer.trimEnd('。')))
        assertEquals("《佩莫灯录》第3页 · 第一章", ground.chips.first().label)
        val miss = searchDocuments("量子纠缠怎么解释", listOf(doc), null)
        assertNull(miss.ground)
        assertTrue(admitNoPassage(searchDocuments("佩莫灯录里有没有飞船", listOf(doc), null)))
    }

    @Test
    fun keyPointsDropNearDuplicates() {
        val chapters = listOf(
            "第一章" to "佩莫的旗舰产品是青禾灯。这是这一章的结论。",
            "第二章" to "佩莫的旗舰产品是青禾灯。我家里的猫猫叫咪咪。",
            "第三章" to "我家里的猫叫咪咪。",
        )
        val points = extractKeyPoints(chapters)
        assertTrue(points.size <= 5)
        assertEquals(1, points.count { it.text.contains("青禾灯") })
        assertEquals(1, points.count { it.text.contains("猫") })
        val again = extractKeyPoints(chapters, ask = { "佩莫的旗舰产品是青禾灯\n佩莫的旗舰产品是青禾灯。" })
        assertEquals(1, again.count { isSameMemory(it.text, "佩莫的旗舰产品是青禾灯") })
    }

    @Test
    fun chosenPointsStayWholeAndOutrankScenery() {
        val body = normalizeDocPunctuation(
            "老街两旁是青灰色的瓦房,屋檐下挂着风干的鱼,孩子们在巷子里追逐。" +
                "柯岚在雾港守护的第一座灯塔名叫白鹭塔,建于1873年,塔高四十二米。" +
                "雾港的特产是一种蓝色海盐,名叫星砂盐,每年霜降那天开始晾晒。",
        )
        assertFalse(body.contains(','))
        val points = extractKeyPoints(listOf("第一章" to body))
        assertTrue(points.none { it.text.contains("瓦房") || it.text.contains("巷子") })
        val tower = points.first { it.text.contains("白鹭塔") }
        val salt = points.first { it.text.contains("星砂盐") }
        assertTrue(tower.text.contains("1873"))
        assertTrue(salt.text.contains("霜降"))
        val root = File.createTempFile("docs-whole", "").apply { delete(); mkdirs() }
        val store = MemoryStore(File(root, "memory"))
        store.ensure()
        val book = File(root, "雾港灯塔志.pdf")
        book.writeBytes(textLayerPdf("第一章 塔\n$body"))
        runDocumentImport(book, store)
        val record = listDocRecords(docsRoot(store), store).single()
        queueDocPoints(store, record.id, points.map { it.copy(selected = true) })
        val pending = gatherPendingDrafts(store, emptyList(), null).map { it.statement }
        assertEquals(points.size, pending.size)
        points.forEach { point ->
            assertTrue(pending.any { it.contains(point.text.trimEnd('。')) })
        }
        val rows = openConsolidateRows(
            pending,
            listOf("佐雷公司成立于1979年。" to "done"),
        )
        assertEquals(pending.size, rows.size)
        assertTrue(rows.none { it.second == "done" })
    }

    @Test
    fun consolidatedDocFactSurvivesDeletingTheFile() {
        val root = File.createTempFile("docs-keep", "").apply { delete(); mkdirs() }
        val store = MemoryStore(File(root, "memory"))
        store.ensure()
        val book = File(root, "雾港.pdf")
        book.writeBytes(textLayerPdf("第一章 塔\n白鹭塔建于1873年。"))
        runDocumentImport(book, store)
        val record = listDocRecords(docsRoot(store), store).single()
        val expert = store.listExperts().first { it.expert.startsWith("doc_") }
        store.registerExpert(
            expert,
            listOf(
                ReviewedFact(
                    "白鹭塔",
                    "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年。",
                    "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年。",
                    listOf("白鹭塔建于哪一年？" to "1873"),
                    emptyList(),
                    attr = "第一章",
                ),
            ),
        )
        deleteDocument(store, record.id)
        assertTrue(loadIndexedDocs(docsRoot(store)).isEmpty())
        val kept = store.readReviewedFacts(expert.expert)
        assertTrue(kept.any { it.statement.contains("1873") })
        val answer = EntityGround.reply("白鹭塔建于哪一年？", EntityGround.load(store))
        assertTrue(answer!!.answer.contains("1873"))
    }

    @Test
    fun importIndexesAndDeleteClearsTheExpert() {
        val root = File.createTempFile("docs", "").apply { delete(); mkdirs() }
        val memory = File(root, "memory")
        val store = MemoryStore(memory)
        store.ensure()
        val book = File(root, "佩莫灯录.pdf")
        book.writeBytes(textLayerPdf("第一章 灯\n佩莫的旗舰产品是青禾灯。"))
        runDocumentImport(book, store)
        val job = readDocJob(File(docsRoot(store), "job.json"))
        assertEquals("done", job.phase)
        val docs = loadIndexedDocs(docsRoot(store))
        assertEquals(1, docs.size)
        val found = searchDocuments("旗舰产品是什么", docs, null).ground
        assertTrue(found!!.answer.contains("青禾灯"))
        val record = listDocRecords(docsRoot(store), store).single()
        assertEquals("佩莫灯录", record.title)
        assertEquals(0, record.consolidated)
        val points = loadDocPoints(File(docsRoot(store), "${record.id}/points.json"))
        assertTrue(points.any { it.text.contains("青禾灯") })
        queueDocPoints(store, record.id, points)
        val pending = gatherPendingDrafts(store, emptyList(), null)
        assertTrue(pending.any { it.statement.contains("青禾灯") })
        assertTrue(store.listExperts().any { it.expert.startsWith("doc_") })
        deleteDocument(store, record.id)
        assertTrue(loadIndexedDocs(docsRoot(store)).isEmpty())
        assertTrue(store.listExperts().none { it.expert.startsWith("doc_") })
        assertTrue(gatherPendingDrafts(store, emptyList(), null).none { it.statement.contains("青禾灯") })
    }

    private fun zip(vararg entries: Pair<String, String>): ByteArray {
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { zip ->
            entries.forEach { (name, text) ->
                zip.putNextEntry(ZipEntry(name))
                zip.write(text.toByteArray(Charsets.UTF_8))
                zip.closeEntry()
            }
        }
        return out.toByteArray()
    }
}
