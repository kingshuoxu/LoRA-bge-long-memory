package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import java.util.zip.Inflater
import java.util.zip.ZipInputStream
import kotlin.math.sqrt

data class DocChunk(
    val id: String,
    val text: String,
    val chapter: String,
    val page: Int,
)

data class DocPoint(
    val id: String,
    val text: String,
    val chapter: String,
    val selected: Boolean = true,
)

data class DocHit(
    val chunk: DocChunk,
    val score: Double,
)

data class DocChip(
    val label: String,
    val passage: String,
    val docId: String = "",
)

data class DocRecord(
    val id: String,
    val title: String,
    val pages: Int,
    val chunks: Int,
    val points: Int,
    val consolidated: Int,
)

data class DocJob(
    val title: String = "",
    val phase: String = "",
    val percent: Int = 0,
    val message: String = "",
    val docId: String = "",
    val source: String = "",
)

data class IndexedDoc(
    val id: String,
    val title: String,
    val expert: String,
    val chunks: List<DocChunk>,
    val vectors: List<FloatArray>?,
)

data class DocGround(
    val answer: String,
    val chips: List<DocChip>,
    val expert: String,
    val docId: String,
)

data class DocSearch(
    val ground: DocGround?,
    val bestScore: Double,
    val titleHit: Boolean,
)

/** A scanned PDF has no text layer. The message is for the person importing it. */
const val PDF_NO_TEXT = "这份 PDF 没有文字层，扫描件暂时还不能读。"

private val chapterHead = Regex("(?m)^(第[0-9０-９一二三四五六七八九十百千]+[章节回部篇].*|#{1,3} .+)$")

fun extractDocument(name: String, bytes: ByteArray): String {
    val lower = name.lowercase()
    val text = when {
        lower.endsWith(".pdf") -> extractPdfTextLayer(bytes)
        lower.endsWith(".epub") -> extractEpub(bytes)
        lower.endsWith(".docx") -> extractDocx(bytes)
        else -> decodePlain(bytes)
    }
    return text.replace("\u0000", "").trim()
}

fun pdfHasTextLayer(bytes: ByteArray): Boolean = extractPdfTextLayer(bytes).isNotBlank()

fun decodePlain(bytes: ByteArray): String {
    val utf8 = bytes.toString(Charsets.UTF_8)
    if (utf8.contains('\uFFFD') && bytes.size > 8) {
        return bytes.toString(Charsets.UTF_16)
    }
    return utf8
}

fun extractDocx(bytes: ByteArray): String {
    val xml = zipEntry(bytes, "word/document.xml") ?: return ""
    return xmlText(xml)
}

fun extractEpub(bytes: ByteArray): String {
    val entries = zipTexts(bytes)
    val opf = entries.entries.firstOrNull { it.key.endsWith(".opf") }?.value.orEmpty()
    val ordered = epubSpine(opf, entries.keys)
    val parts = ArrayList<String>()
    val used = LinkedHashSet<String>()
    for (href in ordered) {
        val hit = entries.entries.firstOrNull { it.key.endsWith(href) || it.key.endsWith("/$href") } ?: continue
        if (!used.add(hit.key)) continue
        val body = xmlText(hit.value)
        if (body.isNotBlank()) parts.add(body)
    }
    if (parts.isEmpty()) {
        entries.filter { it.key.endsWith(".xhtml") || it.key.endsWith(".html") || it.key.endsWith(".htm") }
            .toSortedMap()
            .values
            .forEach { parts.add(xmlText(it)) }
    }
    return parts.joinToString("\n\n")
}

fun extractPdfTextLayer(bytes: ByteArray): String {
    val pages = ArrayList<String>()
    val streamMark = "stream".toByteArray(Charsets.ISO_8859_1)
    val endMark = "endstream".toByteArray(Charsets.ISO_8859_1)
    var cursor = 0
    while (cursor < bytes.size) {
        val streamAt = indexOfBytes(bytes, streamMark, cursor)
        if (streamAt < 0) break
        val dictStart = maxOf(0, streamAt - 240)
        val dict = bytes.copyOfRange(dictStart, streamAt).toString(Charsets.ISO_8859_1)
        var dataStart = streamAt + streamMark.size
        if (dataStart < bytes.size && bytes[dataStart] == '\r'.code.toByte()) dataStart++
        if (dataStart < bytes.size && bytes[dataStart] == '\n'.code.toByte()) dataStart++
        val end = indexOfBytes(bytes, endMark, dataStart)
        if (end < 0) break
        val slice = bytes.copyOfRange(dataStart, end)
        val body = if (dict.contains("FlateDecode")) inflatePdf(slice) else slice
        val text = pdfOperators(body.toString(Charsets.ISO_8859_1))
        if (text.isNotBlank()) pages.add(text)
        cursor = end + endMark.size
    }
    return pages.joinToString("\n\u000c\n")
}

