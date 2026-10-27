package com.lorabge.memory

import java.io.File

data class StoredFact(
    val expert: String,
    val entity: String,
    val statement: String,
    val value: String,
    val questions: List<String> = emptyList(),
    val attr: String = "",
)

data class GroundedReply(
    val expert: String,
    val entity: String,
    val answer: String,
    val reason: String,
)

/**
 * 问句里出现已保存的实体时，直接用这些事实作答。
 * 不再把开放问题交给基座模型，避免它编一个仓库里没有的年份或地址。
 */
object EntityGround {
    fun load(store: MemoryStore): List<StoredFact> {
        val out = ArrayList<StoredFact>()
        for (record in store.listExperts()) {
            for (row in NebulaGraph.readFacts(File(store.expertsDir, record.expert))) {
                val entity = row.optString("entity").trim()
                val statement = row.optString("statement").trim()
                if (entity.isEmpty() || statement.isEmpty()) continue
                out.add(
                    StoredFact(
                        record.expert,
                        entity,
                        statement,
                        row.optString("value").trim(),
                        questions = stringList(row.optJSONArray("questions")),
                        attr = row.optString("attr").trim(),
                    ),
                )
            }
        }
        return out
    }

    fun reply(query: String, facts: List<StoredFact>, lang: String = "zh"): GroundedReply? {
        val alias = longestAlias(query, facts)
        val related = if (alias != null) {
            facts.filter { it.entity == alias.first.entity }
        } else {
            facts.filter { personalHit(query, it) || questionMatches(query, it) }
        }
        if (related.isEmpty()) return null
        val fact = alias?.first ?: related.first()
        val kind = askedKind(query)
        val picked = if (kind == null) related else related.filter { factKind(it.statement) == kind }
        val lines = (if (picked.isNotEmpty()) picked else related).map { finish(it.statement) }.distinct()
        if (lines.isEmpty()) return null
        val missing = kind != null && picked.isEmpty()
        val body = lines.joinToString("")
        val answer = if (!missing) {
            body
        } else if (lang == "en") {
            body + " The rest is not in memory."
        } else {
            body + "其余不在记忆里。"
        }
        return GroundedReply(
            expert = fact.expert,
            entity = fact.entity,
            answer = answer,
            reason = if (missing) "entity_partial" else "entity",
        )
    }

    private fun stringList(arr: org.json.JSONArray?): List<String> {
        if (arr == null) return emptyList()
        val out = ArrayList<String>()
        for (i in 0 until arr.length()) {
            val text = arr.optString(i).trim()
            if (text.isNotEmpty()) out.add(text)
        }
        return out
    }

    private fun personalHit(query: String, fact: StoredFact): Boolean {
        if (fact.entity != "我" || fact.attr.isBlank()) return false
        val noun = fact.attr.removeSuffix("的名字")
        if (noun.isBlank() || noun == fact.attr) return false
        return query.contains(noun) && (query.contains("叫") || query.contains("名字") || query.contains("是"))
    }

    private fun questionMatches(query: String, fact: StoredFact): Boolean {
        val q = norm(query)
        if (q.length < 4) return false
        return (fact.questions + fact.statement).any { stored ->
            val s = norm(stored)
            s.length >= 4 && (s in q || q in s)
        }
    }

    private fun norm(text: String) = text.trim().trimEnd('？', '?', '。', '.', '！', '!', ' ')

    private fun longestAlias(query: String, facts: List<StoredFact>): Pair<StoredFact, String>? {
        var best: Pair<StoredFact, String>? = null
        for (fact in facts) {
            val aliases = listOf(fact.entity + "公司", fact.entity + "集团", fact.entity).distinct()
            for (alias in aliases) {
                if (alias.length < 2 || alias !in query) continue
                if (alias.length > (best?.second?.length ?: 0)) best = fact to alias
            }
        }
        return best
    }

    internal fun askedKind(query: String): String? = when {
        query.contains("成立") || query.contains("哪一年") || query.contains("哪年") || query.contains("什么时候") -> "year"
        query.contains("总部") || query.contains("住在") || query.contains("位于") -> "place"
        query.contains("产品") || query.contains("旗舰") -> "product"
        query.contains("首席") || query.contains("CEO") || query.contains("总裁") -> "ceo"
        else -> null
    }

    internal fun factKind(statement: String): String = when {
        statement.contains("成立") -> "year"
        statement.contains("总部") || statement.contains("位于") || statement.contains("住在") -> "place"
        statement.contains("产品") || statement.contains("旗舰") -> "product"
        statement.contains("首席") || statement.contains("执行官") || statement.contains("总裁") -> "ceo"
        else -> "other"
    }

    private fun finish(text: String): String {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return trimmed
        if (trimmed.last() in "。！？.!?") return trimmed
        return trimmed + if (FactExpand.hasCjk(trimmed)) "。" else "."
    }
}
