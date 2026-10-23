package com.lorabge.memory

import android.Manifest
import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.view.WindowCompat
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : ComponentActivity() {
    private val notifyPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightNavigationBars = false
        val store = MemoryStore(File(filesDir, "memory"))
        store.ensure()
        val engine = Engine(this, store)
        val client = LlmClient(this)
        engine.disarmUnprovenMali()
        if (intent?.getStringExtra("mode") == "benchmark" || intent?.action == TrainService.ACTION_BENCHMARK) {
            startBenchmark(store)
        }
        val benchmark = intent?.getStringExtra("mode") == "benchmark" || intent?.action == TrainService.ACTION_BENCHMARK
        setContent {
            var ready by remember { mutableStateOf(benchmark || !FetchService.needsSetup(this)) }
            if (!ready) {
                SetupScreen(onFinished = { ready = true })
                return@setContent
            }
            PhoneApp(store, engine, client, probeOnStart = !benchmark, onCleared = { ready = false }, onTrain = {
                if (Build.VERSION.SDK_INT >= 33 &&
                    ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED
                ) {
                    notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
                startForegroundService(Intent(this, TrainService::class.java))
            }, onCancel = {
                startService(Intent(this, TrainService::class.java).setAction(TrainService.ACTION_CANCEL))
            }, onExport = {
                shareDiagnostics(engine.diagnostics())
            })
        }
    }

    private fun shareDiagnostics(text: String) {
        val file = File(cacheDir, "lorabge-diagnostics.txt")
        file.writeText(text)
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).setType("text/plain")
        send.putExtra(Intent.EXTRA_STREAM, uri)
        send.putExtra(Intent.EXTRA_TEXT, text)
        send.clipData = ClipData.newRawUri("diagnostics", uri)
        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val chooser = Intent.createChooser(send, "导出诊断")
        chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        startActivity(chooser)
    }

    private fun startBenchmark(store: MemoryStore) {
        val obj = JSONObject(assets.open("consolidation_bench.json").bufferedReader().use { it.readText() })
        val factsJson = obj.getJSONArray("facts")
        val facts = ArrayList<ReviewedFact>()
        for (i in 0 until factsJson.length()) facts.add(TrainService.factFromJson(factsJson.getJSONObject(i)))
        TrainService.writeJob(
            store,
            "expert_bench",
            facts,
            force = true,
            epochs = 4,
            benchmark = true,
            heldOut = obj.optJSONArray("held_out"),
            neverWritten = obj.optJSONArray("never_written"),
        )
        startForegroundService(Intent(this, TrainService::class.java))
    }
}

