package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicInteger

class ModelFetchTest {
    @Test
    fun smallFilesUseAdaptiveUnitsAndChineseStatus() {
        assertEquals("800 B", formatBytes(800))
        assertEquals("1.2 KB", formatBytes(1200))
        assertEquals("4.5 MB", formatBytes((4.5 * 1024 * 1024).toLong()))
        assertEquals("下载中", fileStateLabel("zh", "running"))
        assertEquals("等待", fileStateLabel("zh", "wait"))
        assertEquals("完成", fileStateLabel("zh", "done"))
        assertEquals("校验中", fileStateLabel("zh", "checking"))
        assertEquals("失败", fileStateLabel("zh", "error"))
        assertEquals("downloading", fileStateLabel("en", "running"))
        val files = listOf(FileSnap("a", 800, 1200, "running"), FileSnap("b", 0, 1024 * 1024, "wait"))
        val (got, total) = overallBytes(files)
        assertEquals(800L, got)
        assertEquals(1200L + 1024 * 1024, total)
        assertEquals(1L, remainingEtaSeconds(4_500_000, 4_500_000))
        assertTrue(formatEta(90L * 4_500_000, 4_500_000, "zh").contains("分"))
        assertEquals("不到 1 秒", formatEta(800, 4_500_000, "zh"))
        assertEquals("ETA under 1s", formatEta(800, 4_500_000, "en"))
        assertFalse(formatEta(800, 4_500_000, "zh").contains("0 秒"))
    }

    @Test
    fun resumeContinuesFromPartial() {
        val payload = "abcdefgh".toByteArray()
        val manifest = manifestOf(payload, listOf("http://mirror/a"))
        val root = tempRoot()
        val opens = AtomicInteger()
        val fetch = ModelFetch(root, RemoteOpener { _, offset ->
            opens.incrementAndGet()
            if (offset == 0L) RemoteBody(200, payload.size.toLong(), ByteArrayInputStream(payload.copyOfRange(0, 4)))
            else RemoteBody(206, payload.size.toLong(), ByteArrayInputStream(payload.copyOfRange(offset.toInt(), payload.size)))
        }, chunkBytes = 4)
        assertEquals("done", fetch.download(manifest) {})
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
        assertTrue(opens.get() >= 2)
    }

    @Test
    fun checksumMismatchFallsThroughToNextMirror() {
        val good = "abcdefgh".toByteArray()
        val manifest = manifestOf(good, listOf("http://bad/a", "http://good/a"))
        val root = tempRoot()
        val seen = ArrayList<String>()
        val fetch = ModelFetch(root, RemoteOpener { url, _ ->
            seen.add(url)
            val body = if (url.contains("bad")) "xxxxxxxx".toByteArray() else good
            RemoteBody(200, body.size.toLong(), ByteArrayInputStream(body))
        }, chunkBytes = 4)
        assertEquals("done", fetch.download(manifest) {})
        assertEquals(listOf("http://bad/a", "http://good/a"), seen)
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
        assertFalse(File(root, "models/base.gguf.part").exists())
    }

    @Test
    fun failedMirrorIsSkipped() {
        val good = "abcdefgh".toByteArray()
        val manifest = manifestOf(good, listOf("http://down/a", "http://up/a"))
        val root = tempRoot()
        val fetch = ModelFetch(root, RemoteOpener { url, _ ->
            if (url.contains("down")) throw java.io.IOException("连接失败")
            RemoteBody(200, good.size.toLong(), ByteArrayInputStream(good))
        }, chunkBytes = 8)
        assertEquals("done", fetch.download(manifest) {})
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
    }

    @Test
    fun diskCheckStopsBeforeAnyRequest() {
        val good = ByteArray(5000) { 1 }
        val manifest = manifestOf(good, listOf("http://mirror/a"))
        var opened = false
        val fetch = ModelFetch(
            tempRoot(),
            RemoteOpener { _, _ ->
                opened = true
                RemoteBody(200, good.size.toLong(), ByteArrayInputStream(good))
            },
            freeBytes = { 100 },
            reserveBytes = 0,
        )
        val result = fetch.download(manifest) {}
        assertTrue(result.startsWith("error:"))
        assertTrue(result.contains("空间不够"))
        assertFalse(opened)
    }

