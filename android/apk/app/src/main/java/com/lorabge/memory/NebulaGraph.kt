package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

/**
 * 把手机上的 fact_memory / 对话收成桌面星云同一份 JSON。
 * 画面上只用实体拼出来的名字,不出现 expert_0 这种内部编号。
 */
internal object NebulaGraph {
    private val expertId = Regex("expert_\\d+")

    fun displayName(entities: List<String>, lang: String): String {
        val names = entities.map { it.trim() }.filter { it.isNotEmpty() && !expertId.matches(it) }.distinct()
        if (names.isEmpty()) return if (lang == "en") "Memory" else "记忆"
        if (names.all { isSelfEntity(it) }) return if (lang == "en") "About you" else "关于你"
        val head = names.take(2).joinToString(if (lang == "en") ", " else "、")
        if (names.size <= 2) return head
        return if (lang == "en") "$head…" else "${head}等"
    }

    fun readFacts(dir: File): List<JSONObject> {
        val memory = File(dir, "fact_memory.json")
        if (memory.exists()) {
            val text = memory.readText().trim()
            if (text.startsWith("[")) return arrayOf(JSONArray(text))
            if (text.startsWith("{")) {
                val obj = JSONObject(text)
                val facts = obj.optJSONArray("facts")
                if (facts != null) return arrayOf(facts)
                val keys = obj.optJSONArray("key_texts")
                if (keys != null) return statements(keys)
            }
        }
        val keys = File(dir, "key_texts.json")
        if (keys.exists()) {
            val text = keys.readText().trim()
            if (text.startsWith("[")) return statements(JSONArray(text))
        }
        return emptyList()
    }

    fun build(store: MemoryStore, lang: String, freshExpert: String? = null): String {
        val fresh = if (freshExpert.isNullOrBlank()) emptySet() else setOf(freshExpert)
        return document(store, lang, fresh).toString()
    }

    fun build(store: MemoryStore, lang: String, freshExperts: Set<String>): String {
        return document(store, lang, freshExperts).toString()
    }

    /** 这一次打开应用后才巩固出来的专家。导入的专家不写这个文件。 */
    fun sessionNew(store: MemoryStore): Set<String> {
        val file = File(store.trainDir, "session-new.txt")
        if (!file.exists()) return emptySet()
        return file.readLines().map { it.trim() }.filter { it.isNotEmpty() }.toSet()
    }

    fun rememberSession(store: MemoryStore, expert: String) {
        if (expert.isBlank()) return
        val file = File(store.trainDir, "session-new.txt")
        file.parentFile?.mkdirs()
        val names = sessionNew(store).toMutableSet()
        if (!names.add(expert)) return
        file.writeText(names.joinToString("\n") + "\n")
    }

    fun recall(store: MemoryStore, lang: String, expert: String?, fired: Boolean, sim: Double, query: String): String {
        val doc = document(store, lang, emptySet())
        val facts = doc.getJSONArray("facts")
        val matched = JSONArray()
        val mounted = fired && !expert.isNullOrBlank()
        if (mounted) {
            for (i in 0 until facts.length()) {
                val fact = facts.getJSONObject(i)
                if (fact.optString("expert") != expert) continue
                val entity = fact.optString("entity")
                if (entity.isNotBlank() && query.contains(entity)) {
                    val node = JSONObject().put("node_id", fact.getString("id"))
                    if (sim > 0.0) node.put("score", sim)
                    matched.put(node)
                }
            }
        }
        val label = doc.getJSONArray("experts").let { experts ->
            var found = ""
            for (i in 0 until experts.length()) {
                val item = experts.getJSONObject(i)
                if (item.optString("name") == expert) found = item.optString("display_name")
            }
            found.ifBlank { if (lang == "en") "Memory" else "记忆" }
        }
        val banner = if (!mounted) {
            ""
        } else {
            val score = if (sim > 0.0) {
                val num = String.format(Locale.US, "%.2f", sim)
                if (lang == "en") " · similarity $num" else " · 相似度 $num"
            } else {
                ""
            }
            if (lang == "en") "Recall $label$score" else "回忆 $label$score"
        }
        return JSONObject()
            .put("mounted", mounted)
            .put("mounted_expert", expert ?: "")
            .put("matched_facts", matched)
            .put("banner", banner)
            .toString()
    }

