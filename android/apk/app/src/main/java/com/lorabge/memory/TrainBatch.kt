package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

internal data class SavedBatch(
    val groups: List<List<String>>,
    val index: Int,
    val phase: String,
)

internal fun planTrainGroups(facts: List<ReviewedFact>): List<List<ReviewedFact>> {
    val self = facts.filter { isSelfEntity(it.entity) }
    val others = facts.filter { !isSelfEntity(it.entity) }
    val out = ArrayList<List<ReviewedFact>>()
    if (self.isNotEmpty()) out.add(self)
    val grouped = LinkedHashMap<String, MutableList<ReviewedFact>>()
    for (fact in others) {
        grouped.getOrPut(fact.entity.trim()) { ArrayList() }.add(fact)
    }
    grouped.values.forEach { out.add(it.toList()) }
    return out
}

/** Items already in the batch stay put. A new one waits in a later group, so the running job is not rewritten. */
internal fun enqueueStatement(batch: SavedBatch, statement: String): SavedBatch {
    val key = statement.trim()
    if (key.isEmpty() || batch.groups.any { group -> group.any { it.trim() == key } }) return batch
    return batch.copy(groups = batch.groups + listOf(listOf(key)))
}

internal fun batchMarks(batch: SavedBatch, trainState: String): List<Pair<String, String>> {
    val failed = batch.phase == "error" || trainState == "error"
    val out = ArrayList<Pair<String, String>>()
    batch.groups.forEachIndexed { index, statements ->
        val mark = when {
            batch.phase == "done" || index < batch.index -> "done"
            index == batch.index && failed -> "error"
            index == batch.index -> "running"
            else -> "queued"
        }
        statements.forEach { out.add(it to mark) }
    }
    return out
}

internal object TrainBatchStore {
    private fun file(store: MemoryStore) = File(store.trainDir, "batch.json")

    fun read(store: MemoryStore): SavedBatch? {
        val file = file(store)
        if (!file.exists()) return null
        return runCatching { parse(file.readText()) }.getOrNull()
    }

    fun write(store: MemoryStore, batch: SavedBatch) {
        store.ensure()
        file(store).writeText(format(batch))
    }

    fun clear(store: MemoryStore) {
        file(store).delete()
    }

    fun parse(text: String): SavedBatch? {
        if (text.isBlank()) return null
        val obj = JSONObject(text)
        val groupsJson = obj.optJSONArray("groups") ?: return null
        val groups = ArrayList<List<String>>()
        for (i in 0 until groupsJson.length()) {
            val row = groupsJson.optJSONArray(i) ?: continue
            val statements = ArrayList<String>()
            for (j in 0 until row.length()) {
                val line = row.optString(j).trim()
                if (line.isNotEmpty()) statements.add(line)
            }
            if (statements.isNotEmpty()) groups.add(statements)
        }
        if (groups.isEmpty()) return null
        val index = obj.optInt("index").coerceIn(0, groups.lastIndex)
        val phase = obj.optString("phase").ifBlank { "running" }
        return SavedBatch(groups, index, phase)
    }

    fun format(batch: SavedBatch): String {
        val groups = JSONArray()
        for (group in batch.groups) {
            val row = JSONArray()
            group.forEach { row.put(it) }
            groups.put(row)
        }
        return JSONObject()
            .put("groups", groups)
            .put("index", batch.index)
            .put("phase", batch.phase)
            .toString()
    }
}