@Composable
private fun PhoneApp(
    store: MemoryStore,
    engine: Engine,
    client: LlmClient,
    probeOnStart: Boolean,
    onTrain: () -> Unit,
    onCancel: () -> Unit,
    onExport: () -> Unit,
    onCleared: () -> Unit,
) {
    var lang by remember { mutableStateOf("zh") }
    var tab by remember { mutableStateOf(SkyTab.Chat) }
    var tick by remember { mutableIntStateOf(0) }
    var note by remember { mutableStateOf("") }
    var toast by remember { mutableStateOf("") }
    var probeGen by remember { mutableIntStateOf(if (probeOnStart) 1 else 0) }
    LaunchedEffect(probeGen) {
        if (probeGen == 0) return@LaunchedEffect
        val running = AtomicBoolean(true)
        val langNow = lang
        Thread {
            try {
                client.ensure()
            } catch (_: Throwable) {
            } finally {
                val fallback = client.notice(langNow)
                if (fallback.isNotBlank()) toast = fallback
                running.set(false)
            }
        }.start()
        while (running.get()) {
            delay(700)
            tick++
        }
        tick++
    }
    val context = androidx.compose.ui.platform.LocalContext.current
    var settingsOpen by remember { mutableStateOf(false) }
    var drawerOpen by remember { mutableStateOf(false) }
    var wifiOnly by remember { mutableStateOf(FetchService.wifiOnly(context)) }
    var manifestUrl by remember { mutableStateOf(FetchService.manifestUrl(context)) }
    var recallJson by remember { mutableStateOf("") }
    var recallBanner by remember { mutableStateOf("") }
    var draft by remember { mutableStateOf("") }
    var generating by remember { mutableStateOf(false) }
    var streaming by remember { mutableStateOf("") }
    var currentId by remember { mutableStateOf(store.listConversations().firstOrNull()?.id) }
    var pending by remember { mutableStateOf<PendingCorrection?>(null) }
    var entity by remember { mutableStateOf("") }
    var statement by remember { mutableStateOf("") }
    var value by remember { mutableStateOf("") }
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var force by remember { mutableStateOf(false) }
    val statusFile = File(store.trainDir, "status.json")
    val training = statusFile.exists() && statusState(statusFile.readText()) == "running"
    LaunchedEffect(training, tick) {
        if (!training) return@LaunchedEffect
        delay(1000)
        tick++
    }
    val conversations = remember(tick) { store.listConversations() }
    val current = currentId?.let { store.loadConversation(it) }
    val experts = remember(tick, lang) { skyExperts(store, lang) }
    val highlight = current?.messages?.lastOrNull { it.role == "assistant" }?.expert
    val loss = remember(tick) { readLoss(File(store.trainDir, "train.log")) }
    val record = engine.backendRecord()
    val storageLabel = remember(tick) { formatBytes(modelBytes(context)) }
    val versionName = remember {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0.1.3"
    }
    val freshExpert = if (training) experts.firstOrNull()?.name else null
    val nebulaJson = remember(tick, lang, freshExpert) { NebulaGraph.build(store, lang, freshExpert) }
    val state = SkyState(
        lang = lang,
        tab = tab,
        training = training,
        status = presentTrainStatus(lang, statusFile.takeIf { it.exists() }?.readText().orEmpty()),
        messages = current?.messages?.map { SkyMessage(it.role, it.content, it.expert, it.reason, it.noticed) } ?: emptyList(),
        streaming = streaming,
        generating = generating,
        draft = draft,
        conversations = conversations.map { SkyConversation(it.id, it.title) },
        currentTitle = current?.title.orEmpty(),
        loss = loss,
        experts = experts,
        highlightExpert = highlight,
        pending = pending,
        entity = entity,
        statement = statement,
        value = value,
        question = question,
        answer = answer,
        force = force,
        note = note,
        toast = toast,
        settingsOpen = settingsOpen,
        drawerOpen = drawerOpen,
        backendMode = record.mode,
        backendLine = backendLine(lang, record, engine.baseModel() != null, engine.bgeModel() != null),
        wifiOnly = wifiOnly,
        manifestUrl = manifestUrl,
        storageLabel = storageLabel,
        versionName = versionName,
        nebulaJson = nebulaJson,
        recallJson = recallJson,
        recallBanner = recallBanner,
        liveNebula = true,
    )
    SkyFrame(state) { event ->
        when (event) {
            is SkyEvent.Lang -> lang = event.lang
            is SkyEvent.Tab -> tab = event.tab
            is SkyEvent.Draft -> draft = event.text
            SkyEvent.NewChat -> {
                currentId = store.newConversation().id
                recallJson = ""
                recallBanner = ""
                drawerOpen = false
                tick++
            }
            SkyEvent.OpenSettings -> settingsOpen = true
            SkyEvent.CloseSettings -> settingsOpen = false
            SkyEvent.OpenDrawer -> drawerOpen = true
            SkyEvent.CloseDrawer -> drawerOpen = false
            is SkyEvent.OpenConversation -> {
                currentId = event.id
                tab = SkyTab.Chat
                drawerOpen = false
                settingsOpen = false
                tick++
            }
            is SkyEvent.WifiOnly -> {
                wifiOnly = event.on
                FetchService.setWifiOnly(context, event.on)
            }
            is SkyEvent.ManifestUrl -> manifestUrl = event.url
            SkyEvent.ApplyManifest -> FetchService.setManifestUrl(context, manifestUrl)
            SkyEvent.ClearModels -> {
                clearDownloadedModels(context)
                onCleared()
            }
            SkyEvent.Send -> {
                val text = draft.trim()
                if (text.isEmpty() || generating) return@SkyFrame
                val conversation = current ?: store.newConversation().also { currentId = it.id }
                val noticed = FactNotice.noticed(text)
                if (noticed) {
                    val guess = FactNotice.guess(text)
                    entity = guess.entity
                    statement = guess.statement
                    value = guess.value
                    pending = null
                }
                val now = Instant.now().toString()
                val title = if (conversation.messages.isEmpty()) text.take(18) else conversation.title
                val withUser = conversation.messages + ChatMessage("user", text)
                store.saveConversation(conversation.copy(title = title, updated = now, messages = withUser))
                draft = ""
                generating = true
                streaming = ""
                tick++
                val langNow = lang
                Thread {
                    val hit = try {
                        client.route(text)
                    } catch (ex: Throwable) {
                        RouteHit(null, false, ex.message ?: "route", 0.0)
                    }
                    val trace = NebulaGraph.recall(store, langNow, hit.expert, hit.fired, hit.sim, text)
                    recallJson = trace
                    recallBanner = org.json.JSONObject(trace).optString("banner")
                    val expert = if (hit.fired) hit.expert else null
                    val reply = try {
                        client.answer(text, expert) { streaming = it }
                    } catch (ex: Throwable) {
                        if (langNow == "en") "Couldn't generate" else "生成失败"
                    }
                    val saved = store.loadConversation(conversation.id) ?: withUser.let {
                        conversation.copy(title = title, updated = now, messages = withUser)
                    }
                    val messages = saved.messages + ChatMessage("assistant", reply, expert, hit.reason, noticed)
                    store.saveConversation(saved.copy(updated = Instant.now().toString(), messages = messages))
                    generating = false
                    streaming = ""
                    val fallback = client.notice(langNow)
                    if (fallback.isNotBlank()) toast = fallback
                    tick++
                }.start()
            }
            SkyEvent.DismissCorrection -> pending = null
            SkyEvent.ConfirmCorrection -> {
                val item = pending ?: return@SkyFrame
                val fact = ReviewedFact(
                    entity = item.entity.ifBlank { "事实" },
                    statement = item.statement,
                    value = item.value.ifBlank { item.statement },
                    qa = listOf(item.statement to item.value),
                    sources = listOfNotNull(currentId),
                    selected = true,
                )
                TrainService.writeJob(store, "expert_" + System.currentTimeMillis().toString().takeLast(6), listOf(fact), force = true)
                onTrain()
                pending = null
                tab = SkyTab.Consolidate
                tick++
            }
            is SkyEvent.Field -> when (event.key) {
                "entity" -> entity = event.text
                "statement" -> statement = event.text
                "value" -> value = event.text
                "question" -> question = event.text
                "answer" -> answer = event.text
            }
            is SkyEvent.Force -> force = event.on
            SkyEvent.Train -> {
                if (entity.isBlank() || statement.isBlank() || value.isBlank()) return@SkyFrame
                val qa = if (question.isBlank()) emptyList() else listOf(question to answer.ifBlank { value })
                val fact = ReviewedFact(entity.trim(), statement.trim(), value.trim(), qa, emptyList(), selected = true)
                TrainService.writeJob(store, "expert_" + System.currentTimeMillis().toString().takeLast(6), listOf(fact), force)
                onTrain()
                tick++
            }
            SkyEvent.CancelTrain -> onCancel()
            is SkyEvent.DeleteExpert -> {
                store.deleteExpert(event.name)
                Thread {
                    try {
                        client.rebuild()
                    } catch (_: Throwable) {
                    }
                    tick++
                }.start()
            }
            SkyEvent.ImportExperts -> {
                val langNow = lang
                Thread {
                    note = try {
                        client.importExternal()
                        if (langNow == "en") "Experts imported" else "已导入专家"
                    } catch (ex: Throwable) {
                        ex.message ?: "import"
                    }
                    tick++
                }.start()
            }
            SkyEvent.SelfCheck -> {
                Thread {
                    note = try {
                        client.selfCheck()
                    } catch (ex: Throwable) {
                        ex.message ?: "check"
                    }
                    tick++
                }.start()
            }
            is SkyEvent.BackendMode -> {
                engine.setBackendMode(event.mode)
                toast = engine.backendLabel(lang) + " · " + DeviceTune.explain(engine.backendRecord())
                if (event.mode == "auto") probeGen++
                tick++
            }
            SkyEvent.DismissToast -> toast = ""
            SkyEvent.ExportDiagnostics -> onExport()
        }
    }
}