    private fun document(store: MemoryStore, lang: String, freshExperts: Set<String>): JSONObject {
        val expertsOut = JSONArray()
        val factsOut = JSONArray()
        val links = JSONArray()
        val conversations = store.listConversations()
        val includedConversations = LinkedHashMap<String, Conversation>()
        val entityExperts = LinkedHashMap<String, LinkedHashSet<String>>()
        store.listExperts().forEach { record ->
            val rawFacts = readFacts(File(store.expertsDir, record.expert))
            val entities = rawFacts.map { it.optString("entity") }
            val label = displayName(entities, lang)
            val fresh = freshExperts.contains(record.expert)
            expertsOut.put(
                JSONObject()
                    .put("id", "expert:${record.expert}")
                    .put("name", record.expert)
                    .put("display_name", label)
                    .put("writable", true)
                    .put("explicit", fresh),
            )
            rawFacts.forEachIndexed { index, raw ->
                val id = "fact:${record.expert}:$index"
                val entity = raw.optString("entity")
                val conversation = matchConversation(conversations, raw)
                val fact = JSONObject()
                    .put("id", id)
                    .put("fact_id", id)
                    .put("expert", record.expert)
                    .put("expert_label", label)
                    .put("statement", raw.optString("statement"))
                    .put("entity", entity)
                    .put("attr", raw.optString("attr"))
                    .put("value", raw.optString("value"))
                    .put("question", firstQuestion(raw))
                    .put("superseded", raw.optBoolean("superseded"))
                    .put("snippets", JSONArray())
                    .put("recall_hits", 0)
                if (raw.has("gate_score") && !raw.isNull("gate_score")) {
                    fact.put("gate_score", raw.optDouble("gate_score"))
                } else if (raw.has("score") && !raw.isNull("score")) {
                    fact.put("gate_score", raw.optDouble("score"))
                }
                if (conversation != null) {
                    fact.put("conversation_id", conversation.id)
                    fact.put("source_title", conversationTitle(conversation))
                    includedConversations[conversation.id] = conversation
                    links.put(
                        JSONObject()
                            .put("source", id)
                            .put("target", "conv:${conversation.id}")
                            .put("kind", "source"),
                    )
                }
                factsOut.put(fact)
                if (entity.isNotBlank() && !expertId.matches(entity)) {
                    entityExperts.getOrPut(entity) { LinkedHashSet() }.add(record.expert)
                }
            }
        }
        entityExperts.values.forEach { names ->
            if (names.size < 2) return@forEach
            val ids = names.map { "expert:$it" }
            for (i in 1 until minOf(ids.size, 4)) {
                links.put(
                    JSONObject()
                        .put("source", ids[0])
                        .put("target", ids[i])
                        .put("kind", "entity"),
                )
            }
        }
        val convOut = JSONArray()
        includedConversations.values.forEach { conversation ->
            val snippet = conversation.messages.firstOrNull { it.role == "user" }?.content.orEmpty().take(48)
            convOut.put(
                JSONObject()
                    .put("id", "conv:${conversation.id}")
                    .put("conversation_id", conversation.id)
                    .put("title", conversationTitle(conversation))
                    .put("snippet", snippet),
            )
        }
        return JSONObject()
            .put("experts", expertsOut)
            .put("facts", factsOut)
            .put("conversations", convOut)
            .put("links", links)
    }

