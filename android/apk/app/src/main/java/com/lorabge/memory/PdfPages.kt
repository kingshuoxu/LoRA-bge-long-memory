package com.lorabge.memory

import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.text.PDFTextStripper
import java.io.ByteArrayInputStream
import java.io.File
import java.text.Normalizer

/**
 * One page at a time, in page-tree order. ToUnicode and Identity-H come from PdfBox,
 * not from literal Tj strings. A scanned page contributes an empty string.
 */
fun extractPdfPages(bytes: ByteArray): List<String> {
    if (bytes.isEmpty()) return emptyList()
    return PDDocument.load(ByteArrayInputStream(bytes)).use { doc -> readPages(doc) }
}

fun extractPdfFile(file: File): List<String> {
    if (!file.exists() || file.length() == 0L) return emptyList()
    return PDDocument.load(file).use { doc -> readPages(doc) }
}

fun pdfDocumentTitle(bytes: ByteArray): String {
    if (bytes.isEmpty()) return ""
    return runCatching {
        PDDocument.load(ByteArrayInputStream(bytes)).use { doc ->
            doc.documentInformation?.title?.trim().orEmpty()
        }
    }.getOrDefault("")
}

fun pdfDocumentTitle(file: File): String {
    if (!file.exists()) return ""
    return runCatching {
        PDDocument.load(file).use { doc -> doc.documentInformation?.title?.trim().orEmpty() }
    }.getOrDefault("")
}

/** Call once on the phone so PdfBox can see bundled cmap assets. */
fun initPdfBox(context: android.content.Context) {
    runCatching { PDFBoxResourceLoader.init(context) }
}

internal fun joinWrappedLines(text: String): String {
    val out = ArrayList<String>()
    for (raw in text.split('\n')) {
        val line = raw.trim()
        if (line.isEmpty()) continue
        val prev = out.lastOrNull()
        val wrap = prev != null && prev.length >= 12 && headingTitle(prev) == null && headingTitle(line) == null &&
            prev.last() !in "。！？；：" && isCjk(prev.last()) && isCjk(line.first())
        if (wrap) out[out.lastIndex] = prev + line else out.add(line)
    }
    return out.joinToString("\n")
}

private fun isCjk(ch: Char): Boolean = ch in '\u4e00'..'\u9fff'

private fun readPages(doc: PDDocument): List<String> {
    if (doc.numberOfPages <= 0) return emptyList()
    val stripper = PDFTextStripper()
    stripper.sortByPosition = true
    stripper.lineSeparator = "\n"
    stripper.paragraphStart = ""
    stripper.pageStart = ""
    stripper.pageEnd = ""
    val pages = ArrayList<String>(doc.numberOfPages)
    for (page in 1..doc.numberOfPages) {
        stripper.startPage = page
        stripper.endPage = page
        val text = stripper.getText(doc)
        val normalized = joinWrappedLines(Normalizer.normalize(text.replace("\r\n", "\n"), Normalizer.Form.NFKC))
        pages.add(normalized)
    }
    return pages
}