/** A tiny text-layer PDF. Scanned pages have no operators, so this fixture is the supported kind. */
fun textLayerPdf(sentence: String): ByteArray {
    val hex = "FEFF" + sentence.toByteArray(Charsets.UTF_16BE).joinToString("") { "%02X".format(it) }
    val stream = "<$hex> Tj\n".toByteArray(Charsets.US_ASCII)
    val head = "%PDF-1.4\n1 0 obj\n<< /Length ${stream.size} >>\nstream\n".toByteArray(Charsets.US_ASCII)
    val tail = "endstream\nendobj\ntrailer\n<< >>\n%%EOF\n".toByteArray(Charsets.US_ASCII)
    return head + stream + tail
}

fun splitChapters(text: String): List<Pair<String, String>> {
    val matches = chapterHead.findAll(text).toList()
    if (matches.isEmpty()) return listOf("正文" to text.trim())
    val out = ArrayList<Pair<String, String>>()
    if (matches.first().range.first > 0) {
        val preface = text.substring(0, matches.first().range.first).trim()
        if (preface.isNotBlank()) out.add("正文" to preface)
    }
    matches.forEachIndexed { index, match ->
        val start = match.range.last + 1
        val end = if (index + 1 < matches.size) matches[index + 1].range.first else text.length
        val body = text.substring(start, end).trim()
        val title = match.value.trim().trimStart('#').trim()
        if (body.isNotBlank()) out.add(title to body)
    }
    return out.ifEmpty { listOf("正文" to text.trim()) }
}

fun chunkPassages(text: String, chapter: String = "正文", page: Int = 1): List<DocChunk> {
    val clean = text.replace("\r\n", "\n").trim()
    if (clean.isEmpty()) return emptyList()
    if (clean.contains('\u000c')) {
        val out = ArrayList<DocChunk>()
        clean.split('\u000c').forEachIndexed { index, pageText ->
            out.addAll(chunkPassages(pageText, chapter, page + index))
        }
        return out.mapIndexed { index, chunk -> chunk.copy(id = "c$index") }
    }
    if (clean.length <= 500) {
        return listOf(DocChunk(id = "c0", text = clean, chapter = chapter, page = page))
    }
    val out = ArrayList<DocChunk>()
    var cursor = 0
    var pageNo = page
    var guard = 0
    while (cursor < clean.length && guard++ < 10000) {
        var end = (cursor + 420).coerceAtMost(clean.length)
        if (end < clean.length) {
            val breakAt = clean.lastIndexOf('。', end).takeIf { it > cursor + 280 }
                ?: clean.lastIndexOf('\n', end).takeIf { it > cursor + 280 }
            if (breakAt != null) end = (breakAt + 1).coerceAtMost(clean.length)
        }
        val slice = clean.substring(cursor, end).trim()
        if (slice.isNotEmpty()) {
            val pages = slice.count { it == '\u000c' }
            out.add(DocChunk("c${out.size}", slice.replace("\u000c", "\n"), chapter, pageNo))
            pageNo += pages
        }
        if (end >= clean.length) break
        val next = (end - 80).coerceAtLeast(cursor + 1)
        cursor = next
    }
    return out
}

fun chunkBook(text: String): List<DocChunk> {
    val out = ArrayList<DocChunk>()
    var page = 1
    for ((chapter, body) in splitChapters(text)) {
        val pieces = chunkPassages(body, chapter, page)
        out.addAll(pieces)
        val last = pieces.maxOfOrNull { it.page } ?: page
        page = last + 1
    }
    return out.mapIndexed { index, chunk -> chunk.copy(id = "c$index") }
}