internal fun looksLikeCorrection(text: String): Boolean {
    val lower = text.lowercase()
    return listOf("不对", "记错", "应该是", "更正", "改成", "actually", "correction").any { it in lower }
}

internal fun guessCorrection(text: String): PendingCorrection {
    var body = text.trim()
    for (prefix in listOf("不对，", "不对,", "不对。", "记错了，", "记错了,", "更正：", "更正:", "应该是，", "应该是 ")) {
        if (body.startsWith(prefix)) body = body.removePrefix(prefix).trim()
    }
    val match = Regex("(.+?)的(.+?)是(.+)").find(body)
    val entity = match?.groupValues?.getOrNull(1)?.trim().orEmpty()
    val value = match?.groupValues?.getOrNull(3)?.trim()?.trimEnd('。', '.', '！', '!')?.trim().orEmpty()
    return PendingCorrection(entity, body, value)
}

internal fun readLoss(log: File): List<Float> {
    if (!log.exists()) return emptyList()
    return log.readLines().mapNotNull { line ->
        val at = line.indexOf("loss=")
        if (at < 0) return@mapNotNull null
        line.drop(at + 5).takeWhile { it.isDigit() || it == '.' }.toFloatOrNull()
    }
}

private fun skyExperts(store: MemoryStore, lang: String): List<SkyExpert> {
    return store.listExperts().map { record ->
        val raw = NebulaGraph.readFacts(File(store.expertsDir, record.expert))
        SkyExpert(
            record.expert,
            raw.map { it.optString("statement") }.filter { it.isNotBlank() },
            NebulaGraph.displayName(raw.map { it.optString("entity") }, lang),
        )
    }
}

private fun modelBytes(context: android.content.Context): Long {
    fun walk(dir: File?): Long {
        if (dir == null || !dir.exists()) return 0
        return dir.walkTopDown().filter { it.isFile }.sumOf { it.length() }
    }
    val external = context.getExternalFilesDir(null)?.let { File(it, "models") }
    return walk(File(context.filesDir, "models")) + walk(external)
}

private fun clearDownloadedModels(context: android.content.Context) {
    File(context.filesDir, "models").deleteRecursively()
    context.getExternalFilesDir(null)?.let { File(it, "models").deleteRecursively() }
    File(context.filesDir, "setup/complete").delete()
    File(context.filesDir, "setup/status.json").delete()
}

private fun statusState(raw: String): String = try {
    JSONObject(raw).optString("state")
} catch (_: Throwable) {
    ""
}
