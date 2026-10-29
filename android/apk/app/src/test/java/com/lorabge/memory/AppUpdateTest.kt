package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.net.SocketException
import java.security.KeyStore
import java.security.MessageDigest

class AppUpdateTest {
    @Test
    fun versionCodeFollowsTheReleaseTag() {
        assertEquals(1003, versionCodeOf("0.1.3"))
        assertEquals(1002, versionCodeOf("0.1.2"))
        assertEquals(1_002_003, versionCodeOf("1.2.3"))
        assertTrue(versionCodeOf("0.1.3") > versionCodeOf("0.1.2"))
        // 已发布的 0.1.2 用的是手写 versionCode 4。新规则必须高于它。
        assertTrue(versionCodeOf("0.1.3") > 4)
        assertEquals(1004, versionCodeOf("0.1.4"))
        assertTrue(versionCodeOf("0.1.4") > versionCodeOf("0.1.3"))
        assertEquals(1005, versionCodeOf("0.1.5"))
        assertTrue(versionCodeOf("0.1.5") > versionCodeOf("0.1.4"))
        assertEquals(1006, versionCodeOf("0.1.6"))
        assertTrue(versionCodeOf("0.1.6") > versionCodeOf("0.1.5"))
        assertEquals(1007, versionCodeOf("0.1.7"))
        assertTrue(versionCodeOf("0.1.7") > versionCodeOf("0.1.6"))
        assertEquals(1008, versionCodeOf("0.1.8"))
        assertTrue(versionCodeOf("0.1.8") > versionCodeOf("0.1.7"))
        assertEquals(1009, versionCodeOf("0.1.9"))
        assertTrue(versionCodeOf("0.1.9") > versionCodeOf("0.1.8"))
        assertEquals(1010, versionCodeOf("0.1.10"))
        assertTrue(versionCodeOf("0.1.10") > versionCodeOf("0.1.9"))
        assertEquals(1011, versionCodeOf("0.1.11"))
        assertTrue(versionCodeOf("0.1.11") > versionCodeOf("0.1.10"))
        assertEquals(1012, versionCodeOf("0.1.12"))
        assertTrue(versionCodeOf("0.1.12") > versionCodeOf("0.1.11"))
        assertEquals(1013, versionCodeOf("0.1.13"))
        assertTrue(versionCodeOf("0.1.13") > versionCodeOf("0.1.12"))
        assertEquals(1014, versionCodeOf("0.1.14"))
        assertTrue(versionCodeOf("0.1.14") > versionCodeOf("0.1.13"))
        assertEquals(1015, versionCodeOf("0.1.15"))
        assertTrue(versionCodeOf("0.1.15") > versionCodeOf("0.1.14"))
        assertEquals(1016, versionCodeOf("0.1.16"))
        assertTrue(versionCodeOf("0.1.16") > versionCodeOf("0.1.15"))
        assertEquals(1017, versionCodeOf("0.1.17"))
        assertTrue(versionCodeOf("0.1.17") > versionCodeOf("0.1.16"))
        assertEquals(1018, versionCodeOf("0.1.18"))
        assertTrue(versionCodeOf("0.1.18") > versionCodeOf("0.1.17"))
        assertEquals(1019, versionCodeOf("0.1.19"))
        assertTrue(versionCodeOf("0.1.19") > versionCodeOf("0.1.18"))
        assertEquals(1020, versionCodeOf("0.1.20"))
        assertTrue(versionCodeOf("0.1.20") > versionCodeOf("0.1.19"))
        assertEquals(1021, versionCodeOf("0.1.21"))
        assertTrue(versionCodeOf("0.1.21") > versionCodeOf("0.1.20"))
        assertEquals("0.1.3", versionNameOfTag("android-v0.1.3"))
        assertEquals("0.1.4", versionNameOfTag("android-v0.1.4"))
        assertEquals("0.1.5", versionNameOfTag("android-v0.1.5"))
        assertEquals("0.1.6", versionNameOfTag("android-v0.1.6"))
        assertEquals("0.1.7", versionNameOfTag("android-v0.1.7"))
        assertEquals("0.1.8", versionNameOfTag("android-v0.1.8"))
        assertEquals("0.1.9", versionNameOfTag("android-v0.1.9"))
        assertEquals("0.1.10", versionNameOfTag("android-v0.1.10"))
        assertEquals("0.1.11", versionNameOfTag("android-v0.1.11"))
        assertEquals("0.1.12", versionNameOfTag("android-v0.1.12"))
        assertEquals("0.1.13", versionNameOfTag("android-v0.1.13"))
        assertEquals("0.1.14", versionNameOfTag("android-v0.1.14"))
        assertEquals("0.1.15", versionNameOfTag("android-v0.1.15"))
        assertEquals("0.1.16", versionNameOfTag("android-v0.1.16"))
        assertEquals("0.1.17", versionNameOfTag("android-v0.1.17"))
        assertEquals("0.1.18", versionNameOfTag("android-v0.1.18"))
        assertEquals("0.1.19", versionNameOfTag("android-v0.1.19"))
        assertEquals("0.1.20", versionNameOfTag("android-v0.1.20"))
        assertEquals("0.1.21", versionNameOfTag("android-v0.1.21"))
        assertNull(versionNameOfTag("v0.1.3"))
        assertNull(versionNameOfTag("android-v0.1"))
        val gradle = File("build.gradle.kts").readText()
        assertTrue(gradle.contains(""""0.1.21""""))
        assertTrue(gradle.contains("releaseVersionCode(appVersion)"))
    }

    @Test
    fun releaseListPrefersTheApkAndSkipsOtherTags() {
        val offers = parseGithubReleases(
            """
            [
              {"tag_name":"desktop-v1","body":"no","assets":[{"name":"app-debug.apk"}]},
              {"tag_name":"android-v0.1.2","body":"old notes","assets":[{"name":"notes.txt"},{"name":"app-debug.apk"}]},
              {"tag_name":"android-v0.1.3","body":"phone notes","assets":[{"name":"manifest.json"},{"name":"app-debug.apk"}]}
            ]
            """.trimIndent(),
        )
        assertEquals(listOf("0.1.2", "0.1.3"), offers.map { it.versionName })
        assertEquals("app-debug.apk", offers[1].apkName)
        assertEquals("", offers[1].sha256)
        assertEquals("phone notes", offers[1].notes)
        assertEquals(offers[1], newerRelease(1002, offers))
        assertNull(newerRelease(1003, offers))
    }

    @Test
    fun updateJsonMustMatchTheTag() {
        val offer = UpdateOffer("android-v0.1.3", "0.1.3", 1003, "notes", "", 0, "app-debug.apk")
        val sha = "ab".repeat(32)
        val parsed = parseUpdateJson(
            """{"versionName":"0.1.3","versionCode":1003,"sha256":"$sha","size":42,"apk":"app-debug.apk"}""",
            offer,
        )
        assertEquals(sha, parsed.sha256)
        assertEquals(42L, parsed.size)
        assertThrowsMessage("versionCode") {
            parseUpdateJson(
                """{"versionName":"0.1.3","versionCode":5,"sha256":"$sha","size":42}""",
                offer,
            )
        }
    }

    @Test
    fun mirrorsTryGitHubThenWorkingProxies() {
        val urls = releaseListUrls()
        assertEquals("https://api.github.com/repos/kingshuoxu/LoRA-bge-long-memory/releases?per_page=30", urls[0])
        assertTrue(urls.any { it.startsWith("https://gh-proxy.com/https://api.github.com/") })
        assertTrue(urls.any { it.startsWith("https://gh-proxy.org/https://api.github.com/") })
        assertTrue(urls.any { it.startsWith("https://ghfast.top/https://api.github.com/") })
        assertFalse(urls.any { it.contains("releases/latest") })
        assertFalse(urls.any { it.contains("ghproxy.net") || it.contains("mirror.ghproxy.com") })
        val apk = apkUrls(UPDATE_REPO, "android-v0.1.5", "app-debug.apk")
        assertEquals(
            "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.5/app-debug.apk",
            apk[0],
        )
        assertTrue(apk.any { it.contains("https://gh-proxy.com/https://github.com/") })
        assertFalse(apk.any { it.contains("releases/latest") })
        assertEquals(listOf("android-v0.1.5", "android-v0.1.6", "android-v0.1.7", "android-v0.1.8", "android-v0.2.0"), newerTagCandidates(1004))
    }

    @Test
    fun lookupReadsTheReleaseListThenTheManifest() {
        val sha = "cd".repeat(32)
        val seen = ArrayList<List<String>>()
        val offer = lookupUpdate(4, { urls ->
            seen.add(urls)
            if (urls[0].contains("api.github.com")) {
                """[{"tag_name":"android-v0.1.3","body":"更新说明","assets":[{"name":"app-debug.apk"}]}]"""
            } else {
                """{"versionName":"0.1.3","versionCode":1003,"sha256":"$sha","size":9,"apk":"app-debug.apk"}"""
            }
        })
        assertEquals("0.1.3", offer!!.versionName)
        assertEquals(1003, offer.versionCode)
        assertEquals(sha, offer.sha256)
        assertEquals("更新说明", offer.notes)
        assertTrue(seen[0][0].contains("api.github.com"))
        assertTrue(seen[1][0].contains("update.json"))
        assertTrue(seen[0].any { it.contains("gh-proxy.com") })
        assertFalse(seen[0].any { it.contains("releases/latest") })
    }

    @Test
    fun lookupUpdateSkipsADeadFirstUrlAndHtml() {
        val sha = "ab".repeat(32)
        val listJson = """[{"tag_name":"android-v0.1.5","body":"notes","assets":[{"name":"app-debug.apk"}]}]"""
        val updateJson = """{"versionName":"0.1.5","versionCode":1005,"sha256":"$sha","size":51,"apk":"app-debug.apk"}"""
        var apiCalls = 0
        var jsonCalls = 0
        val offer = lookupUpdate(1004, { urls ->
            bytesOfText(urls, accept = ::acceptUpdateDocument, opener = { url ->
                val direct = url.startsWith("https://api.github.com/") || url.startsWith("https://github.com/")
                val api = url.contains("per_page=30")
                if (direct) throw SocketException(if (api) "Software caused connection abort" else "connection closed")
                val body = if (api) {
                    apiCalls += 1
                    if (apiCalls == 1) "<html><body>landing</body></html>" else listJson
                } else {
                    jsonCalls += 1
                    if (jsonCalls == 1) "<!DOCTYPE html><html></html>" else updateJson
                }
                RemoteBody(200, body.length.toLong(), ByteArrayInputStream(body.toByteArray()))
            })
        })
        assertEquals("0.1.5", offer!!.versionName)
        assertEquals(1005, offer.versionCode)
        assertTrue(offer.versionCode > 1004)
        assertEquals(sha, offer.sha256)
        assertTrue(apiCalls >= 2)
        assertTrue(jsonCalls >= 2)
    }

    @Test
    fun lookupUpdateReadsUpdateJsonWhenTheReleaseListIsUnreachable() {
        val sha = "ef".repeat(32)
        val offer = lookupUpdate(1004, { urls ->
            if (urls.any { it.contains("per_page=30") }) throw IOException("Software caused connection abort")
            """{"versionName":"0.1.5","versionCode":1005,"sha256":"$sha","size":9,"apk":"app-debug.apk"}"""
        })
        assertEquals(1005, offer!!.versionCode)
        assertEquals("0.1.5", offer.versionName)
    }

    @Test
    fun unreachableUpdateExplainsInChinese() {
        val err = try {
            lookupUpdate(1004, { urls ->
                bytesOfText(urls, accept = ::acceptUpdateDocument, opener = {
                    throw SocketException("Software caused connection abort")
                })
            })
            null
        } catch (err: IOException) {
            err
        }
        val message = err!!.message.orEmpty()
        assertTrue(message.contains("连不上"))
        assertTrue(message.contains("GitHub"))
        assertTrue(message.contains("镜像"))
        assertTrue(message.contains("android-v0.1.21/app-debug.apk"))
        assertTrue(message.contains("https://github.com/kingshuoxu/LoRA-bge-long-memory/releases"))
        assertFalse(message.contains("releases/latest"))
        assertFalse(message.contains("Software caused connection abort"))
        val explained = explainUpdateFailure("connection closed")
        assertTrue(explained.contains("连不上"))
        assertEquals("校验不符", explainUpdateFailure("校验不符"))
    }

    @Test
    fun apkDownloadChecksShaAndSkipsAMatchingFile() {
        val payload = "apk-bytes".toByteArray()
        val sha = MessageDigest.getInstance("SHA-256").digest(payload).joinToString("") { "%02x".format(it) }
        val offer = UpdateOffer("android-v0.1.3", "0.1.3", 1003, "", sha, payload.size.toLong(), "app-debug.apk")
        val root = File.createTempFile("upd", "").apply {
            delete()
            mkdirs()
        }
        var opens = 0
        val opener = RemoteOpener { _, _ ->
            opens += 1
            RemoteBody(200, payload.size.toLong(), ByteArrayInputStream(payload))
        }
        val file = downloadUpdate(root, offer, opener)
        assertEquals("apk-bytes", file.readText())
        assertEquals(1, opens)
        downloadUpdate(root, offer, opener)
        assertEquals(1, opens)
    }

    @Test
    fun committedKeystoreIsTheMarkedTestKey() {
        val file = listOf(
            File("keystore/debug-test-only.jks"),
            File("../keystore/debug-test-only.jks"),
        ).first { it.isFile }
        val readme = File(file.parentFile, "README.md").readText()
        assertTrue(readme.contains("测试专用"))
        assertTrue(readme.contains("ANDROID_KEYSTORE_B64"))
        val store = KeyStore.getInstance("PKCS12")
        file.inputStream().use { store.load(it, "lorabge-test-only".toCharArray()) }
        assertTrue(store.containsAlias("lorabge-test"))
        assertFalse(store.containsAlias("androiddebugkey"))
    }

    private fun assertThrowsMessage(part: String, block: () -> Unit) {
        try {
            block()
        } catch (err: IllegalArgumentException) {
            assertTrue(err.message.orEmpty().contains(part))
            return
        }
        throw AssertionError("expected failure containing $part")
    }
}