fun extractKeyPoints(
    chapters: List<Pair<String, String>>,
    perChapter: Int = 5,
    totalCap: Int = 40,
    ask: ((String) -> String)? = null,
): List<DocPoint> {
    val out = ArrayList<DocPoint>()
    for ((chapter, body) in chapters) {
        if (out.size >= totalCap) break
        val fromLlm = if (ask != null) parseKeyLines(ask(chapterPrompt(chapter, body))) else emptyList()
        val lines = (if (fromLlm.isNotEmpty()) fromLlm else heuristicKeys(body)).take(perChapter)
        for (line in lines) {
            if (out.size >= totalCap) break
            if (out.any { isSameMemory(it.text, line) }) continue
            out.add(DocPoint("p${out.size}", line, chapter, true))
        }
    }
    return out
}

fun retrieveDocs(
    query: String,
    chunks: List<DocChunk>,
    vectors: List<FloatArray>?,
    queryVector: FloatArray?,
): List<DocHit> {
    if (chunks.isEmpty() || query.isBlank()) return emptyList()
    val scored = if (queryVector != null && vectors != null && vectors.size == chunks.size) {
        chunks.mapIndexed { index, chunk -> DocHit(chunk, cosineSimilarity(queryVector, vectors[index])) }
    } else {
        chunks.map { chunk -> DocHit(chunk, lexicalScore(query, chunk.text)) }
    }
    return scored.sortedByDescending { it.score }.take(3)
}

fun groundDocument(query: String, hits: List<DocHit>, title: String, minScore: Double): Pair<String, List<DocChip>>? {
    val useful = hits.filter { it.score >= minScore }
    if (useful.isEmpty()) return null
    val best = useful.first().chunk
    val sentence = bestSentence(query, best.text)
    val chips = useful.map { hit ->
        val where = if (hit.chunk.page > 0) "第${hit.chunk.page}页" else hit.chunk.chapter
        val chapter = hit.chunk.chapter.takeIf { it.isNotBlank() && it != "正文" }?.let { " · $it" }.orEmpty()
        DocChip("《$title》$where$chapter", hit.chunk.text, "")
    }
    return sentence to chips
}

fun docMinScore(usedVectors: Boolean): Double = if (usedVectors) 0.45 else 0.18

fun trainMinutes(count: Int): Int = (count * 2).coerceAtLeast(if (count == 0) 0 else 1)

fun docPhaseLabel(phase: String, lang: String): String {
    val zh = lang != "en"
    return when (phase) {
        "parse" -> if (zh) "解析" else "Reading"
        "split" -> if (zh) "切分" else "Splitting"
        "index" -> if (zh) "建索引" else "Indexing"
        "points" -> if (zh) "提取重点" else "Key points"
        "done" -> if (zh) "完成" else "Done"
        "error" -> if (zh) "没有完成" else "Stopped"
        "cancelled" -> if (zh) "已取消" else "Cancelled"
        else -> if (zh) "准备" else "Preparing"
    }
}

private fun chapterPrompt(chapter: String, body: String): String {
    val clip = body.take(1500)
    return "请只列出《$chapter》里最多5条关键事实，每行一条，不要编号。\n$clip"
}

private fun parseKeyLines(raw: String): List<String> {
    return raw.lineSequence()
        .map { it.trim().trimStart('-', '•', ' ', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '、') }
        .map { it.trim() }
        .filter { it.length in 6..80 && !it.endsWith("？") && !it.endsWith("?") }
        .take(5)
        .toList()
}

private fun heuristicKeys(body: String): List<String> {
    val cues = listOf("是", "叫", "成立", "位于", "称为", "定义", "因此", "结论", "总部")
    return body.split(Regex("[。！!\n]+"))
        .map { it.trim() }
        .filter { line -> line.length in 8..80 && cues.any { it in line } && "什么" !in line && "吗" !in line }
        .distinct()
        .take(5)
}

private fun bestSentence(query: String, passage: String): String {
    val parts = passage.split(Regex("[。！!\n]+")).map { it.trim() }.filter { it.length >= 4 }
    if (parts.isEmpty()) return passage.trim()
    val q = normalizeFactKey(query)
    return parts.maxBy { lexicalScore(q, normalizeFactKey(it)) }.let { if (it.endsWith("。")) it else "$it。" }
}

internal fun lexicalScore(query: String, text: String): Double {
    val left = bigrams(normalizeFactKey(query))
    val right = bigrams(normalizeFactKey(text))
    if (left.isEmpty() || right.isEmpty()) return 0.0
    val shared = left.count { it in right }
    return shared.toDouble() / sqrt(left.size.toDouble() * right.size)
}

