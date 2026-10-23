package com.lorabge.memory

data class FactDraft(
    val entity: String,
    val attr: String,
    val statement: String,
    val value: String,
    val question: String,
    val answer: String,
)

/** 一句新事实只在回复下面留一行小字,巩固页再去训练。问句和回答由这句话自己填上。 */
object FactNotice {
    fun draft(text: String): FactDraft? {
        val body = text.trim().trimEnd('。', '.', '！', '!', ' ')
        if (body.length < 4) return null
        if (body.endsWith("?") || body.endsWith("？")) return null
        if (body.contains("什么") || body.contains("吗") || body.contains("哪") || body.contains("怎么")) return null
        val cat = Regex("^我的猫猫?叫(.+)$").find(body)
        if (cat != null) {
            val value = cat.groupValues[1].trim()
            return FactDraft("我", "猫的名字", body, value, "我的猫叫什么名字？", value)
        }
        val mine = Regex("^我的(.+?)叫(.+)$").find(body)
        if (mine != null) {
            val thing = mine.groupValues[1].trim()
            val value = mine.groupValues[2].trim()
            return FactDraft("我", "${thing}的名字", body, value, "我的${thing}叫什么？", value)
        }
        val of = Regex("^(.+?)的(.+?)是(.+)$").find(body)
        if (of != null) {
            val entity = of.groupValues[1].trim()
            val attr = of.groupValues[2].trim()
            val value = of.groupValues[3].trim()
            return FactDraft(entity, attr, body, value, "${entity}的${attr}是什么？", value)
        }
        val called = Regex("^(.+?)叫(.+)$").find(body)
        if (called != null) {
            val entity = called.groupValues[1].trim()
            val value = called.groupValues[2].trim()
            return FactDraft(entity, "名字", body, value, "${entity}叫什么？", value)
        }
        return null
    }

    fun acknowledge(draft: FactDraft, lang: String): String {
        if (draft.attr == "猫的名字") {
            return if (lang == "en") "Okay, I'll remember. Your cat is named ${draft.value}."
            else "好的，记住了，你的猫叫${draft.value}。"
        }
        val statement = draft.statement.trim()
        val sentence = if (statement.lastOrNull() in listOf('。', '.', '！', '!', '？', '?')) statement else {
            statement + if (lang == "en") "." else "。"
        }
        return if (lang == "en") "Okay, I'll remember. $sentence" else "好的，记住了。$sentence"
    }

    fun noticed(text: String): Boolean {
        val body = text.trim()
        if (body.length < 4 || body.length > 80) return false
        if (body.endsWith("?") || body.endsWith("？")) return false
        if (body.contains("吗") || body.contains("什么") || body.contains("哪") || body.contains("怎么")) return false
        val lower = body.lowercase()
        if (lower.contains("what ") || lower.contains("which ") || lower.contains("how ") || lower.contains("why ")) return false
        if (looksLikeCorrection(body)) return true
        if (body.contains("叫")) return true
        if (Regex("的.+是.+").containsMatchIn(body)) return true
        if (lower.contains(" is called ") || lower.contains(" my ")) return true
        return false
    }

    fun guess(text: String): PendingCorrection {
        val called = Regex("(.+?)叫(.+)").find(text.trim())
        if (called != null) {
            val entity = called.groupValues[1].trim()
            val value = called.groupValues[2].trim().trimEnd('。', '.', '！', '!')
            return PendingCorrection(entity, text.trim(), value)
        }
        return guessCorrection(text)
    }
}