    private fun conversationTitle(conversation: Conversation): String {
        val title = conversation.title.trim()
        if (title.isNotEmpty() && title != "新对话") return title
        val first = conversation.messages.firstOrNull { it.role == "user" }?.content?.trim().orEmpty()
        if (first.isNotEmpty()) return first.take(18)
        return title.ifBlank { "对话" }
    }

    private fun matchConversation(conversations: List<Conversation>, fact: JSONObject): Conversation? {
        val sources = fact.optJSONArray("sources")
        if (sources != null) {
            for (i in 0 until sources.length()) {
                val id = sources.optString(i)
                val found = conversations.firstOrNull { it.id == id }
                if (found != null) return found
            }
        }
        val entity = fact.optString("entity")
        val statement = fact.optString("statement")
        return conversations.firstOrNull { conversation ->
            conversation.messages.any { message ->
                (entity.length >= 2 && entity in message.content) ||
                    (statement.length >= 6 && statement in message.content)
            }
        }
    }

    private fun firstQuestion(fact: JSONObject): String {
        val questions = fact.optJSONArray("questions") ?: return fact.optString("question")
        return if (questions.length() == 0) "" else questions.optString(0)
    }

    private fun arrayOf(array: JSONArray): List<JSONObject> {
        val out = ArrayList<JSONObject>(array.length())
        for (i in 0 until array.length()) {
            val item = array.opt(i)
            if (item is JSONObject) out.add(item)
        }
        return out
    }

    private fun statements(keys: JSONArray): List<JSONObject> {
        val out = ArrayList<JSONObject>()
        for (i in 0 until keys.length()) {
            val text = keys.optString(i).trim()
            if (!text.endsWith("。") && !text.endsWith(".")) continue
            out.add(JSONObject().put("statement", text).put("entity", "").put("value", text))
        }
        return out
    }
}

internal fun backendLine(lang: String, record: BackendRecord, baseReady: Boolean, bgeReady: Boolean): String {
    val where = DeviceTune.label(record, lang)
    val base = if (baseReady) skyText(lang, "baseReady") else skyText(lang, "baseMissing")
    val bge = if (bgeReady) skyText(lang, "bgeReady") else skyText(lang, "bgeMissing")
    val why = when (record.reason) {
        "mali_unproven" -> skyText(lang, "maliUnproven")
        "matched_faster" -> skyText(lang, "matchedFaster")
        "matched" -> skyText(lang, "matched")
        "no_vulkan" -> skyText(lang, "noVulkan")
        "native_crash", "chat_exit", "embed_exit", "speed_exit" -> skyText(lang, "nativeCrash")
        "chat_timeout", "embed_timeout" -> skyText(lang, "gpuTimeout")
        else -> when (record.mode) {
            "cpu" -> skyText(lang, "usingCpu")
            "gpu" -> skyText(lang, "usingGpu")
            else -> if (record.checking) skyText(lang, "checkingGpu") else ""
        }
    }
    return listOf("$base · $bge · $where", why).filter { it.isNotBlank() }.joinToString("\n")
}

internal fun presentTrainStatus(lang: String, raw: String): String {
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) return ""
    val obj = runCatching { JSONObject(trimmed) }.getOrNull()
        ?: return if (trimmed.startsWith("{")) "" else trimmed
    val head = when (obj.optString("state")) {
        "running" -> skyText(lang, "consolidating")
        "done" -> if (lang == "en") "Finished" else "已完成"
        "cancelled", "canceled" -> if (lang == "en") "Cancelled" else "已取消"
        "error" -> if (lang == "en") "Failed" else "失败"
        else -> ""
    }
    val detail = obj.optString("detail").trim()
    // Trainer stdout ("[micro 6/8] step 3/8") is a second counter. The progress line already shows it.
    val extra = if (
        detail.isBlank() ||
        detail.contains("expert_") ||
        detail.contains("Exception") ||
        detail.startsWith("[")
    ) {
        ""
    } else {
        detail
    }
    return listOf(head, extra).filter { it.isNotBlank() }.joinToString(" · ")
}
