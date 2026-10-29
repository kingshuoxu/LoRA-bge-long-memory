package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException

const val UPDATE_REPO = "kingshuoxu/LoRA-bge-long-memory"

fun versionCodeOf(versionName: String): Int {
    val parts = versionName.trim().removePrefix("v").split(".")
    require(parts.size >= 3) { "版本号需要三段: $versionName" }
    val major = parts[0].toInt()
    val minor = parts[1].toInt()
    val patch = parts[2].substringBefore("-").substringBefore("+").toInt()
    require(major in 0..99 && minor in 0..999 && patch in 0..999) { versionName }
    return major * 1_000_000 + minor * 1_000 + patch
}

fun versionNameOfTag(tag: String): String? {
    val match = Regex("^android-v(\\d+\\.\\d+\\.\\d+)$").matchEntire(tag.trim()) ?: return null
    return match.groupValues[1]
}

data class UpdateOffer(
    val tag: String,
    val versionName: String,
    val versionCode: Int,
    val notes: String,
    val sha256: String,
    val size: Long,
    val apkName: String,
)

// 这些前缀在 2026-10-26 的实测里返回了 JSON 或 APK 字节，不是 HTML 落地页。
// ghproxy.net 读超时，mirror.ghproxy.com 已经没有 DNS，不再排进链里。
val UPDATE_MIRROR_PREFIXES: List<String> = listOf(
    "https://gh-proxy.com/",
    "https://gh-proxy.org/",
    "https://ghfast.top/",
    "https://gh.llkk.cc/",
    "https://gh.nxnow.top/",
)

const val BROWSER_APK_URL =
    "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.21/app-debug.apk"

const val BROWSER_RELEASES_URL =
    "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases"

fun mirrorUrls(direct: String): List<String> {
    val clean = direct.trim()
    return listOf(clean) + UPDATE_MIRROR_PREFIXES.map { prefix -> prefix + clean }
}

fun acceptUpdateDocument(text: String): Boolean {
    val trimmed = text.trimStart()
    if (trimmed.isEmpty() || trimmed.startsWith("<")) return false
    if (trimmed.contains("<html", ignoreCase = true) || trimmed.contains("<!DOCTYPE", ignoreCase = true)) return false
    return try {
        when {
            trimmed.startsWith("[") -> {
                JSONArray(text)
                true
            }
            trimmed.startsWith("{") -> {
                JSONObject(text)
                true
            }
            else -> false
        }
    } catch (_: JSONException) {
        false
    }
}

fun updateUnreachableMessage(): String =
    "连不上 GitHub 和镜像。可以用手机浏览器打开安装包覆盖安装：$BROWSER_APK_URL 。更新的包在发布页：$BROWSER_RELEASES_URL"

fun explainUpdateFailure(raw: String?): String {
    val text = raw?.trim().orEmpty()
    if (text.contains("连不上")) return text
    if (text.contains("校验不符") || text.contains("空间不够") || text.contains("versionCode")) return text
    return updateUnreachableMessage()
}

fun newerTagCandidates(currentVersionCode: Int): List<String> {
    val major = currentVersionCode / 1_000_000
    val minor = (currentVersionCode % 1_000_000) / 1_000
    val patch = currentVersionCode % 1_000
    val tags = ArrayList<String>()
    for (next in (patch + 1)..(patch + 4)) {
        if (next <= 999) tags.add("android-v$major.$minor.$next")
    }
    if (minor < 999) tags.add("android-v$major.${minor + 1}.0")
    return tags
}

fun releaseListUrls(repo: String = UPDATE_REPO): List<String> =
    mirrorUrls("https://api.github.com/repos/$repo/releases?per_page=30")

fun updateJsonUrls(repo: String, tag: String): List<String> =
    mirrorUrls("https://github.com/$repo/releases/download/$tag/update.json")

fun apkUrls(repo: String, tag: String, apkName: String): List<String> =
    mirrorUrls("https://github.com/$repo/releases/download/$tag/$apkName")

