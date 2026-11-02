package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.Deflater
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
        assertTrue(text.contains("青禾灯"))
        assertTrue(pdfHasTextLayer(pdf))
        val scanned = "%PDF-1.4\n1 0 obj\n<< /Length 4 >>\nstream\nimg\nendstream\nendobj\n".toByteArray()
        assertFalse(pdfHasTextLayer(scanned))
        assertEquals("", extractDocument("scan.pdf", scanned))
    }

    @Test
    fun flatePdfRoundTrip() {
        val sentence = "(Qinghe lamp.) Tj\n"
        val raw = sentence.toByteArray(Charsets.US_ASCII)
        val deflater = Deflater()
        deflater.setInput(raw)
        deflater.finish()
        val buf = ByteArray(128)
        val n = deflater.deflate(buf)
        deflater.end()
        val body = buf.copyOf(n)
        val head = "%PDF-1.4\n1 0 obj\n<< /Filter /FlateDecode /Length ${body.size} >>\nstream\n".toByteArray()
        val tail = "endstream\nendobj\n%%EOF\n".toByteArray()
        val text = extractPdfTextLayer(head + body + tail)
        assertTrue(text.contains("Qinghe"))
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
