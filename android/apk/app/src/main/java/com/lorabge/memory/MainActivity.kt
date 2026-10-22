package com.lorabge.memory

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
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
        setContent {
            MaterialTheme {
                App(store, engine, onTrain = { force ->
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
    }
}

private enum class Tab { Chat, Review, Experts }

@Composable
private fun App(store: MemoryStore, engine: Engine, onTrain: (Boolean) -> Unit, onCancel: () -> Unit) {
    var tab by remember { mutableStateOf(Tab.Chat) }
    var tick by remember { mutableStateOf(0) }
    fun refresh() { tick++ }
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(12.dp)) {
            Row {
                Button(onClick = { tab = Tab.Chat }) { Text("对话") }
                Button(onClick = { tab = Tab.Review }) { Text("整理") }
                Button(onClick = { tab = Tab.Experts }) { Text("专家") }
            }
            Text(
                "基座 ${if (engine.baseModel() != null) "已找到" else "未放入"} · " +
                    "bge ${if (engine.bgeModel() != null) "已找到" else "未放入"} · " +
                    "程序 ${if (engine.binariesReady()) "就绪" else "缺少"}",
                modifier = Modifier.padding(vertical = 8.dp),
            )
            when (tab) {
                Tab.Chat -> ChatTab(store, engine, tick, ::refresh)
                Tab.Review -> ReviewTab(store, tick, ::refresh, onTrain, onCancel)
                Tab.Experts -> ExpertTab(store, engine, tick, ::refresh)
            }
        }
    }
}

