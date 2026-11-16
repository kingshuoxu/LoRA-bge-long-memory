package com.lorabge.memory

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Exercise the production lookup, verified download and PackageInstaller with the
 * exact release artifact. Only the remote transport is a local fixture. The host
 * verifies installation because replacing this APK terminates instrumentation.
 * This is not a test of a previously published app's UI or GitHub availability.
 */
class CandidateUpdateTest {
    @Test
    fun installCandidate() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = File(context.filesDir, "update-fixture")
        val manifest = File(fixture, "update.json").readText()
        val meta = JSONObject(manifest)
        val current = context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode.toInt()
        val name = meta.getString("versionName")
        val tag = "android-v$name"
        val release = JSONArray().put(JSONObject().apply {
            put("tag_name", tag)
            put("assets", JSONArray().put(JSONObject().put("name", "app-debug.apk")))
        }).toString()
        val offer = requireNotNull(lookupUpdate(current, { urls ->
            when (urls.first()) {
                releaseListUrls().first() -> release
                updateJsonUrls(UPDATE_REPO, tag).first() -> manifest
                else -> error("Unexpected metadata request: ${urls.first()}")
            }
        }))
        assertTrue(offer.versionCode > current)
        val source = File(fixture, "app-debug.apk")
        assertEquals(offer.size, source.length())
        assertEquals(offer.sha256, sha256File(source))
        File(context.filesDir, "updates").deleteRecursively()
        val downloaded = downloadUpdate(context.filesDir, offer, RemoteOpener { url, offset ->
            require(url == apkUrls(UPDATE_REPO, tag, "app-debug.apk").first())
            require(offset == 0L) // A fresh download; fail rather than hide a stale fixture.
            RemoteBody(200, source.length(), source.inputStream())
        })
        assertEquals(offer.sha256, sha256File(downloaded))
        assertTrue(!UpdateInstaller.needsUnknownSources(context))
        File(fixture, "submitted").writeText(offer.sha256)
        UpdateInstaller.install(context, downloaded)
        // The host, not JUnit's exit status, decides success after package replacement.
        Thread.sleep(120_000)
        error("Candidate did not replace the running application")
    }
}
