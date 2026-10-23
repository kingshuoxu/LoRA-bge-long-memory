package com.lorabge.memory

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant

class MainActivity : ComponentActivity() {
    private val notifyPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = MemoryStore(File(filesDir, "memory"))
        store.ensure()
        val engine = Engine(this, store)
        if (intent?.getStringExtra("mode") == "benchmark" || intent?.action == TrainService.ACTION_BENCHMARK) {
            startBenchmark(store)
        }
        setContent {
            PhoneApp(store, engine, onTrain = {
                if (Build.VERSION.SDK_INT >= 33 &&
                    ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED
                ) {
                    notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
                startForegroundService(Intent(this, TrainService::class.java))
            }, onCancel = {
                startService(Intent(this, TrainService::class.java).setAction(TrainService.ACTION_CANCEL))
            })
        }
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
private fun PhoneApp(store: MemoryStore, engine: Engine, onTrain: () -> Unit, onCancel: () -> Unit) {
    var lang by remember { mutableStateOf("zh") }
    var tab by remember { mutableStateOf(SkyTab.Chat) }
    var tick by remember { mutableStateOf(0) }
    var draft by remember { mutableStateOf("") }
    var currentId by remember { mutableStateOf(store.listConversations().firstOrNull()?.id) }
    var pending by remember { mutableStateOf<PendingCorrection?>(null) }
    var entity by remember { mutableStateOf("") }
    var statement by remember { mutableStateOf("") }
    var value by remember { mutableStateOf("") }
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var force by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("") }
    val statusFile = File(store.trainDir, "status.json")
    val training = statusFile.exists() && statusState(statusFile.readText()) == "running"
    LaunchedEffect(training, tick) {
        if (!training) return@LaunchedEffect
        delay(1000)
        tick++
    }
    val conversations = remember(tick) { store.listConversations() }
    val current = currentId?.let { store.loadConversation(it) }
    val experts = remember(tick) { skyExperts(store) }
    val highlight = current?.messages?.lastOrNull { it.role == "assistant" }?.expert
    val loss = remember(tick) { readLoss(File(store.trainDir, "train.log")) }
    val state = SkyState(
        lang = lang,
        tab = tab,
        training = training,
        status = statusFile.takeIf { it.exists() }?.readText().orEmpty(),
        messages = current?.messages?.map { SkyMessage(it.role, it.content, it.expert) } ?: emptyList(),
        draft = draft,
        conversations = conversations.map { it.title },
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
        ready = (if (lang == "en") "base " else "基座 ") +
            (if (engine.baseModel() != null) "ok" else "—") +
            " · bge " + (if (engine.bgeModel() != null) "ok" else "—"),
        note = note,
    )
    SkyFrame(state) { event ->
        when (event) {
            is SkyEvent.Lang -> lang = event.lang
            is SkyEvent.Tab -> tab = event.tab
            is SkyEvent.Draft -> draft = event.text
            SkyEvent.NewChat -> {
                currentId = store.newConversation().id
                tick++
            }
            SkyEvent.Send -> {
                val text = draft.trim()
                if (text.isEmpty()) return@SkyFrame
                if (looksLikeCorrection(text)) {
                    pending = guessCorrection(text)
                    draft = ""
                    return@SkyFrame
                }
                val conversation = current ?: store.newConversation().also { currentId = it.id }
                val hit = try {
                    engine.route(text)
                } catch (ex: Throwable) {
                    RouteHit(null, false, ex.message ?: "route", 0.0)
                }
                val expert = if (hit.fired) hit.expert else null
                val reply = try {
                    engine.answer(text, expert, ngl = if (File(store.root, "use_gpu").exists()) 99 else 0)
                } catch (ex: Throwable) {
                    "生成失败: ${ex.message}"
                }
                val now = Instant.now().toString()
                val messages = conversation.messages + ChatMessage("user", text) + ChatMessage("assistant", reply, expert, hit.reason)
                val title = if (conversation.messages.isEmpty()) text.take(18) else conversation.title
                store.saveConversation(conversation.copy(title = title, updated = now, messages = messages))
                draft = ""
                tick++
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
                try {
                    engine.rebuildIndex()
                } catch (_: Throwable) {
                }
                tick++
            }
            SkyEvent.ImportExperts -> {
                note = try {
                    engine.importExternal()
                    if (lang == "en") "Imported" else "已从 import 导入专家"
                } catch (ex: Throwable) {
                    ex.message ?: "import"
                }
                tick++
            }
            SkyEvent.SelfCheck -> {
                note = try {
                    engine.selfCheck()
                } catch (ex: Throwable) {
                    ex.message ?: "check"
                }
            }
            SkyEvent.ToggleGpu -> {
                val gpu = File(store.root, "use_gpu")
                if (gpu.exists()) gpu.delete() else gpu.writeText("1")
                note = if (gpu.exists()) "Vulkan" else "CPU"
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
    return log.readLines().mapNotNull { line ->
        val at = line.indexOf("loss=")
        if (at < 0) return@mapNotNull null
        line.drop(at + 5).takeWhile { it.isDigit() || it == '.' }.toFloatOrNull()
    }
}

private fun skyExperts(store: MemoryStore): List<SkyExpert> {
    return store.listExperts().map { record ->
        val memory = File(store.expertsDir, "${record.expert}/fact_memory.json")
        val facts = ArrayList<String>()
        if (memory.exists()) {
            val arr = JSONArray(memory.readText())
            for (i in 0 until arr.length()) facts.add(arr.getJSONObject(i).optString("statement"))
        }
        SkyExpert(record.expert, facts)
    }
}

private fun statusState(raw: String): String = try {
    JSONObject(raw).optString("state")
} catch (_: Throwable) {
    ""
}
