package com.lorabge.memory

import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

data class FetchFile(
    val id: String,
    val dest: String,
    val sha256: String,
    val size: Long,
    val urls: List<String>,
)

data class FetchManifest(val published: Boolean, val files: List<FetchFile>)

data class FileSnap(val dest: String, val bytes: Long, val size: Long, val state: String)

data class FetchSnapshot(
    val state: String,
    val message: String,
    val mirror: String,
    val speedBps: Long,
    val files: List<FileSnap>,
)

class RemoteBody(val code: Int, val totalSize: Long, val stream: InputStream) : AutoCloseable {
    override fun close() {
        stream.close()
    }
}

fun interface RemoteOpener {
    fun open(url: String, offset: Long): RemoteBody
}

class FetchControl {
    @Volatile var pause: Boolean = false
    @Volatile var onlineCheck: () -> Boolean = { true }
    val online: Boolean get() = onlineCheck()
}

fun parseManifest(text: String): FetchManifest {
    val obj = JSONObject(text)
    val published = obj.optBoolean("published", true)
    val rows = obj.optJSONArray("files")
    val files = ArrayList<FetchFile>()
    if (rows != null) {
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val urlsJson = row.getJSONArray("urls")
            val urls = ArrayList<String>()
            for (j in 0 until urlsJson.length()) urls.add(urlsJson.getString(j))
            files.add(
                FetchFile(
                    id = row.optString("id", row.getString("dest")),
                    dest = row.getString("dest"),
                    sha256 = row.getString("sha256").lowercase(),
                    size = row.getLong("size"),
                    urls = urls,
                ),
            )
        }
    }
    return FetchManifest(published, files)
}

