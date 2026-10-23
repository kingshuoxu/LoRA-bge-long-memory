package com.lorabge.memory

import org.json.JSONArray
import org.json.JSONObject

/**
 * 和桌面 memory_core.extract.expand_training_fact、prompts.with_brief 同一套。
 * 用户确认过的问句一定进训练。改写出来的闸门问句只当事实闸的键,不进样本。
 */
object FactExpand {
    private val trailing = listOf("最喜欢", "比较喜欢", "非常喜欢", "喜欢", "现在的", "目前的")

    fun hasCjk(text: String): Boolean = text.any { it in '\u4e00'..'\u9fff' }

    fun keepForTraining(fact: ReviewedFact): Boolean {
        // 闸门标了 skip_ 时,用户仍可勾选。勾选了就训练。
        if (!fact.selected && fact.gate.startsWith("skip_")) return false
        return fact.selected
    }

    fun expand(fact: ReviewedFact): ReviewedFact {
        val english = !hasCjk(fact.entity + fact.attr + fact.value + fact.statement)
        val attr = fact.attr.trim().ifBlank { if (english) "fact" else "事实" }
        val value = fact.value.trim()
        val statement = finishStatement(
            fact.statement.trim().ifBlank {
                if (english) "${fact.entity}'s $attr is $value." else "${fact.entity}的${attr}是$value。"
            },
        )
        val questions = ArrayList<String>()
        for ((q, _) in fact.qa) {
            val text = q.trim()
            if (text.isNotEmpty()) questions.add(text)
        }
        if (english) {
            if (questions.isEmpty()) questions.add("What is ${fact.entity}'s $attr?")
            questions.add("What is ${fact.entity}'s $attr?")
            questions.add("What is the $attr of ${fact.entity}?")
            questions.add("Could you tell me ${fact.entity}'s $attr?")
            questions.add("Do you know ${fact.entity}'s $attr?")
            questions.add("Please tell me the $attr of ${fact.entity}.")
            if (attr == "address" || attr == "where they live" || "lives in" in statement.lowercase()) {
                questions.add("Where does ${fact.entity} live?")
                questions.add("Where is ${fact.entity}'s home?")
                questions.add("What is ${fact.entity}'s address?")
            }
            if ("name" in attr.lowercase() || " named " in " ${statement.lowercase()} ") {
                questions.add("What is ${fact.entity}'s $attr called?")
                questions.add("Who is ${fact.entity}'s $attr?")
            }
        } else {
            if (questions.isEmpty()) questions.add(attrQuestion(fact.entity, attr, "是什么？"))
            questions.add(attrQuestion(fact.entity, attr, "是什么？"))
            questions.add("请问" + attrQuestion(fact.entity, attr, "是什么？"))
            questions.add("能告诉我" + attrQuestion(fact.entity, attr, "吗？"))
            questions.add("你知道" + attrQuestion(fact.entity, attr, "吗？"))
            questions.add("${fact.entity}${attr}是什么？")
            questions.add("关于${fact.entity}，${attr}是什么？")
            if ("住" in attr || "住在" in statement) {
                questions.add("${fact.entity}住在哪里？")
                questions.add("${fact.entity}住在什么地方？")
                questions.add("请问${fact.entity}的住址是哪里？")
            }
            if ("叫" in statement || "名" in attr) {
                questions.add("${fact.entity}的${attr}叫什么？")
                questions.add("${fact.entity}的${attr}是谁？")
            }
        }
        val seen = LinkedHashSet<String>()
        val qa = ArrayList<Pair<String, String>>()
        for (question in questions) {
            val text = question.trim()
            if (text.isEmpty() || !seen.add(text)) continue
            qa.add(text to value)
        }
        return fact.copy(attr = attr, value = value, statement = statement, qa = qa)
    }

    fun toFactsJsonl(facts: List<ReviewedFact>): String {
        val rows = ArrayList<String>()
        for (fact in facts) {
            val qa = JSONArray()
            for ((q, a) in fact.qa) qa.put(JSONObject().put("q", q).put("a", a))
            rows.add(JSONObject().put("statement", fact.statement).put("qa", qa).toString())
        }
        return if (rows.isEmpty()) "" else rows.joinToString("\n") + "\n"
    }

    private fun finishStatement(raw: String): String {
        val text = raw.trim()
        if (text.isEmpty()) return text
        if (text.last() in "。！？.!?") return text
        return text + if (hasCjk(text)) "。" else "."
    }

    private fun attrQuestion(entity: String, attr: String, tail: String): String {
        val glued = trailing.any { attr.startsWith(it + "的") }
        val joiner = if (glued) "" else "的"
        return "$entity$joiner$attr$tail"
    }
}
