package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.time.Instant
import java.util.UUID

/**
 * 和仓库、桌面端共用的记忆目录。权重在手机上是 GGUF 和 float32 向量,
 * 事实、路由表、key_texts 的 JSON 字段和 experts/ 一致。
 * 见 docs/client_store.md。
 */
class MemoryStore(val root: File) {
    val conversationsDir = File(root, "conversations")
    val expertsDir = File(root, "experts")
    val indexDir = File(root, "index")
    val trainDir = File(root, "train")

    fun ensure() {
        conversationsDir.mkdirs()
        expertsDir.mkdirs()
        indexDir.mkdirs()
        trainDir.mkdirs()
        val gate = File(expertsDir, "fact_gate.json")
        if (!gate.exists()) {
            gate.writeText(
                """
                {"tau":0.622,"mask":"某","value_mask":"某值","use_paraphrases":false,"use_reranker":false}
                """.trimIndent(),
            )
        }
    }

    fun listConversations(): List<Conversation> {
        ensure()
        return conversationsDir.listFiles { f -> f.extension == "json" }
            ?.mapNotNull { file ->
                Conversation.fromJson(file.readText()).takeIf { it.id.isNotBlank() }
            }
            ?.sortedByDescending { it.updated }
            ?: emptyList()
    }

    fun loadConversation(id: String): Conversation? {
        val file = File(conversationsDir, "$id.json")
        if (!file.exists()) return null
        val parsed = Conversation.fromJson(file.readText())
        if (parsed.id.isBlank()) return null
        return parsed
    }