@Composable
private fun ColumnScope.ChatTab(store: MemoryStore, engine: Engine, tick: Int, refresh: () -> Unit) {
    val conversations = remember(tick) { store.listConversations() }
    var currentId by remember { mutableStateOf(conversations.firstOrNull()?.id) }
    var draft by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    val current = currentId?.let { store.loadConversation(it) }
    Column(Modifier.weight(1f).fillMaxWidth()) {
        Row {
            Button(onClick = {
                val created = store.newConversation()
                currentId = created.id
                refresh()
            }) { Text("新对话") }
        }
        LazyColumn(Modifier.weight(1f)) {
            items(current?.messages ?: emptyList()) { message ->
                val who = if (message.role == "user") "我" else "助手"
                val extra = if (message.expert != null) " · ${message.expert}/${message.reason}" else ""
                Text("$who$extra\n${message.content}", modifier = Modifier.padding(vertical = 4.dp))
            }
        }
        if (note.isNotEmpty()) Text(note)
        OutlinedTextField(draft, { draft = it }, modifier = Modifier.fillMaxWidth(), label = { Text("说点什么") })
        Button(onClick = {
            val text = draft.trim()
            if (text.isEmpty()) return@Button
            val conversation = current ?: store.newConversation().also { currentId = it.id }
            val hit = try {
                engine.route(text)
            } catch (ex: Throwable) {
                RouteHit(null, false, ex.message ?: "route", 0.0)
            }
            val expert = if (hit.fired) hit.expert else null
            val answer = try {
                engine.answer(text, expert, ngl = if (File(store.root, "use_gpu").exists()) 99 else 0)
            } catch (ex: Throwable) {
                "生成失败: ${ex.message}"
            }
            val now = Instant.now().toString()
            val messages = conversation.messages +
                ChatMessage("user", text) +
                ChatMessage("assistant", answer, expert, hit.reason)
            val title = if (conversation.messages.isEmpty()) text.take(18) else conversation.title
            store.saveConversation(conversation.copy(title = title, updated = now, messages = messages))
            draft = ""
            note = "路由 ${hit.reason} sim=${"%.3f".format(hit.sim)}"
            refresh()
        }) { Text("发送") }
        Text("已有对话", modifier = Modifier.padding(top = 8.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(conversations) { item ->
                Button(onClick = { currentId = item.id; refresh() }, modifier = Modifier.fillMaxWidth()) {
                    Text(item.title)
                }
            }
        }
    }
}

@Composable
private fun ColumnScope.ReviewTab(
    store: MemoryStore,
    tick: Int,
    refresh: () -> Unit,
    onTrain: (Boolean) -> Unit,
    onCancel: () -> Unit,
) {
    val conversations = remember(tick) { store.listConversations() }
    val selected = remember { mutableStateOf(setOf<String>()) }
    var entity by remember { mutableStateOf("") }
    var statement by remember { mutableStateOf("") }
    var value by remember { mutableStateOf("") }
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var force by remember { mutableStateOf(false) }
    val status = File(store.trainDir, "status.json").takeIf { it.exists() }?.readText() ?: ""
    Column(Modifier.weight(1f).fillMaxWidth()) {
        Text("勾选要整理的对话,改成一条事实后再训练。训练默认等充电;学习率 2e-5,因为 1e-4 在 Q8 全词表 loss 上会发散。")
        LazyColumn(Modifier.weight(1f, fill = false)) {
            items(conversations) { item ->
                Row {
                    Checkbox(
                        checked = item.id in selected.value,
                        onCheckedChange = { on ->
                            selected.value = if (on) selected.value + item.id else selected.value - item.id
                            val conv = store.loadConversation(item.id)
                            val lastUser = conv?.messages?.lastOrNull { it.role == "user" }?.content.orEmpty()
                            val lastAsst = conv?.messages?.lastOrNull { it.role == "assistant" }?.content.orEmpty()
                            if (statement.isBlank()) statement = lastUser
                            if (question.isBlank()) question = lastUser
                            if (answer.isBlank()) answer = lastAsst
                        },
                    )
                    Text(item.title, modifier = Modifier.padding(top = 12.dp))
                }
            }
        }
        OutlinedTextField(entity, { entity = it }, label = { Text("实体") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(statement, { statement = it }, label = { Text("陈述句") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value, { value = it }, label = { Text("答案") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(question, { question = it }, label = { Text("问句") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(answer, { answer = it }, label = { Text("问句的答") }, modifier = Modifier.fillMaxWidth())
        Row {
            Checkbox(force, { force = it })
            Text("立即训练(不等充电、不等熄屏)", modifier = Modifier.padding(top = 12.dp))
        }
        Button(onClick = {
            if (entity.isBlank() || statement.isBlank() || value.isBlank()) return@Button
            val qa = if (question.isBlank()) emptyList() else listOf(question to (answer.ifBlank { value }))
            val fact = ReviewedFact(entity.trim(), statement.trim(), value.trim(), qa, selected.value.toList())
            val name = "expert_" + System.currentTimeMillis().toString().takeLast(6)
            TrainService.writeJob(store, name, listOf(fact), force)
            onTrain(force)
            refresh()
        }) { Text("确认并训练") }
        Button(onClick = onCancel) { Text("取消训练") }
        if (status.isNotEmpty()) Text(status)
    }
}

@Composable
private fun ColumnScope.ExpertTab(store: MemoryStore, engine: Engine, tick: Int, refresh: () -> Unit) {
    val experts = remember(tick) { store.listExperts() }
    var note by remember { mutableStateOf("") }
    Column(Modifier.weight(1f).fillMaxWidth()) {
        Button(onClick = {
            note = try {
                engine.selfCheck()
            } catch (ex: Throwable) {
                "自检失败: ${ex.message}"
            }
        }) { Text("路由自检") }
        Button(onClick = {
            note = try {
                engine.importExternal()
                refresh()
                "已从 import 导入专家"
            } catch (ex: Throwable) {
                "导入失败: ${ex.message}"
            }
        }) { Text("导入已推送的专家") }
        Button(onClick = {
            val gpu = File(store.root, "use_gpu")
            if (gpu.exists()) gpu.delete() else gpu.writeText("1")
            note = if (gpu.exists()) "推理和训练改用 Vulkan (ngl 99)" else "推理和训练改用 CPU"
        }) { Text("切换 CPU / GPU") }
        if (note.isNotEmpty()) Text(note)
        Text("模型目录 ${engine.modelsDir().absolutePath}")
        LazyColumn {
            items(experts) { expert ->
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                    Text("${expert.expert}  ${expert.nFacts} 条", modifier = Modifier.weight(1f))
                    Button(onClick = {
                        store.deleteExpert(expert.expert)
                        try {
                            engine.rebuildIndex()
                        } catch (_: Throwable) {
                        }
                        refresh()
                    }) { Text("删除") }
                }
            }
        }
    }
}

@Suppress("unused")
private fun statusState(raw: String): String = try {
    JSONObject(raw).optString("state")
} catch (_: Throwable) {
    ""
}
