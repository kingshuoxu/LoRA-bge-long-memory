package com.lorabge.memory

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.MotionEvent
import android.view.View
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject
import java.io.File

/**
 * 桌面同一套 WebGL 星云。模块脚本走 appassets,避免 file:// 的跨域限制。
 * 控制台、脚本错误和显卡字符串写入 logcat,并附在导出诊断里。
 */
@SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
@Composable
internal fun NebulaHost(
    json: String,
    recallJson: String,
    training: Boolean,
    lang: String,
    modifier: Modifier = Modifier,
    onOpenConversation: (String) -> Unit,
    onGl: (String) -> Unit,
) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            val web = NebulaWeb(context)
            web.setBackgroundColor(0xFF070910.toInt())
            web.settings.javaScriptEnabled = true
            web.settings.domStorageEnabled = true
            web.settings.setSupportZoom(false)
            web.settings.builtInZoomControls = false
            web.settings.displayZoomControls = false
            web.settings.mediaPlaybackRequiresUserGesture = false
            web.isVerticalScrollBarEnabled = false
            web.isHorizontalScrollBarEnabled = false
            web.overScrollMode = View.OVER_SCROLL_NEVER
            web.isFocusable = true
            web.isFocusableInTouchMode = true
            web.contentDescription = "nebula"
            web.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
            web.setOnTouchListener { view, event ->
                val pinch = event.pointerCount >= 2 ||
                    event.actionMasked == MotionEvent.ACTION_POINTER_DOWN ||
                    event.actionMasked == MotionEvent.ACTION_DOWN
                if (pinch) view.parent?.requestDisallowInterceptTouchEvent(true)
                false
            }
            val bridge = NebulaBridge(context.applicationContext, onOpenConversation, onGl)
            web.addJavascriptInterface(bridge, "Android")
            web.webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    val line = "${message.messageLevel()} ${message.sourceId()}:${message.lineNumber()} ${message.message()}"
                    Log.i("Nebula", line)
                    appendNebulaConsole(context.applicationContext, line)
                    return true
                }
            }
            web.webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    return openAsset(context, request.url)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    web.ready = true
                    if (web.lastScript.isNotEmpty()) web.evaluateJavascript(web.lastScript, null)
                }

                override fun onReceivedError(
                    view: WebView?,
                    request: WebResourceRequest?,
                    error: android.webkit.WebResourceError?,
                ) {
                    if (request?.isForMainFrame == false) return
                    val line = "page ${error?.errorCode} ${error?.description}"
                    Log.e("Nebula", line)
                    appendNebulaConsole(context.applicationContext, line)
                }
            }
            val e2e = File(context.filesDir, "setup/e2e").exists()
            web.loadUrl(
                "https://appassets.androidplatform.net/assets/nebula/index.html" + if (e2e) "?e2e=1" else "",
            )
            web
        },
        update = { web ->
            val data = if (json.isBlank()) JSONObject().put("experts", org.json.JSONArray()) else JSONObject(json)
            val payload = JSONObject()
                .put("lang", lang)
                .put("mode", if (training) "dim" else "full")
                .put("data", data)
            if (recallJson.isNotBlank()) payload.put("recall", JSONObject(recallJson))
            val script = "window.nebulaHost&&nebulaHost.apply(${JSONObject.quote(payload.toString())})"
            web.push(script)
        },
    )
}

internal fun noteNebulaFallback(context: android.content.Context, lang: String): String? {
    val file = File(context.filesDir, "setup/nebula-fallback-noted")
    if (file.exists()) return null
    file.parentFile?.mkdirs()
    file.writeText("1")
    return skyText(lang, "nebulaFallback")
}

private fun appendNebulaConsole(context: android.content.Context, line: String) {
    val file = File(context.filesDir, "setup/nebula-console.txt")
    file.parentFile?.mkdirs()
    val prior = if (file.exists()) file.readText() else ""
    val next = (prior + line.take(400) + "\n").takeLast(4000)
    file.writeText(next)
}

