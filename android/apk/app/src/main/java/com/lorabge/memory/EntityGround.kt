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
        val ask = selfAsk(query)
        if (ask == "assistant") return null
        if (ask != null) return selfReply(ask, facts, lang)
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
        val lines = (if (picked.isNotEmpty()) picked else related)
            .map { finish(assistantVoice(it.statement, it.entity)) }
            .distinct()
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

    /**
     * 我 / 我的 in the user's message is the user. 你是谁 is the assistant.
     * identity, name, place, overview, or assistant. Null means not a self question.
     */
    internal fun selfAsk(query: String): String? {
        val q = norm(query)
        if (q.isEmpty()) return null
        val lower = q.lowercase()
        val aboutUser = q.contains("我") || Regex("""\b(i|me|my)\b""").containsMatchIn(lower)
        val assistant = !aboutUser && (
            q.startsWith("你是谁") || q.startsWith("你叫什么") ||
                Regex("""\bwho are you\b""").containsMatchIn(lower) ||
                Regex("""what(?:'s| is) your name\b""").containsMatchIn(lower)
            )
        if (assistant) return "assistant"
        if (q == "我是谁" || q.startsWith("我是谁") || Regex("""\bwho am i\b""").containsMatchIn(lower)) return "identity"
        if (q.startsWith("我叫什么") || q.startsWith("我的名字") ||
            Regex("""what(?:'s| is) my name\b""").containsMatchIn(lower)
        ) {
            return "name"
        }
        if (q.startsWith("我住") || Regex("""\bwhere (?:do i live|am i from)\b""").containsMatchIn(lower)) return "place"
        if (q.contains("关于我") || q.contains("你知道我") || q.contains("你了解我") ||
            Regex("""what do you know about me\b""").containsMatchIn(lower)
        ) {
            return "overview"
        }
        return null
    }

    /** Force the about-you expert. A miss must not fall through to the base model's own identity. */
    internal fun selfRoute(query: String, hasSelfExpert: Boolean): RouteHit? {
        val ask = selfAsk(query) ?: return null
        if (ask == "assistant") return null
        return if (hasSelfExpert) {
            RouteHit(SELF_EXPERT, true, "self", 1.0)
        } else {
            RouteHit(null, false, "self_empty", 0.0)
        }
    }

    private fun selfReply(kind: String, facts: List<StoredFact>, lang: String): GroundedReply {
        val mine = facts.filter { isSelfEntity(it.entity) }
        val picked = when (kind) {
            "place" -> mine.filter { factKind(it.statement) == "place" || it.statement.contains("住") }
            "overview" -> mine
            else -> mine.filter { isUserName(it) }
        }
        val use = when {
            picked.isNotEmpty() -> picked
            kind == "overview" -> mine
            else -> emptyList()
        }
        if (use.isEmpty()) {
            val answer = when {
                lang == "en" && kind == "place" -> "I don't know where you live yet. You can tell me."
                lang == "en" -> "I don't know who you are yet. You can tell me."
                kind == "place" -> "还不知道你住在哪里。你可以告诉我。"
                else -> "还不知道你是谁。你可以告诉我。"
            }
            return GroundedReply("", "我", answer, "self_empty")
        }
        val lines = use.map { finish(assistantVoice(it.statement, it.entity)) }.distinct()
        val fact = use.first()
        return GroundedReply(fact.expert, "我", lines.joinToString(""), "entity")
    }

    private fun isUserName(fact: StoredFact): Boolean {
        if (!isSelfEntity(fact.entity)) return false
        if (fact.attr.contains("猫")) return false
        if (fact.attr == "名字") return true
        val statement = fact.statement.trim()
        return statement.startsWith("我叫") || statement.startsWith("我是") || statement.startsWith("我的名字")
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

    /**
     * Stored lines keep the user's own words ("我的猫猫叫咪咪").
     * A reply has to speak to them, not repeat the sentence as if the assistant were the user.
     */
    internal fun assistantVoice(statement: String, entity: String): String {
        if (!isSelfEntity(entity)) return statement
        val text = statement.trim()
        if (text.isEmpty()) return text
        if (!FactExpand.hasCjk(text)) return speakEnglish(text)
        val kept = text.replace("我们", "\uE000")
        val yours = kept.replace("我的", "你的")
        val plural = yours.replace("\uE000", "你们")
        return plural.replace(Regex("(?<![\\p{IsHan}])我(?!们)"), "你")
    }

    private fun speakEnglish(text: String): String {
        var spoken = text
        spoken = Regex("\\bI'm\\b", RegexOption.IGNORE_CASE).replace(spoken, "you're")
        spoken = Regex("\\bI am\\b", RegexOption.IGNORE_CASE).replace(spoken, "you are")
        spoken = Regex("\\bI\\b").replace(spoken, "you")
        spoken = Regex("\\b[Mm]y\\b").replace(spoken) { match ->
            if (match.value.first().isUpperCase()) "Your" else "your"
        }
        spoken = Regex("\\b[Mm]ine\\b").replace(spoken) { match ->
            if (match.value.first().isUpperCase()) "Yours" else "yours"
        }
        spoken = Regex("^you\\b").replace(spoken, "You")
        spoken = Regex("^your\\b").replace(spoken, "Your")
        return spoken
    }

    private fun finish(text: String): String {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return trimmed
        if (trimmed.last() in "。！？.!?") return trimmed
        return trimmed + if (FactExpand.hasCjk(trimmed)) "。" else "."
    }
}