private fun bigrams(text: String): List<String> {
    if (text.length < 2) return listOf(text).filter { it.isNotBlank() }
    return (0 until text.length - 1).map { text.substring(it, it + 2) }
}

private fun zipEntry(bytes: ByteArray, name: String): String? {
    return zipTexts(bytes)[name]
}

private fun zipTexts(bytes: ByteArray): Map<String, String> {
    val out = LinkedHashMap<String, String>()
    ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
        var entry = zip.nextEntry
        while (entry != null) {
            if (!entry.isDirectory && entry.size < 4_000_000) {
                val data = zip.readBytes()
                if (entry.name.endsWith(".xml") || entry.name.endsWith(".xhtml") || entry.name.endsWith(".html") ||
                    entry.name.endsWith(".htm") || entry.name.endsWith(".opf") || entry.name.endsWith(".txt")
                ) {
                    out[entry.name] = data.toString(Charsets.UTF_8)
                }
            }
            zip.closeEntry()
            entry = zip.nextEntry
        }
    }
    return out
}

private fun xmlText(xml: String): String {
    val chunks = Regex("<(?:w:t|title|h1|h2|h3|p)[^>]*>(.*?)</(?:w:t|title|h1|h2|h3|p)>", RegexOption.IGNORE_CASE)
        .findAll(xml)
        .map { decodeXml(it.groupValues[1]) }
        .filter { it.isNotBlank() }
        .toList()
    if (chunks.isNotEmpty()) return chunks.joinToString("\n")
    return decodeXml(xml.replace(Regex("<[^>]+>"), " ")).replace(Regex("\\s+"), " ").trim()
}

private fun decodeXml(text: String): String {
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", "\"").trim()
}

private fun epubSpine(opf: String, names: Set<String>): List<String> {
    val manifest = Regex("id=\"([^\"]+)\"[^>]*href=\"([^\"]+)\"").findAll(opf).associate { it.groupValues[1] to it.groupValues[2] }
    val spine = Regex("<itemref[^>]*idref=\"([^\"]+)\"").findAll(opf).map { manifest[it.groupValues[1]] }.filterNotNull().toList()
    if (spine.isNotEmpty()) return spine
    return names.filter { it.endsWith(".xhtml") || it.endsWith(".html") }.sorted()
}

private fun inflatePdf(data: ByteArray): ByteArray {
    val inflater = Inflater()
    inflater.setInput(data)
    val out = ByteArrayOutputStream()
    val buf = ByteArray(8192)
    return try {
        while (!inflater.finished()) {
            val n = inflater.inflate(buf)
            if (n == 0) break
            out.write(buf, 0, n)
        }
        out.toByteArray()
    } catch (_: Throwable) {
        data
    } finally {
        inflater.end()
    }
}

private fun pdfOperators(stream: String): String {
    val out = StringBuilder()
    Regex("\\((?:\\\\.|[^\\\\)])*\\)\\s*Tj").findAll(stream).forEach { match ->
        val raw = match.value.substringBeforeLast(")").substringAfter("(")
        out.append(unescapePdf(raw))
    }
    Regex("<([0-9A-Fa-f\\s]+)>\\s*Tj").findAll(stream).forEach { match ->
        out.append(decodePdfHex(match.groupValues[1]))
    }
    return out.toString().trim()
}

private fun unescapePdf(text: String): String {
    val out = StringBuilder()
    var i = 0
    while (i < text.length) {
        if (text[i] == '\\' && i + 1 < text.length) {
            out.append(text[i + 1])
            i += 2
        } else {
            out.append(text[i])
            i++
        }
    }
    return out.toString()
}

private fun decodePdfHex(hex: String): String {
    val clean = hex.replace(Regex("\\s"), "")
    if (clean.length < 4) return ""
    val bytes = ByteArray(clean.length / 2)
    var n = 0
    var i = 0
    while (i + 1 < clean.length) {
        bytes[n++] = clean.substring(i, i + 2).toInt(16).toByte()
        i += 2
    }
    val slice = bytes.copyOf(n)
    return if (n >= 2 && slice[0] == 0xFE.toByte() && slice[1] == 0xFF.toByte()) {
        slice.toString(Charsets.UTF_16)
    } else {
        slice.toString(Charsets.UTF_8)
    }
}