    @Test
    fun pauseKeepsPartialAndResumeFinishes() {
        val payload = "abcdefgh".toByteArray()
        val manifest = manifestOf(payload, listOf("http://mirror/a"))
        val root = tempRoot()
        val control = FetchControl()
        val fetch = ModelFetch(root, RemoteOpener { _, offset ->
            RemoteBody(if (offset > 0) 206 else 200, payload.size.toLong(), object : InputStream() {
                var pos = offset.toInt()
                override fun read(): Int = if (pos >= payload.size) -1 else payload[pos++].toInt() and 0xff
                override fun read(b: ByteArray, off: Int, len: Int): Int {
                    if (pos >= payload.size) return -1
                    val n = minOf(len, 4, payload.size - pos)
                    System.arraycopy(payload, pos, b, off, n)
                    pos += n
                    control.pause = true
                    return n
                }
            })
        }, control = control, chunkBytes = 4)
        assertEquals("paused", fetch.download(manifest) {})
        assertEquals(4, File(root, "models/base.gguf.part").length())
        control.pause = false
        assertEquals("done", fetch.download(manifest) {})
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
    }

    @Test
    fun ignoredRangeRewritesInsteadOfAppending() {
        val payload = "abcdefgh".toByteArray()
        val manifest = manifestOf(payload, listOf("http://mirror/a"))
        val root = tempRoot()
        val part = File(root, "models/base.gguf.part")
        part.parentFile?.mkdirs()
        part.writeBytes("xxxx".toByteArray())
        val fetch = ModelFetch(root, RemoteOpener { _, _ ->
            RemoteBody(200, payload.size.toLong(), ByteArrayInputStream(payload))
        }, chunkBytes = 8)
        assertEquals("done", fetch.download(manifest) {})
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
    }

    @Test
    fun manifestKeepsMirrorOrder() {
        val parsed = parseManifest(
            """
            {"published":true,"files":[{"id":"base","dest":"models/base.gguf","sha256":"${"00".repeat(32)}","size":1,"urls":["https://modelscope.cn/a","https://hf-mirror.com/a","https://huggingface.co/a","https://github.com/a"]}]}
            """.trimIndent(),
        )
        assertEquals(
            listOf("https://modelscope.cn/a", "https://hf-mirror.com/a", "https://huggingface.co/a", "https://github.com/a"),
            parsed.files.single().urls,
        )
    }

    @Test
    fun httpOpenerSendsRangeAndResumes() {
        val payload = "abcdefgh".toByteArray()
        val server = ServerSocket(0)
        val thread = Thread {
            try {
                while (!server.isClosed) server.accept().use { socket -> serve(socket, payload) }
            } catch (_: Exception) {
            }
        }
        thread.isDaemon = true
        thread.start()
        val root = tempRoot()
        val url = "http://127.0.0.1:${server.localPort}/file"
        val manifest = manifestOf(payload, listOf(url))
        val fetch = ModelFetch(root, RemoteOpener { target, offset -> httpOpen(target, offset) }, chunkBytes = 4)
        assertEquals("done", fetch.download(manifest) {})
        assertEquals("abcdefgh", File(root, "models/base.gguf").readText())
        server.close()
        thread.join(2000)
    }

    private fun serve(socket: Socket, payload: ByteArray) {
        val input = socket.getInputStream()
        val header = ByteArray(4096)
        var n = 0
        while (n < header.size) {
            val b = input.read()
            if (b < 0) break
            header[n++] = b.toByte()
            if (n >= 4 && header[n - 4] == '\r'.code.toByte() && header[n - 3] == '\n'.code.toByte() &&
                header[n - 2] == '\r'.code.toByte() && header[n - 1] == '\n'.code.toByte()
            ) {
                break
            }
        }
        val text = String(header, 0, n, Charsets.ISO_8859_1)
        val rangeLine = text.lineSequence().firstOrNull { it.startsWith("Range:", ignoreCase = true) }
        val range = rangeLine?.substringAfter("=")?.substringBefore("-")?.toIntOrNull() ?: 0
        val out = socket.getOutputStream()
        if (range == 0) {
            val body = payload.copyOfRange(0, 4)
            out.write("HTTP/1.1 200 OK\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
            out.write(body)
        } else {
            val body = payload.copyOfRange(range, payload.size)
            out.write(
                "HTTP/1.1 206 Partial Content\r\nContent-Range: bytes $range-${payload.size - 1}/${payload.size}\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray(),
            )
            out.write(body)
        }
        out.flush()
    }

    private fun manifestOf(payload: ByteArray, urls: List<String>): FetchManifest {
        val sha = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        return FetchManifest(
            true,
            listOf(FetchFile("base", "models/base.gguf", sha, payload.size.toLong(), urls)),
        )
    }

    private fun tempRoot(): File = File.createTempFile("fetch", "").apply {
        delete()
        mkdirs()
    }
}