fun parseGithubReleases(json: String): List<UpdateOffer> {
    val array = JSONArray(json)
    val out = ArrayList<UpdateOffer>()
    for (i in 0 until array.length()) {
        val row = array.getJSONObject(i)
        val tag = row.optString("tag_name")
        val versionName = versionNameOfTag(tag) ?: continue
        val assets = row.optJSONArray("assets") ?: continue
        var apkName = ""
        for (j in 0 until assets.length()) {
            val name = assets.getJSONObject(j).optString("name")
            if (name == "app-debug.apk") {
                apkName = name
                break
            }
            if (apkName.isEmpty() && name.endsWith(".apk")) apkName = name
        }
        if (apkName.isEmpty()) continue
        out.add(
            UpdateOffer(
                tag = tag,
                versionName = versionName,
                versionCode = versionCodeOf(versionName),
                notes = row.optString("body"),
                sha256 = "",
                size = 0,
                apkName = apkName,
            ),
        )
    }
    return out
}

fun parseUpdateJson(text: String, offer: UpdateOffer): UpdateOffer {
    val obj = JSONObject(text)
    val code = obj.getInt("versionCode")
    val name = obj.getString("versionName")
    require(code == offer.versionCode) { "update.json 的 versionCode 和标签不一致" }
    require(name == offer.versionName) { "update.json 的 versionName 和标签不一致" }
    val sha = obj.getString("sha256").lowercase()
    require(Regex("^[0-9a-f]{64}$").matches(sha)) { "sha256" }
    val size = obj.getLong("size")
    require(size > 0) { "size" }
    val apk = obj.optString("apk", offer.apkName).ifBlank { offer.apkName }
    return offer.copy(sha256 = sha, size = size, apkName = apk)
}

fun newerRelease(currentVersionCode: Int, releases: List<UpdateOffer>): UpdateOffer? =
    releases.filter { it.versionCode > currentVersionCode }.maxByOrNull { it.versionCode }

fun bytesOfUpdateText(urls: List<String>): String = bytesOfText(urls, accept = ::acceptUpdateDocument)

fun lookupUpdate(
    currentVersionCode: Int,
    fetchText: (List<String>) -> String,
    repo: String = UPDATE_REPO,
): UpdateOffer? {
    return try {
        val text = fetchText(releaseListUrls(repo))
        val offer = newerRelease(currentVersionCode, parseGithubReleases(text)) ?: return null
        parseUpdateJson(fetchText(updateJsonUrls(repo, offer.tag)), offer)
    } catch (err: IOException) {
        finishAfterListFailure(currentVersionCode, fetchText, repo)
    } catch (err: JSONException) {
        finishAfterListFailure(currentVersionCode, fetchText, repo)
    }
}

private fun finishAfterListFailure(
    currentVersionCode: Int,
    fetchText: (List<String>) -> String,
    repo: String,
): UpdateOffer? {
    var best: UpdateOffer? = null
    var sawMissing = false
    var sawOther = false
    for (tag in newerTagCandidates(currentVersionCode)) {
        val name = versionNameOfTag(tag) ?: continue
        val code = versionCodeOf(name)
        val stub = UpdateOffer(tag, name, code, "", "", 0, "app-debug.apk")
        try {
            val parsed = parseUpdateJson(fetchText(updateJsonUrls(repo, tag)), stub)
            val currentBest = best
            if (currentBest == null || parsed.versionCode > currentBest.versionCode) best = parsed
        } catch (err: IOException) {
            if (err.message?.contains("HTTP 404") == true) sawMissing = true else sawOther = true
        } catch (_: Exception) {
            sawOther = true
        }
    }
    if (best != null) return best
    if (sawMissing && !sawOther) return null
    throw IOException(updateUnreachableMessage())
}

fun downloadUpdate(
    root: File,
    offer: UpdateOffer,
    opener: RemoteOpener,
    repo: String = UPDATE_REPO,
    onUpdate: (FetchSnapshot) -> Unit = {},
): File {
    require(offer.sha256.length == 64) { "还没有校验值" }
    val manifest = FetchManifest(
        true,
        listOf(
            FetchFile(
                id = "apk",
                dest = "updates/${offer.apkName}",
                sha256 = offer.sha256,
                size = offer.size,
                urls = apkUrls(repo, offer.tag, offer.apkName),
            ),
        ),
    )
    val result = ModelFetch(root, opener).download(manifest, onUpdate)
    if (result != "done") throw java.io.IOException(result.removePrefix("error: "))
    return File(root, "updates/${offer.apkName}")
}