fun readDocJob(file: File): DocJob {
    if (!file.exists()) return DocJob()
    val obj = runCatching { JSONObject(file.readText()) }.getOrNull() ?: return DocJob()
    return DocJob(
        title = obj.optString("title"),
        phase = obj.optString("phase"),
        percent = obj.optInt("percent"),
        message = obj.optString("message"),
        docId = obj.optString("docId"),
        source = obj.optString("source"),
    )
}

fun writeDocJob(file: File, job: DocJob) {
    file.parentFile?.mkdirs()
    writeTextAtomic(
        file,
        JSONObject()
            .put("title", job.title)
            .put("phase", job.phase)
            .put("percent", job.percent)
            .put("message", job.message)
            .put("docId", job.docId)
            .put("source", job.source)
            .toString(),
    )
}

fun loadDocChunks(file: File): List<DocChunk> {
    if (!file.exists()) return emptyList()
    return file.readLines().mapNotNull { line ->
        val obj = runCatching { JSONObject(line) }.getOrNull() ?: return@mapNotNull null
        DocChunk(obj.optString("id"), obj.optString("text"), obj.optString("chapter"), obj.optInt("page", 1))
    }
}

fun loadDocPoints(file: File): List<DocPoint> {
    if (!file.exists()) return emptyList()
    val arr = runCatching { JSONArray(file.readText()) }.getOrNull() ?: return emptyList()
    val out = ArrayList<DocPoint>()
    for (i in 0 until arr.length()) {
        val obj = arr.optJSONObject(i) ?: continue
        out.add(DocPoint(obj.optString("id"), obj.optString("text"), obj.optString("chapter"), obj.optBoolean("selected", true)))
    }
    return out
}

fun saveDocPoints(file: File, points: List<DocPoint>) {
    val arr = JSONArray()
    points.forEach { point ->
        arr.put(
            JSONObject()
                .put("id", point.id)
                .put("text", point.text)
                .put("chapter", point.chapter)
                .put("selected", point.selected),
        )
    }
    file.parentFile?.mkdirs()
    writeTextAtomic(file, arr.toString())
}

fun docsRoot(store: MemoryStore): File = File(store.root.parentFile ?: store.root, "docs")

fun docTitleOf(name: String): String {
    val bare = name.substringAfterLast('/').substringBeforeLast('.')
    return bare.ifBlank { "未命名" }
}

fun pdfNoText(lang: String): String {
    return if (lang == "en") "This PDF has no text layer. Scanned pages aren't supported yet." else PDF_NO_TEXT
}

fun trainEstimate(count: Int, lang: String): String {
    val minutes = trainMinutes(count)
    return if (lang == "en") "About $minutes min on CPU" else "大约 $minutes 分钟（CPU）"
}

fun documentMiss(title: String, lang: String): String {
    return if (lang == "en") "Nothing relevant turned up in $title." else "《$title》里没有找到相关内容。"
}

fun searchDocuments(query: String, docs: List<IndexedDoc>, queryVector: FloatArray?): DocSearch {
    if (docs.isEmpty() || query.isBlank()) return DocSearch(null, 0.0, false)
    val titleHit = docs.any { it.title.length >= 2 && query.contains(it.title) }
    var bestScore = 0.0
    var best: DocGround? = null
    for (doc in docs) {
        val vectors = doc.vectors
        val usedVectors = queryVector != null && vectors != null && vectors.size == doc.chunks.size
        val hits = retrieveDocs(query, doc.chunks, if (usedVectors) vectors else null, if (usedVectors) queryVector else null)
        val score = hits.firstOrNull()?.score ?: 0.0
        if (score > bestScore) bestScore = score
        val grounded = groundDocument(query, hits, doc.title, docMinScore(usedVectors)) ?: continue
        if (best == null || score >= bestScore) {
            best = DocGround(
                grounded.first,
                grounded.second.map { it.copy(docId = doc.id) },
                doc.expert,
                doc.id,
            )
        }
    }
    return DocSearch(best, bestScore, titleHit)
}

/**
 * Naming the book and missing, or a lexical near-miss, should say so.
 * Vector scores stay above zero for unrelated text, so those still fall through.
 */
fun admitNoPassage(search: DocSearch, minScore: Double = 0.18, usedVectors: Boolean = false): Boolean {
    if (search.ground != null) return false
    if (search.titleHit) return true
    if (usedVectors) return false
    return search.bestScore > 0.08 && search.bestScore < minScore
}