    fun saveConversation(conversation: Conversation) {
        ensure()
        val dest = File(conversationsDir, "${conversation.id}.json")
        // writeText 会先把原文件截成空。回复线程正在写、界面又按 tick 重读时，
        // JSONObject("") 会把 PhoneApp 打崩。先写临时文件，再原子换上。
        val tmp = File(conversationsDir, "${conversation.id}.${System.nanoTime()}.tmp")
        tmp.writeText(conversation.toJson())
        try {
            Files.move(
                tmp.toPath(),
                dest.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(tmp.toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }

    fun newConversation(): Conversation {
        val now = Instant.now().toString()
        val conversation = Conversation(
            id = "c-" + UUID.randomUUID().toString().take(8),
            title = "新对话",
            created = now,
            updated = now,
            messages = emptyList(),
        )
        saveConversation(conversation)
        return conversation
    }

    fun listExperts(): List<ExpertRecord> {
        ensure()
        val router = File(expertsDir, "router.jsonl")
        if (!router.exists()) return emptyList()
        return router.readLines().filter { it.isNotBlank() }.map { ExpertRecord.fromJson(it) }
    }

    fun deleteExpert(name: String) {
        val kept = listExperts().filter { it.expert != name }
        writeRouter(kept)
        File(expertsDir, name).deleteRecursively()
    }

    fun writeRouter(experts: List<ExpertRecord>) {
        ensure()
        File(expertsDir, "router.jsonl").writeText(
            experts.joinToString("\n") { it.toJson() } + if (experts.isEmpty()) "" else "\n",
        )
    }

    fun registerExpert(record: ExpertRecord, facts: List<ReviewedFact>) {
        val dir = File(expertsDir, record.expert)
        dir.mkdirs()
        File(dir, "fact_memory.json").writeText(factsToFactMemory(facts))
        File(dir, "key_texts.json").writeText(JSONArray(keyTexts(facts)).toString())
        File(dir, "adapter_config.json").writeText(
            JSONObject()
                .put("peft_type", "LORA")
                .put("r", record.rank)
                .put("lora_alpha", record.rank * 2)
                .put("target_modules", JSONArray(listOf("gate_proj", "up_proj", "down_proj")))
                .put("base_model_name_or_path", "Qwen2.5-0.5B-Instruct")
                .put("weight_file", "adapter.gguf")
                .put("weight_format", "gguf-lora")
                .toString(),
        )
        val all = listExperts().filter { it.expert != record.expert } + record
        writeRouter(all.sortedBy { it.batch })
        if (record.expert == SELF_EXPERT) retireOtherSelfExperts()
    }

    fun readReviewedFacts(expert: String): List<ReviewedFact> {
        val file = File(expertsDir, "$expert/fact_memory.json")
        if (!file.exists()) return emptyList()
        val text = file.readText().trim()
        if (!text.startsWith("[")) return emptyList()
        val arr = JSONArray(text)
        val out = ArrayList<ReviewedFact>()
        for (i in 0 until arr.length()) {
            val row = arr.optJSONObject(i) ?: continue
            val questions = row.optJSONArray("questions")
            val qa = ArrayList<Pair<String, String>>()
            if (questions != null) {
                for (j in 0 until questions.length()) {
                    val question = questions.optString(j)
                    if (question.isNotBlank()) qa.add(question to row.optString("value"))
                }
            }
            val gatesArr = row.optJSONArray("gate_questions")
            val gates = ArrayList<String>()
            if (gatesArr != null) {
                for (j in 0 until gatesArr.length()) gates.add(gatesArr.optString(j))
            }
            out.add(
                ReviewedFact(
                    entity = row.optString("entity"),
                    statement = row.optString("statement"),
                    value = row.optString("value"),
                    qa = qa,
                    sources = emptyList(),
                    attr = row.optString("attr"),
                    gateQuestions = gates,
                ),
            )
        }
        return out
    }

    fun expertNameFor(facts: List<ReviewedFact>, generated: String): String {
        val owned = facts.mapNotNull { possessedName(it) }.distinct()
        if (facts.isNotEmpty() && owned.size == 1 && facts.all { possessedName(it) == owned[0] }) {
            return stableExpertId(owned[0])
        }
        if (facts.isNotEmpty() && facts.all { isAboutYou(it) }) return SELF_EXPERT
        return generated
    }

    fun factsForTrain(incoming: List<ReviewedFact>): List<ReviewedFact> {
        if (incoming.isEmpty() || incoming.any { !isAboutYou(it) }) return incoming
        val merged = LinkedHashMap<String, ReviewedFact>()
        listExperts().forEach { record ->
            val stored = readReviewedFacts(record.expert).filter { isAboutYou(it) }
            if (stored.isEmpty()) return@forEach
            stored.forEach { fact ->
                val key = fact.statement.trim()
                if (key.isNotEmpty()) merged.putIfAbsent(key, fact)
            }
        }
        incoming.forEach { fact ->
            val key = fact.statement.trim()
            if (key.isNotEmpty()) merged[key] = fact
        }
        return merged.values.toList()
    }

    /**
     * Facts such as "我的猫叫咪咪" that were stored on the about-you expert
     * become their own node. The name and the original sentence stay, so
     * "我的猫是什么" still answers 咪咪.
     */
    fun migratePossessedEntities(): Boolean {
        var changed = false
        val records = listExperts()
        for (record in records) {
            val facts = readReviewedFacts(record.expert)
            val owned = facts.filter { isSelfEntity(it.entity) && possessedName(it) != null }
            if (owned.isEmpty()) continue
            val keep = facts.filter { it !in owned }
            owned.groupBy { possessedName(it)!! }.forEach { (name, rows) ->
                val lifted = rows.map { fact ->
                    fact.copy(
                        entity = name,
                        attr = if (fact.attr.contains("猫") || fact.statement.contains("猫")) "宠物" else fact.attr.ifBlank { "关系" },
                    )
                }
                val id = stableExpertId(name)
                val existing = readReviewedFacts(id)
                val merged = (existing + lifted).distinctBy { it.statement.trim() }
                val batchNo = listExperts().firstOrNull { it.expert == id }?.batch
                    ?: ((listExperts().maxOfOrNull { it.batch } ?: -1) + 1)
                val rank = listExperts().firstOrNull { it.expert == id }?.rank ?: record.rank
                registerExpert(
                    ExpertRecord(id, batchNo, merged.size, rank, "experts/$id/router_key.f32", "experts/$id/adapter.gguf"),
                    merged,
                )
                val src = File(expertsDir, "${record.expert}/adapter.gguf")
                val dest = File(expertsDir, "$id/adapter.gguf")
                if (src.exists() && !dest.exists()) src.copyTo(dest)
            }
            if (keep.isEmpty()) {
                if (record.expert != stableExpertId(possessedName(owned.first()) ?: "")) deleteExpert(record.expert)
            } else {
                registerExpert(record.copy(nFacts = keep.size), keep)
            }
            changed = true
        }
        return changed
    }

    fun retireOtherSelfExperts() {
        val names = listExperts().map { it.expert }
        names.forEach { name ->
            if (name == SELF_EXPERT) return@forEach
            val stored = readReviewedFacts(name)
            if (stored.isNotEmpty() && stored.all { isSelfEntity(it.entity) }) deleteExpert(name)
        }
    }

    companion object {
        fun tailCount(n: Int): Int {
            // QVAC b7349 把最后约 5% 划成验证,没有开关。多复制几条到末尾,让每条原始样本都进训练。
            var k = 0
            while (kotlin.math.floor((n + k) * 0.95).toInt() < n) k++
            return k + 2
        }

        fun trainingJsonl(facts: List<ReviewedFact>): String {
            // 和 C++ 训练程序、桌面 AssistantDataset 一样:先请模型说出事实,再训确认过的问句。
            // 问句收尾在 tokenize 时加「请简短回答。」。
            val rows = ArrayList<String>()
            for (raw in facts) {
                if (!FactExpand.keepForTraining(raw)) continue
                val fact = FactExpand.expand(raw)
                val instruction = if (FactExpand.hasCjk(fact.statement)) "请说出这条事实。" else "State this fact."
                rows.add(chatRow(instruction, fact.statement))
                for ((q, a) in fact.qa) rows.add(chatRow(q, a))
            }
            if (rows.isEmpty()) return ""
            val k = tailCount(rows.size)
            return (rows + rows.take(k)).joinToString("\n") + "\n"
        }

        private fun chatRow(user: String, assistant: String): String {
            val cjk = FactExpand.hasCjk(user)
            val system = if (cjk) "你是助手。" else "You are a helpful assistant."
            val brief = if (cjk) {
                if (user.trimEnd().endsWith("请简短回答。")) user.trimEnd() else user.trimEnd() + " 请简短回答。"
            } else {
                if (user.trimEnd().endsWith("Answer briefly.")) user.trimEnd() else user.trimEnd() + " Answer briefly."
            }
            val messages = JSONArray()
                .put(JSONObject().put("role", "system").put("content", system))
                .put(JSONObject().put("role", "user").put("content", brief))
                .put(JSONObject().put("role", "assistant").put("content", assistant))
            return JSONObject().put("messages", messages).toString()
        }

        fun keyTexts(facts: List<ReviewedFact>): List<String> {
            val out = ArrayList<String>()
            for (fact in facts) {
                out.add(fact.statement)
                out.addAll(fact.qa.map { it.first })
            }
            return out
        }

        fun factsToFactMemory(facts: List<ReviewedFact>): String {
            val arr = JSONArray()
            for (fact in facts) {
                arr.put(
                    JSONObject()
                        .put("entity", fact.entity)
                        .put("value", fact.value)
                        .put("statement", fact.statement)
                        .put("questions", JSONArray(fact.qa.map { it.first }))
                        .apply {
                            if (fact.attr.isNotEmpty()) put("attr", fact.attr)
                            if (fact.gateQuestions.isNotEmpty()) put("gate_questions", JSONArray(fact.gateQuestions))
                        },
                )
            }
            return arr.toString(2)
        }
    }
}

data class ChatMessage(
    val role: String,
    val content: String,
    val expert: String? = null,
    val reason: String? = null,
    val noticed: Boolean = false,
)

data class Conversation(
    val id: String,
    val title: String,
    val created: String,
    val updated: String,
    val messages: List<ChatMessage>,
) {
    fun toJson(): String {
        val arr = JSONArray()
        for (message in messages) {
            val obj = JSONObject().put("role", message.role).put("content", message.content)
            if (message.expert != null) obj.put("expert", message.expert)
            if (message.reason != null) obj.put("reason", message.reason)
            if (message.noticed) obj.put("noticed", true)
            arr.put(obj)
        }
        return JSONObject()
            .put("id", id)
            .put("title", title)
            .put("created", created)
            .put("updated", updated)
            .put("messages", arr)
            .toString(2)
    }

    companion object {
        fun fromJson(text: String): Conversation {
            val trimmed = text.trim()
            if (trimmed.isEmpty()) return blank()
            return try {
                parse(trimmed)
            } catch (_: Throwable) {
                blank()
            }
        }

        private fun blank() = Conversation(id = "", title = "", created = "", updated = "", messages = emptyList())

        private fun parse(text: String): Conversation {
            val obj = JSONObject(text)
            val messages = obj.getJSONArray("messages")
            val list = ArrayList<ChatMessage>()
            for (i in 0 until messages.length()) {
                val m = messages.getJSONObject(i)
                list.add(
                    ChatMessage(
                        role = m.getString("role"),
                        content = m.getString("content"),
                        expert = m.optString("expert").ifBlank { null },
                        reason = m.optString("reason").ifBlank { null },
                        noticed = m.optBoolean("noticed"),
                    ),
                )
            }
            return Conversation(
                id = obj.getString("id"),
                title = obj.optString("title", "对话"),
                created = obj.optString("created"),
                updated = obj.optString("updated"),
                messages = list,
            )
        }
    }
}

data class ExpertRecord(
    val expert: String,
    val batch: Int,
    val nFacts: Int,
    val rank: Int,
    val keyPath: String,
    val weight: String,
) {
    fun toJson(): String = JSONObject()
        .put("expert", expert)
        .put("batch", batch)
        .put("n_facts", nFacts)
        .put("rank", rank)
        .put("key_path", keyPath)
        .put("weight", weight)
        .put("key_format", "float32")
        .put("dim", 512)
        .toString()

    companion object {
        fun fromJson(line: String): ExpertRecord {
            val obj = JSONObject(line)
            return ExpertRecord(
                expert = obj.getString("expert"),
                batch = obj.optInt("batch"),
                nFacts = obj.optInt("n_facts"),
                rank = obj.optInt("rank", 32),
                keyPath = obj.optString("key_path"),
                weight = obj.optString("weight", "adapter.gguf"),
            )
        }
    }
}

data class ReviewedFact(
    val entity: String,
    val statement: String,
    val value: String,
    val qa: List<Pair<String, String>>,
    val sources: List<String>,
    val attr: String = "",
    val gateQuestions: List<String> = emptyList(),
    val selected: Boolean = true,
    val gate: String = "",
)

internal const val SELF_EXPERT = "expert_self"

internal fun isSelfEntity(entity: String) = entity.trim() == "我"

/**
 * A pet, person, or other thing named in the user's words ("我的猫叫咪咪")
 * is its own entity. The value is the name. Facts about the user stay on 我.
 */
internal fun possessedName(entity: String, attr: String, statement: String, value: String): String? {
    val stmt = statement.trim().trimEnd('。', '.', '！', '!', ' ')
    if (!isSelfEntity(entity)) {
        if (stmt.startsWith("我的") && entity.isNotBlank()) return entity.trim()
        return null
    }
    if (attr.contains("猫") || stmt.contains("我的猫")) {
        val named = value.trim().trimEnd('。', '.', '！', '!').ifBlank {
            Regex("叫(.+)$").find(stmt)?.groupValues?.get(1)?.trim().orEmpty()
        }
        if (named.isNotEmpty() && named != "我") return named
    }
    val mine = Regex("^我的(.+?)叫(.+)$").find(stmt) ?: return null
    val named = mine.groupValues[2].trim().trimEnd('。', '.', '！', '!')
    if (named.isEmpty() || named == "我") return null
    return named
}

internal fun possessedName(fact: ReviewedFact): String? =
    possessedName(fact.entity, fact.attr, fact.statement, fact.value)

internal fun isAboutYou(fact: ReviewedFact): Boolean = isSelfEntity(fact.entity) && possessedName(fact) == null

internal fun stableExpertId(entity: String): String {
    var hash = 2166136261u
    entity.trim().forEach { ch ->
        hash = hash xor ch.code.toUInt()
        hash *= 16777619u
    }
    return "expert_${hash.toString(16)}"
}
