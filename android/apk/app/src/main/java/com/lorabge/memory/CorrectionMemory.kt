package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

enum class CorrectionStatus { Pending, Confirmed, Dismissed, Superseded }

data class ChatCorrection(
    val id: String,
    val conversationId: String,
    val fact: FactDraft,
    val status: CorrectionStatus = CorrectionStatus.Pending,
)

/** Corrections update structured recall immediately, without rewriting expert weights. */
internal class CorrectionMemory(root: File) {
    private val file = File(root, "corrections.json")

    fun read(): List<ChatCorrection> {
        if (!file.exists()) return emptyList()
        val rows = JSONArray(file.readText())
        return List(rows.length()) { i ->
            val row = rows.getJSONObject(i)
            val value = row.getString("value")
            ChatCorrection(
                row.getString("id"),
                row.getString("conversation"),
                FactDraft(row.getString("entity"), row.getString("attribute"), row.getString("statement"),
                    value, row.getString("question"), value),
                CorrectionStatus.valueOf(row.getString("status")),
            )
        }
    }

    fun propose(conversationId: String, fact: FactDraft): ChatCorrection {
        val card = ChatCorrection(UUID.randomUUID().toString(), conversationId, fact)
        save(read() + card)
        return card
    }

    fun resolve(conversationId: String, id: String, confirm: Boolean): Boolean {
        val rows = read()
        val at = rows.indexOfFirst { it.id == id && it.conversationId == conversationId && it.status == CorrectionStatus.Pending }
        if (at < 0) return false
        val slot = rows[at].fact.slot()
        save(rows.mapIndexed { index, row ->
            when {
                index == at -> row.copy(status = if (confirm) CorrectionStatus.Confirmed else CorrectionStatus.Dismissed)
                confirm && index < at && row.fact.slot() == slot &&
                    row.status in setOf(CorrectionStatus.Pending, CorrectionStatus.Confirmed) ->
                    row.copy(status = CorrectionStatus.Superseded)
                else -> row
            }
        })
        return true
    }

    fun overlay(facts: List<StoredFact>): List<StoredFact> {
        val current = read().filter { it.status == CorrectionStatus.Confirmed }.associateBy { it.fact.slot() }
        if (current.isEmpty()) return facts
        val replaced = facts.filterNot { it.slot() in current }
        return replaced + current.map { (key, row) ->
            val draft = row.fact
            val old = facts.firstOrNull { it.slot() == key }
            StoredFact(
                correctionExpert(row), draft.entity, draft.statement, draft.value,
                (listOf(draft.question) + old?.questions.orEmpty()).distinct(), draft.attr,
            )
        }
    }

    private fun save(rows: List<ChatCorrection>) {
        file.parentFile?.mkdirs()
        val tmp = File.createTempFile("corrections-", ".tmp", file.parentFile)
        try {
            val json = JSONArray()
            rows.forEach { row ->
                json.put(JSONObject()
                    .put("id", row.id).put("conversation", row.conversationId).put("status", row.status.name)
                    .put("entity", row.fact.entity).put("attribute", row.fact.attr).put("statement", row.fact.statement)
                    .put("value", row.fact.value).put("question", row.fact.question))
            }
            tmp.writeText(json.toString())
            try {
                Files.move(tmp.toPath(), file.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(tmp.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        } finally {
            tmp.delete()
        }
    }
}

private val correctionPrefix = Regex(
    """^(?:不对|记错了|更正|纠正|应该是|actually|correction)(?:[，,：:。！!]\s*|\s+|$)""",
    RegexOption.IGNORE_CASE,
)

internal fun isExplicitCorrection(text: String): Boolean =
    '?' !in text && '？' !in text && correctionPrefix.containsMatchIn(text.trim())

internal fun parseCorrection(text: String): FactDraft? {
    if (!isExplicitCorrection(text)) return null
    val body = text.trim().replaceFirst(correctionPrefix, "").trim()
    val fact = FactNotice.drafts(body).singleOrNull() ?: return null
    // Don't turn a loose assertion or a pronoun into an unrelated memory. Require a recognizable field.
    if (fact.attr == "是" || fact.entity in setOf("他", "她", "它", "我们", "你", "这", "那")) return null
    if (body.trimEnd('。', '.', '！', '!').any { it in "。；;！!\n，," }) return null
    return fact
}

/** Library displays confirmed facts separately from the trained expert snapshots. */
internal class CorrectionLibrary(rows: Collection<ChatCorrection>) {
    private val current = rows.filter { it.status == CorrectionStatus.Confirmed }.asReversed()
    private val slots = current.map { it.fact.slot() }.toSet()

    val statements: List<String> get() = current.map { it.fact.statement }

    fun isCurrentSnapshot(entity: String, statement: String, value: String = "", attr: String = "") =
        slots.isEmpty() || StoredFact("", entity, statement, value, attr = attr).slot() !in slots
}

private fun FactDraft.slot() = StoredFact("", entity, statement, value, attr = attr).slot()

private fun StoredFact.slot(): Pair<String, String> {
    // Prefer the normal fact parser for old rows that didn't include an attribute;
    // use the stored attribute when the statement can't be parsed.
    val parsed = FactNotice.draft(statement)
    val preciseEntity = parsed?.entity ?: entity
    val preciseAttr = parsed?.attr ?: attr
    // Possessed names use the named thing as the expert entity, but the confirmed slot
    // is the user's relationship (e.g. my cat), which remains stable across name changes.
    val possession = Regex("^我的(.+?)叫").find(statement)?.groupValues?.get(1)
        ?.let { if (it == "猫猫") "猫" else it }
    return if (possession != null) "我" to "possession:${possession}" else preciseEntity to preciseAttr
}

internal fun correctionExpert(row: ChatCorrection) = "correction:${row.id}"
