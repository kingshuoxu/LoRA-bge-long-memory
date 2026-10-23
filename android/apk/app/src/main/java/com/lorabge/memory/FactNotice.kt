package com.lorabge.memory

/** 一句新事实只在回复下面留一行小字,巩固页再去训练。 */
object FactNotice {
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
