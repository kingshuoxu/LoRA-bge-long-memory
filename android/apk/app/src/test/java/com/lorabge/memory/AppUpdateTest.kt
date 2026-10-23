package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
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
        assertEquals("0.1.3", versionNameOfTag("android-v0.1.3"))
        assertNull(versionNameOfTag("v0.1.3"))
        assertNull(versionNameOfTag("android-v0.1"))
        val gradle = File("build.gradle.kts").readText()
        assertTrue(gradle.contains(""""0.1.3""""))
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
    fun mirrorsTryGitHubThenChinaProxies() {
        val urls = releaseListUrls()
        assertEquals("https://api.github.com/repos/kingshuoxu/LoRA-bge-long-memory/releases?per_page=30", urls[0])
        assertTrue(urls[1].startsWith("https://ghproxy.net/https://api.github.com/"))
        assertTrue(urls[2].startsWith("https://mirror.ghproxy.com/https://api.github.com/"))
        val apk = apkUrls(UPDATE_REPO, "android-v0.1.3", "app-debug.apk")
        assertEquals(
            "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.3/app-debug.apk",
            apk[0],
        )
        assertTrue(apk[1].contains("ghproxy.net"))
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
        assertTrue(seen[0].any { it.contains("ghproxy.net") })
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