fun loadIndexedDocs(root: File): List<IndexedDoc> {
    if (!root.exists()) return emptyList()
    val out = ArrayList<IndexedDoc>()
    for (dir in root.listFiles().orEmpty().sortedBy { it.name }) {
        if (!dir.isDirectory) continue
        val meta = readDocMeta(File(dir, "meta.json")) ?: continue
        val chunks = loadDocChunks(File(dir, "chunks.jsonl"))
        if (chunks.isEmpty()) continue
        val vectors = loadVectors(File(dir, "vectors.f32"), chunks.size, meta.dim)
        out.add(IndexedDoc(meta.id, meta.title, meta.expert, chunks, vectors))
    }
    return out
}

fun listDocRecords(root: File, store: MemoryStore): List<DocRecord> {
    if (!root.exists()) return emptyList()
    val out = ArrayList<DocRecord>()
    for (dir in root.listFiles().orEmpty().sortedBy { it.name }) {
        if (!dir.isDirectory) continue
        val meta = readDocMeta(File(dir, "meta.json")) ?: continue
        val points = loadDocPoints(File(dir, "points.json"))
        val stored = store.readReviewedFacts(meta.expert).map { it.statement }.filter { !it.startsWith("已导入《") }
        val consolidated = points.count { point -> stored.any { isSameMemory(point.text, it) } }
        out.add(DocRecord(meta.id, meta.title, meta.pages, meta.chunks, points.size, consolidated))
    }
    return out
}

/**
 * Parse, chunk, index and extract key points. A killed run keeps the files it finished
 * and the next start of the same source continues. Cancel drops the partial directory.
 */
fun runDocumentImport(
    source: File,
    store: MemoryStore,
    embed: ((List<String>) -> List<FloatArray>)? = null,
    ask: ((String) -> String)? = null,
    cancelled: () -> Boolean = { false },
    onProgress: (DocJob) -> Unit = {},
) {
    val root = docsRoot(store)
    root.mkdirs()
    val jobFile = File(root, "job.json")
    val prior = readDocJob(jobFile)
    val resume = prior.source == source.absolutePath && prior.docId.isNotBlank() &&
        prior.phase in setOf("parse", "split", "index", "points")
    val id = if (resume) prior.docId else UUID.randomUUID().toString().take(8)
    val title = docTitleOf(source.name)
    val dir = File(root, id)
    dir.mkdirs()
    fun report(phase: String, percent: Int, message: String = "") {
        val job = DocJob(title, phase, percent, message, id, source.absolutePath)
        writeDocJob(jobFile, job)
        onProgress(job)
    }
    if (cancelled()) {
        report("cancelled", prior.percent, "")
        dir.deleteRecursively()
        return
    }
    try {
        val raw = File(dir, "raw.txt")
        if (!resume || !raw.exists() || raw.length() == 0L) {
            report("parse", 8)
            if (source.length() > 48L * 1024 * 1024) {
                report("error", 8, "这份文件太大。")
                return
            }
            val text = extractDocument(source.name, source.readBytes())
            if (text.isBlank()) {
                val message = if (source.name.lowercase().endsWith(".pdf")) PDF_NO_TEXT else "没有读出文字。"
                report("error", 8, message)
                dir.deleteRecursively()
                return
            }
            raw.writeText(text)
        }
        if (cancelled()) {
            report("cancelled", 20)
            dir.deleteRecursively()
            return
        }
        val text = raw.readText()
        val chunksFile = File(dir, "chunks.jsonl")
        val chunks = if (resume && chunksFile.exists() && chunksFile.length() > 0L) {
            loadDocChunks(chunksFile)
        } else {
            report("split", 30)
            val built = chunkBook(text)
            writeChunks(chunksFile, built)
            built
        }
        if (cancelled()) {
            report("cancelled", 40)
            dir.deleteRecursively()
            return
        }
        val dimFile = File(dir, "vectors.f32")
        var dim = 0
        if (embed != null && chunks.isNotEmpty() && (!dimFile.exists() || dimFile.length() == 0L)) {
            val rows = ArrayList<FloatArray>()
            val batches = chunks.chunked(4)
            var stopped = false
            for ((index, part) in batches.withIndex()) {
                if (cancelled()) {
                    stopped = true
                    break
                }
                val got = runCatching { embed(part.map { it.text }) }.getOrNull()
                if (got == null || got.size != part.size) {
                    rows.clear()
                    break
                }
                rows.addAll(got)
                val percent = 40 + ((index + 1) * 35 / batches.size)
                report("index", percent)
            }
            if (stopped) {
                report("cancelled", 60)
                dir.deleteRecursively()
                return
            }
            if (rows.size == chunks.size) {
                dim = rows.first().size
                val partial = File(dir, "vectors.f32.partial")
                writeVectors(partial, rows)
                if (!partial.renameTo(dimFile)) partial.copyTo(dimFile, overwrite = true)
            }
        } else if (dimFile.exists() && chunks.isNotEmpty()) {
            val bytes = dimFile.length()
            if (bytes > 0 && bytes % (chunks.size * 4L) == 0L) dim = (bytes / (chunks.size * 4L)).toInt()
        }
        if (cancelled()) {
            report("cancelled", 70)
            dir.deleteRecursively()
            return
        }
        report("points", 88)
        val pointsFile = File(dir, "points.json")
        val points = if (pointsFile.exists() && pointsFile.length() > 2) {
            loadDocPoints(pointsFile)
        } else {
            val limited = ask?.let { rawAsk ->
                var calls = 0
                { prompt: String ->
                    if (calls >= 8) "" else {
                        calls += 1
                        runCatching { rawAsk(prompt) }.getOrDefault("")
                    }
                }
            }
            extractKeyPoints(splitChapters(text), ask = limited).also { saveDocPoints(pointsFile, it) }
        }
        val pages = text.count { it == '\u000c' } + 1
        val expert = "doc_$id"
        writeDocMeta(File(dir, "meta.json"), DocMeta(id, title, pages, chunks.size, expert, dim))
        val placeholder = ReviewedFact(
            entity = title,
            statement = "已导入《$title》。",
            value = title,
            qa = emptyList(),
            sources = emptyList(),
            attr = "文档",
        )
        if (store.listExperts().none { it.expert == expert }) {
            val batch = (store.listExperts().maxOfOrNull { it.batch } ?: -1) + 1
            store.registerExpert(
                ExpertRecord(expert, batch, 1, 32, "experts/$expert/router_key.f32", "experts/$expert/adapter.gguf"),
                listOf(placeholder),
            )
        }
        report("done", 100)
    } catch (err: Throwable) {
        report("error", 0, err.message ?: "没有完成")
    }
}