private fun writeNebulaStatus(context: android.content.Context, json: String) {
    val setup = File(context.filesDir, "setup")
    setup.mkdirs()
    File(setup, "nebula-status.json").writeText(json)
    val obj = try {
        JSONObject(json)
    } catch (_: Throwable) {
        null
    }
    val body = if (obj == null) {
        json.take(500)
    } else {
        "renderer=${obj.optString("renderer")}\n" +
            "version=${obj.optString("version")}\n" +
            "path=${obj.optString("path").ifBlank { obj.optString("fallback") }}\n" +
            "fallback=${obj.optString("fallback")}\n" +
            "frames=${obj.optInt("frames")}\n" +
            "touches=${obj.optInt("touches")}\n" +
            "zoom=${obj.optDouble("zoom")}\n" +
            "cameraZ=${obj.optDouble("cameraZ")}\n" +
            "skyRenderer=${obj.optString("skyRenderer")}\n" +
            "skyVersion=${obj.optString("skyVersion")}\n" +
            "flip=${obj.optDouble("flip")}\n" +
            "rough=${obj.optDouble("rough")}\n" +
            "lattice=${obj.optBoolean("lattice")}\n" +
            "probed=${obj.optBoolean("probed")}\n"
    }
    File(setup, "nebula-gl.txt").writeText(body)
}

private class NebulaWeb(context: android.content.Context) : WebView(context) {
    var ready = false
    var lastScript = ""

    fun push(script: String) {
        if (script == lastScript && ready) return
        lastScript = script
        if (ready) evaluateJavascript(script, null)
    }
}

private class NebulaBridge(
    private val appContext: android.content.Context,
    private val onOpen: (String) -> Unit,
    private val onGl: (String) -> Unit,
) {
    private val main = Handler(Looper.getMainLooper())
    private var lastStatus = ""

    @JavascriptInterface
    fun onOpenConversation(id: String) {
        main.post { onOpen(id) }
    }

    @JavascriptInterface
    fun onLog(line: String) {
        Log.i("Nebula", line)
        appendNebulaConsole(appContext, line)
    }

    @JavascriptInterface
    fun onFrame(name: String, dataUrl: String, variance: String) {
        if (name != "canvas-before" && name != "canvas-after" && name != "canvas-sky") return
        if (!File(appContext.filesDir, "setup/e2e").exists()) return
        val comma = dataUrl.indexOf(',')
        if (comma < 0 || comma > 80) return
        val bytes = try {
            android.util.Base64.decode(dataUrl.substring(comma + 1), android.util.Base64.DEFAULT)
        } catch (_: Throwable) {
            return
        }
        if (bytes.size < 32 || bytes.size > 2_000_000) return
        val dir = File(appContext.filesDir, "e2e")
        dir.mkdirs()
        File(dir, "$name.png").writeBytes(bytes)
        File(dir, "$name.txt").writeText("variance=$variance\n")
    }

    @JavascriptInterface
    fun onStatus(json: String) {
        if (json == lastStatus) return
        lastStatus = json
        writeNebulaStatus(appContext, json)
        Log.i("Nebula", "gl ${json.take(240)}")
    }

    @JavascriptInterface
    fun onNotice(kind: String) {
        main.post { onGl(kind) }
    }

    @JavascriptInterface
    fun onFallback(kind: String) {
        main.post { onGl(if (kind == "canvas") "canvas" else kind) }
    }
}

private fun openAsset(context: android.content.Context, url: android.net.Uri): WebResourceResponse? {
    if (url.host != "appassets.androidplatform.net") return null
    val raw = url.path ?: return null
    val path = raw.removePrefix("/assets/").trimStart('/')
    if (path.isEmpty() || path.contains("..")) return null
    val stream = try {
        context.assets.open(path)
    } catch (_: Throwable) {
        return null
    }
    val mime = when {
        path.endsWith(".js") -> "text/javascript"
        path.endsWith(".css") -> "text/css"
        path.endsWith(".html") -> "text/html"
        path.endsWith(".woff2") -> "font/woff2"
        path.endsWith(".json") -> "application/json"
        else -> "application/octet-stream"
    }
    val encoding = if (path.endsWith(".woff2")) null else "utf-8"
    return WebResourceResponse(mime, encoding, stream)
}
