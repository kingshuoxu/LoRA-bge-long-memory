package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

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

fun mirrorUrls(direct: String): List<String> {
    val clean = direct.trim()
    return listOf(
        clean,
        "https://ghproxy.net/$clean",
        "https://mirror.ghproxy.com/$clean",
    )
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

fun lookupUpdate(
    currentVersionCode: Int,
    fetchText: (List<String>) -> String,
    repo: String = UPDATE_REPO,
): UpdateOffer? {
    val offer = newerRelease(currentVersionCode, parseGithubReleases(fetchText(releaseListUrls(repo)))) ?: return null
    return parseUpdateJson(fetchText(updateJsonUrls(repo, offer.tag)), offer)
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