fun queueDocPoints(store: MemoryStore, docId: String, points: List<DocPoint>) {
    val root = docsRoot(store)
    val dir = File(root, docId)
    saveDocPoints(File(dir, "points.json"), points)
    val selected = points.filter { it.selected && it.text.isNotBlank() }
    val queued = JSONArray()
    selected.forEach { queued.put(it.text) }
    writeTextAtomic(File(dir, "queued.json"), queued.toString())
    if (selected.isEmpty()) return
    val now = java.time.Instant.now().toString()
    val existing = store.loadConversation("c-docs")
    val base = existing ?: Conversation("c-docs", "文档重点", now, now, emptyList())
    val additions = selected.map { point ->
        val line = point.text.trim().trimEnd('。', '.')
        ChatMessage("user", "$line。")
    }.filter { message ->
        base.messages.none { isSameMemory(it.content, message.content) }
    }
    if (additions.isEmpty() && existing != null) return
    store.saveConversation(base.copy(updated = now, messages = base.messages + additions))
}

fun docPointDraft(store: MemoryStore, line: String): FactDraft? {
    val root = docsRoot(store)
    if (!root.exists()) return null
    for (dir in root.listFiles().orEmpty()) {
        if (!dir.isDirectory) continue
        val meta = readDocMeta(File(dir, "meta.json")) ?: continue
        val hit = loadDocPoints(File(dir, "points.json")).firstOrNull { point ->
            point.selected && isSameMemory(point.text, line)
        } ?: continue
        val statement = line.trim().trimEnd('。', '.').let { if (it.isEmpty()) it else "$it。" }
        if (statement.isEmpty()) return null
        return FactDraft(
            meta.title,
            hit.chapter.ifBlank { "文档" },
            statement,
            hit.text.take(24),
            "《${meta.title}》里提到什么？",
            hit.text,
        )
    }
    return null
}

