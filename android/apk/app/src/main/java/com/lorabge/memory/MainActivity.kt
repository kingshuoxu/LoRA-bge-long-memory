package com.lorabge.memory

import android.Manifest
import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
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
    private val openDocument = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@registerForActivityResult
        val activity = this
        Thread {
            try {
                val file = copyOpenedDocument(activity, uri)
                startForegroundService(
                    Intent(activity, DocumentService::class.java).putExtra(DocumentService.EXTRA_PATH, file.absolutePath),
                )
            } catch (err: Throwable) {
                writeDocJob(File(filesDir, "docs/job.json"), DocJob(phase = "error", message = err.message ?: "没有打开"))
            }
        }.start()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes = window.attributes.apply {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightNavigationBars = false
        val store = MemoryStore(File(filesDir, "memory"))
        store.ensure()
        val engine = Engine(this, store)
        val client = LlmClient(this)
        engine.disarmUnprovenMali()
        if (intent?.getStringExtra("mode") == "benchmark" || intent?.action == TrainService.ACTION_BENCHMARK) {
            startBenchmark(store, client)
        }
        val benchmark = intent?.getStringExtra("mode") == "benchmark" || intent?.action == TrainService.ACTION_BENCHMARK
        val e2e = File(filesDir, "setup/e2e").exists()
        setContent {
            var ready by remember { mutableStateOf(benchmark || e2e || !FetchService.needsSetup(this)) }
            if (!ready) {
                SetupScreen(onFinished = { ready = true })
                return@setContent
            }
            PhoneApp(store, engine, client, probeOnStart = !benchmark && !e2e, e2e = e2e, onCleared = { ready = false }, onTrain = {
                if (Build.VERSION.SDK_INT >= 33 &&
                    ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED
                ) {
                    notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
                Thread {
                    client.park()
                    startForegroundService(Intent(this, TrainService::class.java))
                }.start()
            }, onCancel = {
                TrainService.abandon(store)
                startService(Intent(this, TrainService::class.java).setAction(TrainService.ACTION_CANCEL))
            }, onExport = {
                shareDiagnostics(engine.diagnostics())
            }, onImport = {
                openDocument.launch(
                    arrayOf(
                        "application/pdf",
                        "text/plain",
                        "text/markdown",
                        "text/x-markdown",
                        "application/epub+zip",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "*/*",
                    ),
                )
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

    private fun startBenchmark(store: MemoryStore, client: LlmClient) {
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
        Thread {
            client.park()
            startForegroundService(Intent(this, TrainService::class.java))
        }.start()
    }
}

@Composable
private fun PhoneApp(
    store: MemoryStore,
    engine: Engine,
    client: LlmClient,
    probeOnStart: Boolean,
    e2e: Boolean,
    onTrain: () -> Unit,
    onCancel: () -> Unit,
    onExport: () -> Unit,
    onCleared: () -> Unit,
    onImport: () -> Unit = {},
) {
    var lang by remember { mutableStateOf("zh") }
    var tab by remember { mutableStateOf(SkyTab.Chat) }
    var tick by remember { mutableIntStateOf(0) }
    var note by remember { mutableStateOf("") }
    var toast by remember { mutableStateOf("") }
    LaunchedEffect(toast) {
        if (toast.isBlank()) return@LaunchedEffect
        delay(3500)
        toast = ""
    }
    var cpuNoticeShown by remember { mutableStateOf(false) }
    var updatePhase by remember { mutableStateOf("") }
    var updateVersion by remember { mutableStateOf("") }
    var updateNotes by remember { mutableStateOf("") }
    var updateMessage by remember { mutableStateOf("") }
    var updateOffer by remember { mutableStateOf<UpdateOffer?>(null) }
    var updateBusy by remember { mutableStateOf(false) }
    val context = androidx.compose.ui.platform.LocalContext.current
    val packageVersion = remember {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toInt() else @Suppress("DEPRECATION") info.versionCode
    }
    LaunchedEffect(packageVersion) {
        if (e2e) return@LaunchedEffect
        val langNow = lang
        Thread {
            val offer = try {
                lookupUpdate(packageVersion, ::bytesOfUpdateText)
            } catch (_: Throwable) {
                null
            }
            if (offer != null && updatePhase.isBlank()) {
                updateOffer = offer
                updateVersion = offer.versionName
                updateNotes = offer.notes.trim()
                updatePhase = "available"
                updateMessage = if (langNow == "en") "Version ${offer.versionName}" else "版本 ${offer.versionName}"
            }
        }.start()
    }
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
                if (fallback.isNotBlank()) {
                    if (!cpuNoticeShown) {
                        toast = fallback
                        cpuNoticeShown = true
                    }
                    client.acknowledgeNotice()
                }
                running.set(false)
            }
        }.start()
        while (running.get()) delay(200)
        tick++
    }
    var settingsOpen by remember { mutableStateOf(false) }
    var drawerOpen by remember { mutableStateOf(false) }
    var wifiOnly by remember { mutableStateOf(FetchService.wifiOnly(context)) }
    var manifestUrl by remember { mutableStateOf(FetchService.manifestUrl(context)) }
    var recallJson by remember { mutableStateOf("") }
    var recallBanner by remember { mutableStateOf("") }
    var draft by remember { mutableStateOf("") }
    var draftEpoch by remember { mutableIntStateOf(0) }
    LaunchedEffect(e2e) {
        if (!e2e) return@LaunchedEffect
        while (true) {
            delay(200)
            val epoch = draftEpoch
            val text = E2eDraft.poll(context.filesDir) ?: continue
            if (epoch != draftEpoch) continue
            if (draft != text) draft = text
        }
    }
    var generating by remember { mutableStateOf(false) }
    var streaming by remember { mutableStateOf("") }
    var currentId by remember { mutableStateOf(store.listConversations().firstOrNull()?.id) }
    var pending by remember { mutableStateOf<PendingCorrection?>(null) }
    var entity by remember { mutableStateOf("") }
    var statement by remember { mutableStateOf("") }
    var value by remember { mutableStateOf("") }
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var attr by remember { mutableStateOf("") }
    var editorOpen by remember { mutableStateOf(false) }
    var docReview by remember { mutableStateOf<List<DocPoint>>(emptyList()) }
    var docReviewId by remember { mutableStateOf("") }
    var docReviewTitle by remember { mutableStateOf("") }
    var passage by remember { mutableStateOf<DocChip?>(null) }
    var deleteDocId by remember { mutableStateOf("") }
    var deleteDocTitle by remember { mutableStateOf("") }
    var docShown by remember { mutableStateOf("") }
    var importLive by remember { mutableStateOf(false) }
    var docPulse by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        val pendingJob = readDocJob(File(docsRoot(store), "job.json"))
        if (pendingJob.phase in setOf("parse", "split", "index", "points") && pendingJob.source.isNotBlank()) {
            context.startForegroundService(
                Intent(context, DocumentService::class.java).putExtra(DocumentService.EXTRA_PATH, pendingJob.source),
            )
        }
        while (true) {
            delay(400)
            docPulse++
        }
    }
    val docRoot = docsRoot(store)
    val docJob = remember(docPulse) { readDocJob(File(docRoot, "job.json")) }
    val docRecords = remember(docPulse, tick) { listDocRecords(docRoot, store) }
    LaunchedEffect(docJob.phase, docJob.docId) {
        // A book that was already finished before this launch must not cover the chat.
        // The review opens only after this session sees the import move, then finish.
        if (docJob.phase in setOf("parse", "split", "index", "points")) importLive = true
        if (!importLive || docJob.phase != "done" || docJob.docId.isBlank() || docShown == docJob.docId) return@LaunchedEffect
        val points = loadDocPoints(File(docRoot, "${docJob.docId}/points.json"))
        if (points.isNotEmpty()) {
            docReview = points
            docReviewId = docJob.docId
            docReviewTitle = docJob.title
            tab = SkyTab.Library
        }
        docShown = docJob.docId
        importLive = false
    }
    var force by remember { mutableStateOf(true) }
    var waitSeconds by remember { mutableIntStateOf(0) }
    val statusFile = File(store.trainDir, "status.json")
    var trainSnap by remember {
        mutableStateOf(parseTrainSnapshot(runCatching { statusFile.takeIf { it.exists() }?.readText().orEmpty() }.getOrDefault("")))
    }
    val training = trainSnap.state == "running"
    LaunchedEffect(generating, streaming) {
        if (!generating || streaming.isNotBlank()) {
            waitSeconds = 0
            return@LaunchedEffect
        }
        var waited = 0
        while (true) {
            delay(1000)
            if (!generating || streaming.isNotBlank()) break
            waited += 1
            waitSeconds = waited
        }
    }
    // 训练在 :train 进程里写 status.json。空读和同一张失败卡不再整页重组。
    LaunchedEffect(statusFile.absolutePath) {
        var held = trainSnap
        while (true) {
            delay(350)
            val exists = statusFile.exists()
            val raw = if (exists) runCatching { statusFile.readText() }.getOrDefault("") else ""
            val next = acceptTrainStatus(held, raw, exists) ?: continue
            held = next
            trainSnap = next
        }
    }
    val conversations = remember(tick) { store.listConversations() }
    val current = currentId?.let { store.loadConversation(it) }
    val experts = remember(tick, lang) { skyExperts(store, lang) }
    val highlight = current?.messages?.lastOrNull { it.role == "assistant" }?.expert
    val loss = remember(tick) { readLoss(File(store.trainDir, "train.log")) }
    val record = engine.backendRecord()
    val storageLabel = remember(tick) { formatBytes(modelBytes(context)) }
    val versionName = remember {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0.1.32"
    }
    var nebulaCanvas by remember { mutableStateOf(false) }
    val sessionGate = remember {
        File(store.trainDir, "session-new.txt").delete()
        true
    }
    val freshExperts = remember(tick, sessionGate) { NebulaGraph.sessionNew(store) }
    val nebulaJson = remember(tick, lang, freshExperts) { NebulaGraph.build(store, lang, freshExperts) }
    val storedLines = experts.flatMap { it.facts }
    val notedForm = if (statement.isBlank()) null else FactDraft(entity, attr, statement, value, question, answer)
    val waiting = remember(tick, statement, entity, value, question, answer, attr, experts) {
        gatherPendingDrafts(store, storedLines, notedForm)
    }
    val remembered = remember(tick, statement, entity, value, question, answer, attr, experts) {
        gatherRememberedDrafts(store, storedLines, notedForm)
    }
    val savedBatch = remember(tick) { TrainBatchStore.read(store) }
    LaunchedEffect(Unit) {
        val moved = store.migratePossessedEntities()
        val absorbed = absorbRememberedAliases(store)
        val finished = migrateFinishedTrain(store)
        if (moved || absorbed || finished) tick++
    }
    LaunchedEffect(trainSnap.state) {
        if (trainSnap.state == "running") {
            while (true) {
                delay(3000)
                if (!statusFile.exists()) {
                    val cleared = acceptTrainStatus(trainSnap, "", fileExists = false)
                    if (cleared != null) trainSnap = cleared
                    return@LaunchedEffect
                }
                val raw = runCatching { statusFile.readText() }.getOrDefault("")
                val now = parseTrainSnapshot(raw)
                // A cut-off read is not a new state, and it must not kill the trainer.
                if (now.state.isEmpty()) continue
                if (shouldRemarkFailedTrain(now.state) &&
                    trainRunIsStale(
                        now.state,
                        TrainService.trainPidAlive(store),
                        TrainService.heartbeatAgeMs(store),
                        pidKnown = TrainService.trainPidKnown(store),
                    )
                ) {
                    val alive = TrainService.trainPidAlive(store)
                    val exit = if (alive) {
                        null
                    } else {
                        delay(400)
                        val config = File(store.trainDir, "config.json").takeIf { it.exists() }
                            ?.readText()?.let { parseTrainConfig(it) }
                        pickTrainExit(
                            readHistoricalTrainExits(context),
                            null,
                            ":train",
                            config?.startedMs ?: 0L,
                        )
                    }
                    TrainService.markDead(store, exit)
                }
                if (!statusFile.exists()) {
                    val cleared = acceptTrainStatus(trainSnap, "", fileExists = false)
                    if (cleared != null) trainSnap = cleared
                    return@LaunchedEffect
                }
                val after = runCatching { statusFile.readText() }.getOrDefault("")
                val afterSnap = parseTrainSnapshot(after)
                if (afterSnap.state.isEmpty()) continue
                val next = acceptTrainStatus(trainSnap, after, fileExists = true)
                if (next != null && next.state != "running") {
                    trainSnap = next
                    return@LaunchedEffect
                }
                if (!shouldRemarkFailedTrain(afterSnap.state)) return@LaunchedEffect
            }
        }
        var chained = false
        try {
        val live = trainSnap
        val stuck = TrainBatchStore.read(store)
        if (shouldRecoverBatch(stuck, live.state)) {
            TrainBatchStore.clear(store)
            if (live.state == "waiting") {
                statusFile.delete()
                trainSnap = TrainSnapshot()
            }
            tick++
            return@LaunchedEffect
        }
        if (stuck != null && live.state != "running") {
            val collapsed = collapseSavedBatch(stuck)
            if (collapsed.groups != stuck.groups) {
                TrainBatchStore.write(store, collapsed)
                tick++
                return@LaunchedEffect
            }
        }
        val batch = TrainBatchStore.read(store)
        if (batch != null && sealedTrain(store.trainDir, trainSnap) && migrateFinishedTrain(store)) {
            tick++
            return@LaunchedEffect
        }
        if (batch != null && batch.phase == "running" && trainSnap.state == "error" && !sealedTrain(store.trainDir, trainSnap)) {
            TrainBatchStore.write(store, batch.copy(phase = "error"))
            tick++
            return@LaunchedEffect
        }
        if (batch != null && batch.phase == "running" && trainSnap.state == "done") {
            if (batch.index + 1 < batch.groups.size) {
                val nextIndex = batch.index + 1
                val wanted = batch.groups[nextIndex].map { it.trim() }.toSet()
                val facts = waiting.filter { it.statement.trim() in wanted }.map { it.toReviewed() }
                if (facts.isNotEmpty()) {
                    TrainBatchStore.write(store, batch.copy(index = nextIndex))
                    TrainService.writeReviewedList(store, facts, force = true)
                    armForeground(store)
                    chained = true
                    onTrain()
                    tick++
                    return@LaunchedEffect
                }
            }
            TrainBatchStore.write(store, batch.copy(phase = "done"))
            tick++
            return@LaunchedEffect
        }
        if (trainSnap.state != "done" || statement.isBlank()) return@LaunchedEffect
        val stored = experts.flatMap { it.facts }
        if (pendingFactLines(listOf(statement), stored).isNotEmpty()) return@LaunchedEffect
        val next = waiting.firstOrNull { pendingFactLines(listOf(it.statement), stored).isNotEmpty() } ?: return@LaunchedEffect
        entity = next.entity
        attr = next.attr
        statement = next.statement
        value = next.value
        question = next.question
        answer = next.answer
        } finally {
            if (!chained) client.resume()
        }
    }
    val state = SkyState(
        lang = lang,
        tab = tab,
        training = training,
        status = presentTrainStatus(lang, statusFile.takeIf { it.exists() }?.readText().orEmpty()),
        messages = current?.messages?.map { SkyMessage(it.role, it.content, it.expert, it.reason, it.noticed, it.sources) } ?: emptyList(),
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
        updatePhase = updatePhase,
        updateVersion = updateVersion,
        updateNotes = updateNotes,
        updateMessage = updateMessage,
        waitSeconds = waitSeconds,
        liveMotion = true,
        train = trainSnap,
        nebulaCanvas = nebulaCanvas,
        e2e = e2e,
        pendingFacts = waiting.map { it.statement },
        rememberedFacts = remembered.map { it.statement },
        pendingDrafts = waiting.map {
            SkyPending(it.entity, it.statement, it.value, it.question, it.answer, it.attr, it.merged)
        },
        batchItems = (savedBatch?.let { saved ->
            val lines = saved.groups.flatten().map { it.trim() }.filter { it.isNotEmpty() }
            val expert = jobExpertName(store.trainDir)
            val registered = if (expert == null) {
                emptySet()
            } else {
                store.readReviewedFacts(expert).map { it.statement.trim() }.toSet()
            }
            val succeeded = sealedTrain(store.trainDir, trainSnap) && lines.isNotEmpty() && lines.all { it in registered }
            batchMarks(saved, trainSnap.state, succeeded)
        } ?: emptyList()).map { (line, mark) ->
            SkyBatchItem(line, mark)
        },
        editorOpen = editorOpen,
        docs = docRecords,
        docJob = docJob,
        docReview = docReview,
        docReviewTitle = docReviewTitle,
        docReviewId = docReviewId,
        passage = passage,
        deleteDocId = deleteDocId,
        deleteDocTitle = deleteDocTitle,
    )
    SkyFrame(state) { event ->
        when (event) {
            is SkyEvent.Lang -> lang = event.lang
            is SkyEvent.Tab -> tab = event.tab
            is SkyEvent.Draft -> {
                draft = if (e2e) E2eDraft.poll(context.filesDir) ?: event.text else event.text
            }
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
                if (e2e) {
                    draftEpoch++
                    E2eDraft.clear(context.filesDir)
                }
                val conversation = current ?: store.newConversation().also { currentId = it.id }
                val now = Instant.now().toString()
                val title = if (conversation.messages.isEmpty()) text.take(18) else conversation.title
                val withUser = conversation.messages + ChatMessage("user", text)
                store.saveConversation(conversation.copy(title = title, updated = now, messages = withUser))
                draft = ""
                tick++
                val langNow = lang
                if (e2e && text == "__e2e_wait__") {
                    generating = true
                    streaming = ""
                    Thread {
                        // 模拟器上 UiAutomator 一轮查询就要一两秒。圆点留够久，测试才看得到相位变化和「已等待」。
                        Thread.sleep(12_000)
                        streaming = "好"
                        Thread.sleep(300)
                        val saved = store.loadConversation(conversation.id)
                        val base = saved ?: conversation.copy(title = title, updated = now, messages = withUser)
                        val messages = base.messages + ChatMessage("assistant", "好")
                        store.saveConversation(base.copy(updated = Instant.now().toString(), messages = messages))
                        generating = false
                        streaming = ""
                        tick++
                    }.start()
                    return@SkyFrame
                }
                val facts = FactNotice.drafts(text)
                val noticed = facts.isNotEmpty() || FactNotice.noticed(text)
                if (noticed) {
                    val storedNow = experts.flatMap { it.facts }
                    val embed = if (engine.bgeModel() != null) {
                        { lines: List<String> -> engine.embedTexts(lines) }
                    } else {
                        null
                    }
                    val fresh = facts.filter { !matchesStored(it.statement, storedNow, embed) }
                    val known = facts.filter { matchesStored(it.statement, storedNow, embed) }
                    known.forEach { store.attachRememberedAlias(it.statement) }
                    val fact = fresh.firstOrNull()
                    if (fact != null) {
                        entity = fact.entity
                        attr = fact.attr
                        statement = fact.statement
                        value = fact.value
                        question = fact.question
                        answer = fact.answer
                        pending = null
                    } else if (known.isNotEmpty()) {
                        statement = ""
                        entity = ""
                        attr = ""
                        value = ""
                        question = ""
                        answer = ""
                        pending = null
                    } else if (looksLikeCorrection(text)) {
                        pending = guessCorrection(text)
                    }
                    val reply = when {
                        fresh.isNotEmpty() -> FactNotice.acknowledgeAll(fresh, langNow)
                        known.isNotEmpty() -> FactNotice.already(known.first(), langNow)
                        langNow == "en" -> "Okay, I'll remember."
                        else -> "好的，记住了。"
                    }
                    val taught = facts.firstOrNull()
                    val taughtEntity = taught?.entity ?: if (looksLikeCorrection(text)) guessCorrection(text).entity else ""
                    val taughtExpert = if (facts.isNotEmpty() && facts.all { it.entity == "我" } || taughtEntity == "我") {
                        SELF_EXPERT
                    } else {
                        ""
                    }
                    writeTeachRoute(context, text, taughtEntity, taughtExpert, reply)
                    val saved = store.loadConversation(conversation.id)
                    val base = saved ?: conversation.copy(title = title, updated = now, messages = withUser)
                    val messages = base.messages + ChatMessage("assistant", reply, noticed = true)
                    store.saveConversation(base.copy(updated = Instant.now().toString(), messages = messages))
                    tick++
                    return@SkyFrame
                }
                generating = true
                streaming = ""
                val selfKind = EntityGround.selfAsk(text)
                val groundedRaw = EntityGround.reply(text, EntityGround.load(store), langNow)
                val grounded = groundedRaw?.takeUnless { it.answer.startsWith("已导入《") }
                val useSelf = selfKind != null && selfKind != "assistant"
                Thread {
                    val hit = try {
                        client.route(text)
                    } catch (ex: Throwable) {
                        RouteHit(null, false, ex.message ?: "route", 0.0)
                    }
                    val indexed = if (useSelf) emptyList() else loadIndexedDocs(docsRoot(store))
                    val queryVector = if (indexed.any { it.vectors != null } && engine.binariesReady() && engine.bgeModel() != null) {
                        runCatching { engine.embedTexts(listOf(text)).firstOrNull() }.getOrNull()
                    } else {
                        null
                    }
                    val searched = if (indexed.isEmpty()) null else searchDocuments(text, indexed, queryVector)
                    val doc = searched?.ground
                    val miss = if (searched != null && admitNoPassage(searched, docMinScore(queryVector != null), queryVector != null)) {
                        val named = missedDocumentTitle(text, indexed)
                        if (named.isBlank()) {
                            if (langNow == "en") "Nothing relevant turned up in the documents." else "文档里没有找到相关内容。"
                        } else {
                            documentMiss(named, langNow)
                        }
                    } else {
                        null
                    }
                    val memory = if (useSelf) grounded else grounded?.takeIf { doc == null }
                    writeLastRoute(context, text, hit, memory)
                    val expert = when {
                        useSelf -> grounded?.expert
                        doc != null -> doc.expert
                        else -> grounded?.expert ?: if (hit.fired) hit.expert else null
                    }
                    val reason = when {
                        useSelf -> grounded?.reason ?: hit.reason
                        doc != null -> "document"
                        else -> grounded?.reason ?: hit.reason
                    }
                    val trace = NebulaGraph.recall(store, langNow, expert, expert != null, hit.sim, text)
                    recallJson = trace
                    recallBanner = org.json.JSONObject(trace).optString("banner")
                    val reply = when {
                        useSelf && grounded != null -> grounded.answer
                        doc != null -> doc.answer
                        grounded != null -> grounded.answer
                        miss != null -> miss
                        else -> {
                            try {
                                client.answer(text, expert) { streaming = it }
                            } catch (ex: ChatParked) {
                                if (langNow == "en") "Training is using the memory. Ask again in a moment." else "正在巩固，请稍后再问。"
                            } catch (ex: Throwable) {
                                if (langNow == "en") "Couldn't generate" else "生成失败"
                            }
                        }
                    }
                    val sources = if (doc != null && !useSelf) doc.chips else emptyList()
                    val saved = store.loadConversation(conversation.id) ?: withUser.let {
                        conversation.copy(title = title, updated = now, messages = withUser)
                    }
                    val messages = saved.messages + ChatMessage("assistant", reply, expert, reason, noticed = false, sources = sources)
                    store.saveConversation(saved.copy(updated = Instant.now().toString(), messages = messages))
                    generating = false
                    streaming = ""
                    val fallback = client.notice(langNow)
                    if (fallback.isNotBlank()) {
                        if (!cpuNoticeShown) {
                            toast = fallback
                            cpuNoticeShown = true
                        }
                        client.acknowledgeNotice()
                    }
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
                beginImmediate(store, listOf(fact))
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
            is SkyEvent.FocusPending -> {
                val draft = waiting.firstOrNull { it.statement == event.statement } ?: return@SkyFrame
                entity = draft.entity
                attr = draft.attr
                statement = draft.statement
                value = draft.value
                question = draft.question
                answer = draft.answer
                editorOpen = true
            }
            is SkyEvent.TrainPending -> {
                val draft = waiting.firstOrNull { it.statement == event.statement } ?: return@SkyFrame
                if (training || trainSnap.state == "running") {
                    queueBehind(store, draft.statement)
                    tick++
                    return@SkyFrame
                }
                entity = draft.entity
                attr = draft.attr
                statement = draft.statement
                value = draft.value
                question = draft.question
                answer = draft.answer
                beginImmediate(store, listOf(draft.toReviewed()))
                editorOpen = false
                onTrain()
                tick++
            }
            SkyEvent.TrainAll -> {
                if (training || trainSnap.state == "running") {
                    waiting.forEach { queueBehind(store, it.statement) }
                    tick++
                    return@SkyFrame
                }
                if (waiting.isNotEmpty()) {
                    beginImmediate(store, waiting.map { it.toReviewed() })
                    editorOpen = false
                    onTrain()
                    tick++
                    return@SkyFrame
                }
                val job = File(store.trainDir, "job.json")
                if (job.exists()) {
                    armForeground(store)
                    onTrain()
                    tick++
                }
            }
            SkyEvent.Train -> {
                if (training || trainSnap.state == "running") return@SkyFrame
                if (entity.isBlank() || statement.isBlank() || value.isBlank()) {
                    val job = File(store.trainDir, "job.json")
                    val again = trainSnap.state == "error" || trainSnap.state == "cancelled" || trainSnap.state == "waiting"
                    if (job.exists() && again) {
                        armForeground(store)
                        onTrain()
                        tick++
                    }
                    return@SkyFrame
                }
                val qa = if (question.isBlank()) emptyList() else listOf(question to answer.ifBlank { value })
                val fact = ReviewedFact(
                    entity.trim(),
                    statement.trim(),
                    value.trim(),
                    qa,
                    emptyList(),
                    attr = attr.trim(),
                    selected = true,
                )
                beginImmediate(store, listOf(fact))
                onTrain()
                tick++
            }
            SkyEvent.CancelTrain -> {
                TrainBatchStore.clear(store)
                if (trainSnap.state == "error") {
                    File(store.trainDir, "status.json").delete()
                    File(store.trainDir, "cancel").delete()
                    File(store.trainDir, "heartbeat").delete()
                    trainSnap = TrainSnapshot()
                    tick++
                } else {
                    onCancel()
                }
            }
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
            SkyEvent.ImportDocument -> onImport()
            SkyEvent.CancelDoc -> {
                File(docsRoot(store), "cancel").apply { parentFile?.mkdirs() }.writeText("1")
                context.startService(Intent(context, DocumentService::class.java).setAction(DocumentService.ACTION_CANCEL))
            }
            is SkyEvent.ToggleDocPoint -> {
                docReview = docReview.map { point ->
                    if (point.id == event.id) point.copy(selected = !point.selected) else point
                }
                if (docReviewId.isNotBlank()) saveDocPoints(File(docsRoot(store), "$docReviewId/points.json"), docReview)
            }
            SkyEvent.TrainDocPoints -> {
                if (docReviewId.isNotBlank()) queueDocPoints(store, docReviewId, docReview)
                val count = docReview.count { it.selected }
                toast = if (lang == "en") {
                    "Added to consolidate. ${trainEstimate(count, lang)}"
                } else {
                    "已放入待巩固。${trainEstimate(count, lang)}"
                }
                docReview = emptyList()
                tab = SkyTab.Consolidate
                tick++
            }
            SkyEvent.DismissDocReview -> docReview = emptyList()
            is SkyEvent.OpenDoc -> {
                val record = docRecords.firstOrNull { it.id == event.id }
                docReview = loadDocPoints(File(docsRoot(store), "${event.id}/points.json"))
                docReviewId = event.id
                docReviewTitle = record?.title.orEmpty()
            }
            is SkyEvent.DeleteDoc -> {
                deleteDocId = event.id
                deleteDocTitle = docRecords.firstOrNull { it.id == event.id }?.title.orEmpty()
            }
            SkyEvent.ConfirmDeleteDoc -> {
                if (deleteDocId.isNotBlank()) deleteDocument(store, deleteDocId)
                if (docReviewId == deleteDocId) docReview = emptyList()
                deleteDocId = ""
                deleteDocTitle = ""
                tick++
            }
            SkyEvent.DismissDeleteDoc -> {
                deleteDocId = ""
                deleteDocTitle = ""
            }
            is SkyEvent.OpenPassage -> passage = event.chip
            SkyEvent.ClosePassage -> passage = null
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
            SkyEvent.DismissUpdate -> {
                updatePhase = ""
                updateMessage = ""
            }
            SkyEvent.CheckUpdate -> {
                if (updateBusy) return@SkyFrame
                val langNow = lang
                updatePhase = "downloading"
                updateMessage = if (langNow == "en") "Checking" else "正在检查"
                Thread {
                    try {
                        val offer = lookupUpdate(packageVersion, ::bytesOfUpdateText)
                        if (offer == null) {
                            updateOffer = null
                            updatePhase = "latest"
                            updateVersion = ""
                            updateNotes = ""
                            updateMessage = ""
                        } else {
                            updateOffer = offer
                            updateVersion = offer.versionName
                            updateNotes = offer.notes.trim()
                            updatePhase = "available"
                            updateMessage = if (langNow == "en") "Version ${offer.versionName}" else "版本 ${offer.versionName}"
                        }
                    } catch (ex: Throwable) {
                        updatePhase = "error"
                        updateMessage = explainUpdateFailure(ex.message)
                    }
                }.start()
            }
            SkyEvent.StartUpdate -> {
                val offer = updateOffer ?: return@SkyFrame
                val langNow = lang
                if (UpdateInstaller.needsUnknownSources(context)) {
                    updatePhase = "need_permission"
                    updateMessage = ""
                    context.startActivity(UpdateInstaller.unknownSourcesIntent(context))
                    return@SkyFrame
                }
                if (updateBusy) return@SkyFrame
                updateBusy = true
                updatePhase = "downloading"
                Thread {
                    try {
                        val file = downloadUpdate(context.filesDir, offer, RemoteOpener { url, offset -> httpOpen(url, offset) }) { snap ->
                            updateMessage = snap.message.ifBlank {
                                if (langNow == "en") "Downloading" else "正在下载"
                            }
                        }
                        UpdateInstaller.install(context, file)
                        updatePhase = "installing"
                        updateMessage = ""
                    } catch (ex: Throwable) {
                        updatePhase = "error"
                        updateMessage = explainUpdateFailure(ex.message)
                    } finally {
                        updateBusy = false
                    }
                }.start()
            }
            is SkyEvent.NebulaGl -> {
                if (event.fallback == "canvas") nebulaCanvas = true
                if (event.fallback == "webgl1" || event.fallback == "canvas") {
                    val msg = noteNebulaFallback(context, lang)
                    if (msg != null && toast.isBlank()) toast = msg
                }
            }
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
    return log.readLines().mapNotNull { parseStepLine(it)?.third }
}

private fun skyExperts(store: MemoryStore, lang: String): List<SkyExpert> {
    return store.listExperts().filter { !it.expert.startsWith("doc_") }.map { record ->
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

private fun FactDraft.toReviewed(): ReviewedFact {
    val qa = if (question.isBlank()) emptyList() else listOf(question to answer.ifBlank { value })
    return ReviewedFact(entity.trim(), statement.trim(), value.trim(), qa, emptyList(), attr = attr.trim(), selected = true)
}

/** A tap on this page starts the foreground service now. It does not wait for charging or a dark screen. */
private fun armForeground(store: MemoryStore) {
    store.ensure()
    File(store.trainDir, "force").writeText("1")
    File(store.trainDir, "cancel").delete()
    File(store.trainDir, "pid").delete()
    File(store.trainDir, "heartbeat").delete()
    writeTextAtomic(
        File(store.trainDir, "status.json"),
        trainSnapshotJson("running", "extract", 0, 0, 4, null, 0, "抽取事实", ""),
    )
}

private fun beginImmediate(store: MemoryStore, facts: List<ReviewedFact>) {
    val groups = planTrainGroups(facts)
    if (groups.isEmpty()) return
    TrainBatchStore.write(store, SavedBatch(groups.map { group -> group.map { it.statement } }, 0, "running"))
    TrainService.writeReviewedList(store, groups[0], force = true)
    armForeground(store)
}

private fun queueBehind(store: MemoryStore, statement: String) {
    val key = statement.trim()
    if (key.isEmpty()) return
    val current = TrainBatchStore.read(store)
    if (current == null) {
        val running = jobStatements(store)
        val groups = if (running.isEmpty() || running.any { it.trim() == key }) {
            listOf(if (running.isEmpty()) listOf(key) else running)
        } else {
            listOf(running, listOf(key))
        }
        TrainBatchStore.write(store, SavedBatch(groups, 0, "running"))
    } else {
        TrainBatchStore.write(store, enqueueStatement(current, key))
    }
}

private fun jobStatements(store: MemoryStore): List<String> {
    val job = File(store.trainDir, "job.json")
    if (!job.exists()) return emptyList()
    val facts = runCatching { org.json.JSONObject(job.readText()).optJSONArray("facts") }.getOrNull() ?: return emptyList()
    val out = ArrayList<String>()
    for (i in 0 until facts.length()) {
        val line = facts.getJSONObject(i).optString("statement").trim()
        if (line.isNotEmpty()) out.add(line)
    }
    return out
}

internal const val REMEMBER_SIM = 0.86

internal fun normalizeFactKey(text: String): String {
    var key = foldStatement(text)
    if (key.startsWith("我是")) key = "我叫" + key.removePrefix("我是")
    return key
}

internal fun cosineSimilarity(left: FloatArray, right: FloatArray): Double {
    if (left.isEmpty() || left.size != right.size) return 0.0
    var dot = 0.0
    var leftNorm = 0.0
    var rightNorm = 0.0
    for (index in left.indices) {
        dot += left[index] * right[index]
        leftNorm += left[index] * left[index]
        rightNorm += right[index] * right[index]
    }
    if (leftNorm <= 0.0 || rightNorm <= 0.0) return 0.0
    return dot / (kotlin.math.sqrt(leftNorm) * kotlin.math.sqrt(rightNorm))
}

/**
 * Same memory after punctuation, 猫猫/猫 and 我是/我叫 are folded.
 * Anything still different is the same only when bge cosine is at least [REMEMBER_SIM].
 */
internal fun isSameMemory(
    pending: String,
    stored: String,
    embed: ((List<String>) -> List<FloatArray>)? = null,
): Boolean {
    val left = normalizeFactKey(pending)
    val right = normalizeFactKey(stored)
    if (left.isNotEmpty() && left == right) return true
    if (left.isEmpty() || right.isEmpty() || embed == null) return false
    val vectors = runCatching { embed(listOf(left, right)) }.getOrNull() ?: return false
    if (vectors.size < 2) return false
    return cosineSimilarity(vectors[0], vectors[1]) >= REMEMBER_SIM
}

internal fun matchesStored(
    line: String,
    stored: List<String>,
    embed: ((List<String>) -> List<FloatArray>)? = null,
): Boolean {
    val key = normalizeFactKey(line)
    if (key.isNotEmpty() && stored.any { normalizeFactKey(it) == key }) return true
    if (embed == null || key.isEmpty()) return false
    val keys = stored.map { normalizeFactKey(it) }.filter { it.isNotEmpty() }
    if (keys.isEmpty()) return false
    val vectors = runCatching { embed(listOf(key) + keys) }.getOrNull() ?: return false
    if (vectors.size != keys.size + 1) return false
    return vectors.drop(1).any { cosineSimilarity(vectors[0], it) >= REMEMBER_SIM }
}

internal fun pendingFactLines(
    noted: List<String>,
    stored: List<String>,
    embed: ((List<String>) -> List<FloatArray>)? = null,
): List<String> {
    return noted.map { it.trim() }.filter { it.isNotBlank() }.distinct().filter { line ->
        !matchesStored(line, stored, embed)
    }
}

internal fun rememberedFactLines(
    noted: List<String>,
    stored: List<String>,
    embed: ((List<String>) -> List<FloatArray>)? = null,
): List<String> {
    return noted.map { it.trim() }.filter { it.isNotBlank() }.distinct().filter { line ->
        matchesStored(line, stored, embed) && stored.none { known ->
            known.trim().trimEnd('。', '.', '！', '!') == line.trim().trimEnd('。', '.', '！', '!')
        }
    }
}

internal fun pendingDrafts(
    drafts: List<FactDraft>,
    stored: List<String>,
    embed: ((List<String>) -> List<FloatArray>)? = null,
): List<FactDraft> {
    val allowed = pendingFactLines(drafts.map { it.statement }, stored, embed)
    val seen = HashSet<String>()
    val out = ArrayList<FactDraft>()
    for (line in allowed) {
        val draft = drafts.firstOrNull { it.statement.trim() == line } ?: continue
        if (seen.add(line)) out.add(draft)
    }
    return dedupePendingFacts(out)
}

internal fun foldStatement(text: String): String {
    val bare = text.trim().lowercase()
        .trimEnd('。', '.', '！', '!', '？', '?', ' ')
        .replace(Regex("[\\s，,。.!！？?、]"), "")
    return bare.replace(Regex("(.)\\1+"), "$1")
}

internal fun samePendingFact(a: FactDraft, b: FactDraft): Boolean {
    if (a.entity.trim() != b.entity.trim()) return false
    val valueA = a.value.trim().trimEnd('。', '.', '！', '!', ' ')
    val valueB = b.value.trim().trimEnd('。', '.', '！', '!', ' ')
    if (valueA.isEmpty() || valueA != valueB) return false
    if (a.attr.isNotBlank() && a.attr.trim() == b.attr.trim()) return true
    return foldStatement(a.statement) == foldStatement(b.statement)
}

internal fun preferPendingFact(a: FactDraft, b: FactDraft): FactDraft {
    fun score(draft: FactDraft): Int {
        val line = draft.statement.trim()
        var score = -line.length
        if (line.startsWith("我叫")) score += 8
        if (line.startsWith("我的猫叫") && !line.startsWith("我的猫猫")) score += 8
        if (line.contains("猫猫")) score -= 4
        if (line.startsWith("我是")) score -= 2
        return score
    }
    return if (score(b) > score(a)) b else a
}

internal fun dedupePendingFacts(drafts: List<FactDraft>): List<FactDraft> {
    val out = ArrayList<FactDraft>()
    for (draft in drafts) {
        val at = out.indexOfFirst { samePendingFact(it, draft) }
        if (at < 0) {
            out.add(draft.copy(merged = draft.merged.coerceAtLeast(1)))
        } else {
            val kept = preferPendingFact(out[at], draft)
            val count = out[at].merged.coerceAtLeast(1) + draft.merged.coerceAtLeast(1)
            out[at] = kept.copy(merged = count)
        }
    }
    return out
}

internal fun strongerBatchStatus(first: String, second: String): String {
    val rank = mapOf("" to 0, "done" to 1, "queued" to 2, "error" to 3, "waiting" to 4, "running" to 5)
    return if ((rank[second] ?: 0) > (rank[first] ?: 0)) second else first
}

internal fun mergedCaption(lang: String, count: Int): String {
    if (count <= 1) return ""
    return if (lang == "en") "Merged $count" else "已合并 $count 条"
}

/** The queue on screen. Raw rows from an older batch still collapse here. */
/**
 * A finished batch must not hide facts that are still waiting.
 * Rows already marked done stay out of the open list.
 */
internal fun openConsolidateRows(pending: List<String>, batch: List<Pair<String, String>>): List<Pair<String, String>> {
    val active = batch.filter { it.second != "done" }
    val covered = active.map { it.first.trim() }.toSet()
    val extra = pending.map { it.trim() }.filter { it.isNotEmpty() && it !in covered }.map { it to "" }
    return active + extra
}

internal fun collapseShownPending(rows: List<SkyPending>): List<SkyPending> {
    val drafts = rows.map {
        FactDraft(it.entity, it.attr, it.statement, it.value, it.question, it.answer, it.merged.coerceAtLeast(1))
    }
    return dedupePendingFacts(drafts).map {
        SkyPending(it.entity, it.statement, it.value, it.question, it.answer, it.attr, it.merged)
    }
}

/** A document sentence is already one fact. The chat splitter must not cut the year off it. */
internal fun keepWholeStatement(original: String): FactDraft {
    val line = original.trim()
    val parsed = FactNotice.draft(line)
    if (parsed == null || normalizeFactKey(parsed.statement).length + 1 < normalizeFactKey(line).length) {
        return FactDraft(parsed?.entity.orEmpty(), parsed?.attr.orEmpty(), line, line, parsed?.question.orEmpty(), line)
    }
    return parsed
}

internal fun collapseShownBatch(items: List<SkyBatchItem>): List<SkyBatchItem> {
    val drafts = ArrayList<FactDraft>()
    val status = ArrayList<String>()
    for (item in items) {
        val draft = keepWholeStatement(item.statement).copy(merged = item.merged.coerceAtLeast(1))
        val at = drafts.indexOfFirst { samePendingFact(it, draft) }
        if (at < 0) {
            drafts.add(draft)
            status.add(item.status)
        } else {
            val kept = preferPendingFact(drafts[at], draft)
            val count = drafts[at].merged.coerceAtLeast(1) + draft.merged.coerceAtLeast(1)
            drafts[at] = kept.copy(merged = count)
            status[at] = strongerBatchStatus(status[at], item.status)
        }
    }
    return drafts.mapIndexed { index, draft -> SkyBatchItem(draft.statement, status[index], draft.merged) }
}

internal fun collapseStatementGroup(lines: List<String>): List<String> {
    val drafts = lines.map { keepWholeStatement(it) }
    return dedupePendingFacts(drafts).map { it.statement }
}

internal fun collapseSavedBatch(batch: SavedBatch): SavedBatch {
    val groups = batch.groups.map { collapseStatementGroup(it) }.filter { it.isNotEmpty() }
    if (groups.isEmpty()) return batch
    return batch.copy(groups = groups, index = batch.index.coerceIn(0, groups.lastIndex))
}

internal fun gatherNotedDrafts(store: MemoryStore, form: FactDraft?): List<FactDraft> {
    val noted = ArrayList<FactDraft>()
    for (conv in store.listConversations()) {
        val full = store.loadConversation(conv.id) ?: continue
        for (message in full.messages) {
            if (message.role != "user") continue
            val fromDoc = docPointDraft(store, message.content)
            if (fromDoc != null) {
                noted.add(fromDoc)
                continue
            }
            val drafts = FactNotice.drafts(message.content)
            if (drafts.isNotEmpty()) noted.addAll(drafts)
        }
    }
    if (form != null && form.statement.isNotBlank() && noted.none { samePendingFact(it, form) }) noted.add(form)
    return noted
}

internal fun gatherPendingDrafts(store: MemoryStore, stored: List<String>, form: FactDraft?): List<FactDraft> {
    return pendingDrafts(gatherNotedDrafts(store, form), stored)
}

internal fun gatherRememberedDrafts(store: MemoryStore, stored: List<String>, form: FactDraft?): List<FactDraft> {
    val allowed = rememberedFactLines(gatherNotedDrafts(store, form).map { it.statement }, stored).toSet()
    return dedupePendingFacts(gatherNotedDrafts(store, form).filter { it.statement.trim() in allowed })
}

/** Fold near-duplicates that are already consolidated into that fact, so upgrade clears 待巩固. */
internal fun absorbRememberedAliases(store: MemoryStore): Boolean {
    val stored = store.listExperts().flatMap { record ->
        store.readReviewedFacts(record.expert).map { it.statement }
    }
    var changed = false
    for (draft in gatherNotedDrafts(store, null)) {
        if (!matchesStored(draft.statement, stored)) continue
        if (store.attachRememberedAlias(draft.statement)) changed = true
    }
    return changed
}

internal fun lastRouteJson(query: String, hit: RouteHit, grounded: GroundedReply?): String {
    return JSONObject()
        .put("query", query)
        .put("nativeFired", hit.fired)
        .put("nativeReason", hit.reason)
        .put("nativeSim", hit.sim)
        .put("grounded", grounded != null)
        .put("expert", grounded?.expert ?: hit.expert.orEmpty())
        .put("entity", grounded?.entity.orEmpty())
        .put("reason", grounded?.reason ?: hit.reason)
        .toString()
}

private fun writeLastRoute(context: android.content.Context, query: String, hit: RouteHit, grounded: GroundedReply?) {
    val dir = File(context.filesDir, "setup").apply { mkdirs() }
    File(dir, "last-route.json").writeText(lastRouteJson(query, hit, grounded))
}

internal fun teachRouteJson(query: String, entity: String, expert: String, reply: String): String {
    return JSONObject()
        .put("query", query)
        .put("nativeFired", false)
        .put("nativeReason", "teach")
        .put("nativeSim", 0.0)
        .put("grounded", false)
        .put("expert", expert)
        .put("entity", entity)
        .put("reason", "teach")
        .put("reply", reply)
        .toString()
}

internal fun copyOpenedDocument(context: android.content.Context, uri: android.net.Uri): File {
    val inbox = File(context.filesDir, "docs/inbox").apply { mkdirs() }
    val rawName = documentDisplayName(context, uri)
    val safe = rawName.replace(Regex("[^\\p{L}\\p{N}._\\-]"), "_").take(80).ifBlank { "book.txt" }
    val dest = File(inbox, "${System.currentTimeMillis()}-$safe")
    context.contentResolver.openInputStream(uri).use { input ->
        if (input == null) error("没有打开")
        dest.outputStream().use { output ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                output.write(buf, 0, n)
            }
        }
    }
    return dest
}

private fun documentDisplayName(context: android.content.Context, uri: android.net.Uri): String {
    val cursor = context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)
    cursor?.use {
        if (it.moveToFirst()) {
            val name = it.getString(0)
            if (!name.isNullOrBlank()) return name
        }
    }
    return uri.lastPathSegment ?: "book.txt"
}

private fun writeTeachRoute(context: android.content.Context, query: String, entity: String, expert: String, reply: String) {
    val dir = File(context.filesDir, "setup").apply { mkdirs() }
    File(dir, "last-route.json").writeText(teachRouteJson(query, entity, expert, reply))
}
