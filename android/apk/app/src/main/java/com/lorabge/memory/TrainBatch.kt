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

/** Shown when a start was not asked to run now, so the service is still behind the charge gate. */
internal const val TRAIN_WAITING_DETAIL = "要等充电并且屏幕关闭。点「现在训练」会立刻开始。"

/**
 * A batch left at `running` while the service is not training.
 * Opening the page clears it so 全部训练 can start again.
 * A real `running` job and a failed job (so the row can say 失败) stay.
 */
internal fun shouldRecoverBatch(batch: SavedBatch?, trainState: String): Boolean {
    if (batch == null || batch.phase != "running") return false
    return trainState == "waiting" || trainState.isBlank() || trainState == "cancelled"
}

/** The old confirm button is a dead tap while a row is queued, running, or waiting on the charger. */
internal fun confirmTrainShown(training: Boolean, trainState: String, marks: List<String>): Boolean {
    if (training || trainState == "running") return false
    if (marks.any { it == "running" || it == "queued" || it == "waiting" }) return false
    return trainState == "error"
}

/**
 * A completed run marks every item in the batch done, even if an earlier attempt
 * left phase=error. Otherwise a failure is only the group this attempt was on.
 */
internal fun batchMarks(batch: SavedBatch, trainState: String, succeeded: Boolean = false): List<Pair<String, String>> {
    val out = ArrayList<Pair<String, String>>()
    batch.groups.forEachIndexed { index, statements ->
        val mark = when {
            succeeded || batch.phase == "done" || index < batch.index -> "done"
            index > batch.index -> "queued"
            batch.phase == "error" || trainState == "error" -> "error"
            trainState == "waiting" -> "waiting"
            trainState == "running" && batch.phase == "running" -> "running"
            else -> "queued"
        }
        statements.forEach { out.add(it to mark) }
    }
    return out
}

/**
 * Move the batch to done only when every statement is actually stored on the expert.
 * Does not invent a separate expert for a value such as 咪咪; self facts stay together.
 */
internal fun reconcileSucceededBatch(batch: SavedBatch, registered: Set<String>): SavedBatch? {
    val lines = batch.groups.flatten().map { it.trim() }.filter { it.isNotEmpty() }
    if (lines.isEmpty() || lines.any { it !in registered }) return null
    val at = batch.groups.lastIndex
    if (batch.phase == "done" && batch.index == at) return null
    return batch.copy(phase = "done", index = at)
}

/**
 * A done run whose adapter is on disk should be registered and shown as 已完成.
 * Returns true when batch or expert state changed.
 */
internal fun migrateFinishedTrain(store: MemoryStore): Boolean {
    val trainDir = store.trainDir
    val jobFile = File(trainDir, "job.json")
    if (!jobFile.exists()) return false
    val job = runCatching { org.json.JSONObject(jobFile.readText()) }.getOrNull() ?: return false
    val expert = job.optString("expert").ifBlank { return false }
    val statusFile = File(trainDir, "status.json")
    val snap = parseTrainSnapshot(statusFile.takeIf { it.exists() }?.readText().orEmpty())
    if (!sealedTrain(trainDir, snap)) return false
    val factsJson = job.optJSONArray("facts") ?: return false
    val facts = ArrayList<ReviewedFact>()
    for (i in 0 until factsJson.length()) {
        val row = factsJson.optJSONObject(i) ?: continue
        facts.add(TrainService.factFromJson(row))
    }
    if (facts.isEmpty()) return false
    // Personal facts share expert_self. A cat's name is not its own expert.
    if (facts.all { isSelfEntity(it.entity) } && expert != SELF_EXPERT) return false
    var changed = false
    val registered = store.readReviewedFacts(expert).map { it.statement.trim() }.toSet()
    val wanted = facts.map { it.statement.trim() }.filter { it.isNotEmpty() }
    if (wanted.any { it !in registered }) {
        val dir = File(store.expertsDir, expert)
        dir.mkdirs()
        val adapter = trainAdapterFile(trainDir, expert)
        val dest = File(dir, "adapter.gguf")
        if (ggufIsValid(adapter) && !ggufIsValid(dest)) adapter.copyTo(dest, overwrite = true)
        val existing = store.listExperts().firstOrNull { it.expert == expert }
        val batchNo = existing?.batch ?: ((store.listExperts().maxOfOrNull { it.batch } ?: -1) + 1)
        store.registerExpert(
            ExpertRecord(
                expert = expert,
                batch = batchNo,
                nFacts = facts.size,
                rank = job.optInt("rank", 32),
                keyPath = "experts/$expert/router_key.f32",
                weight = "experts/$expert/adapter.gguf",
            ),
            facts,
        )
        changed = true
    }
    val now = store.readReviewedFacts(expert).map { it.statement.trim() }.toSet()
    val saved = TrainBatchStore.read(store)
    if (saved != null) {
        val settled = reconcileSucceededBatch(saved, now)
        if (settled != null) {
            TrainBatchStore.write(store, settled)
            changed = true
        }
    }
    if (snap.state != "done" && wanted.all { it in now }) {
        writeTextAtomic(
            statusFile,
            trainSnapshotJson(
                "done",
                "done",
                snap.step,
                snap.total,
                snap.epochs,
                snap.loss,
                snap.elapsedSec,
                "已登记 $expert",
                "",
                updated = java.time.Instant.now().toString(),
            ),
        )
        changed = true
    }
    return changed
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
