package com.lorabge.memory

import android.annotation.SuppressLint
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject

/**
 * 桌面同一套 WebGL 星云。模块脚本走 appassets,避免 file:// 的跨域限制。
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
internal fun NebulaHost(
    json: String,
    recallJson: String,
    training: Boolean,
    lang: String,
    modifier: Modifier = Modifier,
    onOpenConversation: (String) -> Unit,
) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            val web = NebulaWeb(context)
            web.setBackgroundColor(0x00000000)
            web.settings.javaScriptEnabled = true
            web.settings.domStorageEnabled = true
            web.settings.mediaPlaybackRequiresUserGesture = false
            web.isVerticalScrollBarEnabled = false
            web.isHorizontalScrollBarEnabled = false
            web.overScrollMode = View.OVER_SCROLL_NEVER
            web.addJavascriptInterface(NebulaBridge(onOpenConversation), "Android")
            web.webViewClient = object : WebViewClient() {
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    return openAsset(context, request.url)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    web.ready = true
                    if (web.lastScript.isNotEmpty()) web.evaluateJavascript(web.lastScript, null)
                }
            }
            web.loadUrl("https://appassets.androidplatform.net/assets/nebula/index.html")
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

private class NebulaWeb(context: android.content.Context) : WebView(context) {
    var ready = false
    var lastScript = ""

    fun push(script: String) {
        if (script == lastScript && ready) return
        lastScript = script
        if (ready) evaluateJavascript(script, null)
    }
}

private class NebulaBridge(private val onOpen: (String) -> Unit) {
    private val main = Handler(Looper.getMainLooper())

    @JavascriptInterface
    fun onOpenConversation(id: String) {
        main.post { onOpen(id) }
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