fun sha256File(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buf = ByteArray(1024 * 1024)
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            digest.update(buf, 0, n)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

fun httpOpen(url: String, offset: Long): RemoteBody {
    val conn = URL(url).openConnection() as HttpURLConnection
    conn.instanceFollowRedirects = true
    conn.connectTimeout = 20_000
    conn.readTimeout = 60_000
    conn.setRequestProperty("User-Agent", "lorabge-memory/0.1")
    if (offset > 0) conn.setRequestProperty("Range", "bytes=$offset-")
    val code = conn.responseCode
    val stream = if (code in 200..299) conn.inputStream else conn.errorStream ?: InputStream.nullInputStream()
    val range = conn.getHeaderField("Content-Range")
    val total = range?.substringAfter("/")?.toLongOrNull()
        ?: if (offset == 0L) conn.contentLengthLong.coerceAtLeast(0) else -1L
    return RemoteBody(code, total, stream)
}

fun bytesOfText(urls: List<String>, limit: Int = 8 * 1024 * 1024): String {
    var last = "没有地址"
    for (url in urls) {
        try {
            httpOpen(url, 0).use { body ->
                if (body.code !in 200..299) {
                    last = "HTTP ${body.code}"
                    return@use
                }
                val buf = ByteArray(limit + 1)
                var got = 0
                while (got < buf.size) {
                    val n = body.stream.read(buf, got, buf.size - got)
                    if (n < 0) break
                    got += n
                }
                if (got > limit) throw java.io.IOException("清单太大")
                return String(buf, 0, got, Charsets.UTF_8)
            }
        } catch (err: Exception) {
            last = err.message ?: "失败"
        }
    }
    throw java.io.IOException(last)
}

class ModelFetch(
    private val root: File,
    private val opener: RemoteOpener,
    private val control: FetchControl = FetchControl(),
    private val freeBytes: () -> Long = { Long.MAX_VALUE },
    private val reserveBytes: Long = 64L * 1024 * 1024,
    private val chunkBytes: Int = 1024 * 1024,
) {
    fun download(manifest: FetchManifest, onUpdate: (FetchSnapshot) -> Unit): String {
        val snaps = manifest.files.map { FileSnap(it.dest, existingBytes(it), it.size, "wait") }.toMutableList()
        fun publish(state: String, message: String, mirror: String, speed: Long) {
            onUpdate(FetchSnapshot(state, message, mirror, speed, snaps.toList()))
        }
        val need = manifest.files.sumOf { file ->
            val dest = File(root, file.dest)
            if (dest.exists() && dest.length() == file.size) 0L
            else {
                val part = File(root, file.dest + ".part")
                (file.size - (if (part.exists()) part.length() else 0L)).coerceAtLeast(0L)
            }
        }
        val free = freeBytes()
        if (need > 0 && free < need + reserveBytes) {
            val message = "空间不够。还要约 ${need / (1024 * 1024)} MB，可用 ${free / (1024 * 1024)} MB。"
            publish("error", message, "", 0)
            return "error: $message"
        }
        var speed = 0L
        for ((index, file) in manifest.files.withIndex()) {
            if (control.pause || !control.online) {
                snaps[index] = snaps[index].copy(state = "paused")
                publish("paused", if (control.online) "已暂停" else "等待 Wi-Fi", "", speed)
                return "paused"
            }
            val result = downloadOne(file, index, snaps, { mirror, nextSpeed, message, state ->
                speed = nextSpeed
                publish(state, message, mirror, speed)
            })
            if (result == "paused") return "paused"
            if (result.startsWith("error:")) {
                publish("error", result.removePrefix("error: "), "", speed)
                return result
            }
        }
        publish("done", "下载完成", "", 0)
        return "done"
    }

    private fun existingBytes(file: FetchFile): Long {
        val dest = File(root, file.dest)
        if (dest.exists()) return dest.length()
        val part = File(root, file.dest + ".part")
        return if (part.exists()) part.length() else 0L
    }

    private fun downloadOne(
        file: FetchFile,
        index: Int,
        snaps: MutableList<FileSnap>,
        publish: (String, Long, String, String) -> Unit,
    ): String {
        val dest = File(root, file.dest)
        dest.parentFile?.mkdirs()
        val part = File(dest.parentFile, dest.name + ".part")
        if (dest.exists() && dest.length() == file.size && sha256File(dest) == file.sha256) {
            snaps[index] = FileSnap(file.dest, file.size, file.size, "done")
            publish("", 0, "", "running")
            return "done"
        }
        if (dest.exists()) dest.delete()
        if (file.urls.isEmpty()) return "error: ${file.dest} 没有地址"
        var last = "没有可用的镜像"
        for (url in file.urls) {
            if (control.pause || !control.online) {
                snaps[index] = FileSnap(file.dest, part.length(), file.size, "paused")
                return "paused"
            }
            val host = runCatching { URL(url).host }.getOrDefault(url)
            snaps[index] = FileSnap(file.dest, if (part.exists()) part.length() else 0L, file.size, "running")
            publish(host, 0, "", "running")
            val outcome = try {
                pull(url, file, part, dest, index, snaps, publish)
            } catch (err: Exception) {
                "error: ${err.message ?: "失败"}"
            }
            if (outcome == "done" || outcome == "paused") return outcome
            last = outcome.removePrefix("error: ")
        }
        part.delete()
        snaps[index] = FileSnap(file.dest, 0, file.size, "error")
        return "error: $last"
    }

    private fun pull(
        url: String,
        file: FetchFile,
        part: File,
        dest: File,
        index: Int,
        snaps: MutableList<FileSnap>,
        publish: (String, Long, String, String) -> Unit,
    ): String {
        val host = runCatching { URL(url).host }.getOrDefault(url)
        var attempts = 0
        while (part.exists().not() || part.length() < file.size) {
            if (control.pause || !control.online) return "paused"
            attempts += 1
            if (attempts > 8) return "error: 中断太多次"
            val offset = if (part.exists()) part.length() else 0L
            opener.open(url, offset).use { body ->
                if (body.code !in listOf(200, 206)) return "error: HTTP ${body.code}"
                if (offset > 0 && body.code == 200) {
                    part.delete()
                    return@use
                }
                val append = offset > 0 && body.code == 206
                FileOutputStream(part, append).use { out ->
                    val buf = ByteArray(chunkBytes)
                    var written = if (part.exists()) part.length() else 0L
                    var window = 0L
                    var tick = System.nanoTime()
                    while (written < file.size) {
                        if (control.pause || !control.online) return "paused"
                        val n = body.stream.read(buf)
                        if (n < 0) break
                        out.write(buf, 0, n)
                        written += n
                        window += n
                        val now = System.nanoTime()
                        if (now - tick > 250_000_000L) {
                            val speed = window * 1_000_000_000L / (now - tick).coerceAtLeast(1)
                            snaps[index] = FileSnap(file.dest, written, file.size, "running")
                            publish(host, speed, "", "running")
                            window = 0
                            tick = now
                        }
                    }
                    snaps[index] = FileSnap(file.dest, written, file.size, "running")
                }
            }
        }
        if (part.length() != file.size) return "error: 长度 ${part.length()} 不是 ${file.size}"
        val got = sha256File(part)
        if (got != file.sha256) {
            part.delete()
            snaps[index] = FileSnap(file.dest, 0, file.size, "error")
            return "error: 校验不符"
        }
        if (dest.exists()) dest.delete()
        if (!part.renameTo(dest)) {
            part.copyTo(dest, overwrite = true)
            part.delete()
        }
        snaps[index] = FileSnap(file.dest, file.size, file.size, "done")
        publish(host, 0, "", "running")
        return "done"
    }
}