fun docExpertFor(store: MemoryStore, statements: List<String>): String? {
    val lines = statements.map { it.trim() }.filter { it.isNotEmpty() }
    if (lines.isEmpty()) return null
    val root = docsRoot(store)
    if (!root.exists()) return null
    var found: String? = null
    for (dir in root.listFiles().orEmpty()) {
        if (!dir.isDirectory) continue
        val meta = readDocMeta(File(dir, "meta.json")) ?: continue
        val points = loadDocPoints(File(dir, "points.json")).filter { it.selected }
        if (points.isEmpty()) continue
        if (!lines.all { line -> points.any { isSameMemory(it.text, line) } }) continue
        if (found != null && found != meta.expert) return null
        found = meta.expert
    }
    return found
}

fun docTitleForExpert(store: MemoryStore, expert: String): String {
    val root = docsRoot(store)
    for (dir in root.listFiles().orEmpty()) {
        val meta = readDocMeta(File(dir, "meta.json")) ?: continue
        if (meta.expert == expert) return meta.title
    }
    return ""
}

fun deleteDocument(store: MemoryStore, docId: String) {
    val root = docsRoot(store)
    val dir = File(root, docId)
    val meta = readDocMeta(File(dir, "meta.json"))
    val points = loadDocPoints(File(dir, "points.json"))
    if (meta != null) store.deleteExpert(meta.expert)
    val conv = store.loadConversation("c-docs")
    if (conv != null && points.isNotEmpty()) {
        val kept = conv.messages.filter { message ->
            points.none { isSameMemory(it.text, message.content) }
        }
        store.saveConversation(conv.copy(messages = kept))
    }
    dir.deleteRecursively()
}

private data class DocMeta(
    val id: String,
    val title: String,
    val pages: Int,
    val chunks: Int,
    val expert: String,
    val dim: Int,
)

private fun readDocMeta(file: File): DocMeta? {
    if (!file.exists()) return null
    val obj = runCatching { JSONObject(file.readText()) }.getOrNull() ?: return null
    val id = obj.optString("id")
    if (id.isBlank()) return null
    return DocMeta(
        id,
        obj.optString("title"),
        obj.optInt("pages", 1),
        obj.optInt("chunks"),
        obj.optString("expert").ifBlank { "doc_$id" },
        obj.optInt("dim"),
    )
}

private fun writeDocMeta(file: File, meta: DocMeta) {
    writeTextAtomic(
        file,
        JSONObject()
            .put("id", meta.id)
            .put("title", meta.title)
            .put("pages", meta.pages)
            .put("chunks", meta.chunks)
            .put("expert", meta.expert)
            .put("dim", meta.dim)
            .toString(),
    )
}

private fun writeChunks(file: File, chunks: List<DocChunk>) {
    file.parentFile?.mkdirs()
    val text = chunks.joinToString("\n") { chunk ->
        JSONObject()
            .put("id", chunk.id)
            .put("text", chunk.text)
            .put("chapter", chunk.chapter)
            .put("page", chunk.page)
            .toString()
    }
    writeTextAtomic(file, text)
}

private fun writeVectors(file: File, rows: List<FloatArray>) {
    file.parentFile?.mkdirs()
    file.outputStream().buffered().use { out ->
        val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
        for (row in rows) {
            for (value in row) {
                buf.clear()
                buf.putFloat(value)
                out.write(buf.array())
            }
        }
    }
}

private fun loadVectors(file: File, rows: Int, dim: Int): List<FloatArray>? {
    if (!file.exists() || dim <= 0 || rows <= 0) return null
    val expected = rows.toLong() * dim * 4L
    if (file.length() != expected) return null
    val bytes = file.readBytes()
    val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    val out = ArrayList<FloatArray>(rows)
    repeat(rows) {
        val row = FloatArray(dim)
        for (i in 0 until dim) row[i] = buf.float
        out.add(row)
    }
    return out
}

private fun indexOfBytes(data: ByteArray, pattern: ByteArray, from: Int): Int {
    if (pattern.isEmpty() || from >= data.size) return -1
    val last = data.size - pattern.size
    var i = from.coerceAtLeast(0)
    while (i <= last) {
        var matched = true
        for (j in pattern.indices) {
            if (data[i + j] != pattern[j]) {
                matched = false
                break
            }
        }
        if (matched) return i
        i++
    }
    return -1
}
