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
    fun draft(text: String): FactDraft? = drafts(text).firstOrNull()

    fun drafts(text: String): List<FactDraft> {
        val raw = text.trim()
        if (raw.length < 4 || raw.length > 600) return emptyList()
        if (isQuestion(raw) || looksLikeCorrection(raw) || isChore(raw)) return emptyList()
        val body = stripRemember(raw)
        if (body.length < 4) return emptyList()
        val parts = sentences(body)
        if (parts.size > 1) return sequence(parts)
        val whole = draftClause(body, carried = null)
        if (whole != null) return listOf(whole)
        val pieces = commaParts(body)
        if (pieces.size > 1) return sequence(pieces)
        return emptyList()
    }

    fun acknowledge(draft: FactDraft, lang: String): String {
        if (draft.attr == "猫的名字") {
            return if (lang == "en") "Okay, I'll remember. Your cat is named ${draft.value}."
            else "好的，记住了，你的猫叫${draft.value}。"
        }
        if (draft.entity == "我" && draft.attr == "名字") {
            return if (lang == "en") "Okay, I'll remember. You're ${draft.value}."
            else "好的，记住了，你是${draft.value}。"
        }
        return if (lang == "en") "Okay, I'll remember." else "好的，记住了。"
    }

    fun acknowledgeAll(drafts: List<FactDraft>, lang: String): String {
        if (drafts.size == 1) return acknowledge(drafts[0], lang)
        return if (lang == "en") "Okay, I'll remember." else "好的，记住了。"
    }

    fun noticed(text: String): Boolean {
        val body = text.trim()
        if (body.length < 4 || body.length > 600) return false
        if (body.endsWith("?") || body.endsWith("？")) return false
        if (looksLikeCorrection(body)) return true
        return drafts(body).isNotEmpty()
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

    private fun sequence(parts: List<String>): List<FactDraft> {
        val out = ArrayList<FactDraft>()
        var carried: String? = null
        for (part in parts) {
            if (isQuestion(part) || isChore(part)) continue
            val one = draftClause(part, carried) ?: continue
            out.add(one)
            if (one.entity != "我") carried = one.entity
        }
        return out
    }

    private fun draftClause(text: String, carried: String?): FactDraft? {
        val body = text.trim().trimEnd('。', '.', '！', '!', ' ')
        if (body.length < 4 || isQuestion(body)) return null
        val cat = Regex("^我的猫猫?叫(.+)$").find(body)
        if (cat != null) {
            val value = cat.groupValues[1].trim()
            if (dirty(value) || value.isEmpty()) return null
            return FactDraft("我", "猫的名字", body, value, "我的猫叫什么名字？", value)
        }
        val mine = Regex("^我的(.+?)叫(.+)$").find(body)
        if (mine != null) {
            val thing = mine.groupValues[1].trim()
            val value = mine.groupValues[2].trim()
            if (thing.isEmpty() || dirty(value) || value.isEmpty()) return null
            return FactDraft("我", "${thing}的名字", body, value, "我的${thing}叫什么？", value)
        }
        draftSelf(body)?.let { return it }
        draftFounded(body)?.let { return it }
        draftHq(body, carried)?.let { return it }
        draftLive(body)?.let { return it }
        draftLocated(body)?.let { return it }
        val of = Regex("^(.+?)的(.+?)是(.+)$").find(body)
        if (of != null) {
            val entity = stripOrg(of.groupValues[1].trim())
            val attr = of.groupValues[2].trim()
            val value = of.groupValues[3].trim()
            if (entity.length >= 1 && attr.isNotEmpty() && value.length in 1..24 && !dirty(value) && entity !in BARE) {
                return FactDraft(entity, attr, body, value, "${entity}的${attr}是什么？", value)
            }
        }
        val called = Regex("^(.+?)叫(.+)$").find(body)
        if (called != null) {
            val entity = stripOrg(called.groupValues[1].trim())
            val value = called.groupValues[2].trim()
            if (entity.isNotEmpty() && value.length in 1..24 && !dirty(value)) {
                return FactDraft(entity, "名字", body, value, "${entity}叫什么？", value)
            }
        }
        draftEnglish(body)?.let { return it }
        return draftCopula(body)
    }

    private fun draftSelf(body: String): FactDraft? {
        val match = Regex("^(?:你好[，,。\\s]*)?我是(.+)$").find(body) ?: return null
        val value = match.groupValues[1].trim()
        if (!looksLikeName(value)) return null
        val statement = finish("我是$value")
        return FactDraft("我", "名字", statement, value, "我叫什么？", value)
    }

    private fun draftFounded(body: String): FactDraft? {
        val match = Regex("^(.+?)成立于(.+)$").find(body) ?: return null
        val subject = match.groupValues[1].trim()
        val rest = match.groupValues[2].trim()
        if (subject.length < 2 || dirty(rest)) return null
        val year = Regex("(\\d{3,4})").find(rest)?.groupValues?.get(1) ?: return null
        val entity = stripOrg(subject)
        if (entity.length < 2) return null
        return FactDraft(entity, "成立年份", finish(body), year, "${subject}是哪一年成立的?", year)
    }

    private fun draftHq(body: String, carried: String?): FactDraft? {
        val match = Regex("^(?:(.+?)的)?总部(?:位于|在)(.+)$").find(body) ?: return null
        val prefixed = match.groupValues[1].trim()
        val value = match.groupValues[2].trim()
        if (dirty(value) || value.length !in 1..24) return null
        val raw = prefixed.ifBlank { carried.orEmpty() }
        if (raw.isBlank()) return null
        val entity = stripOrg(raw)
        if (entity.length < 2 || entity in BARE) return null
        val statement = if (prefixed.isBlank()) finish("${entity}的总部在$value") else finish(body)
        val subject = prefixed.ifBlank { entity }
        return FactDraft(entity, "总部", statement, value, "${subject}的总部在哪里？", value)
    }

    private fun draftLive(body: String): FactDraft? {
        val match = Regex("^我?住在(.+)$").find(body) ?: return null
        val value = match.groupValues[1].trim()
        if (dirty(value) || value.length !in 1..24) return null
        return FactDraft("我", "居住地", finish("我住在$value"), value, "我住在哪里？", value)
    }

    private fun draftLocated(body: String): FactDraft? {
        val match = Regex("^(.+?)位于(.+)$").find(body) ?: return null
        val subject = match.groupValues[1].trim()
        val value = match.groupValues[2].trim()
        if (subject.length < 2 || dirty(value) || value.length !in 1..24) return null
        if (subject.endsWith("总部")) return null
        val entity = stripOrg(subject)
        if (entity.length < 2 || entity in BARE) return null
        return FactDraft(entity, "所在地", finish(body), value, "${subject}位于哪里？", value)
    }

    private fun draftEnglish(body: String): FactDraft? {
        val cat = Regex("(?i)^my cat is called (.+)$").find(body)
        if (cat != null) {
            val value = cat.groupValues[1].trim()
            if (value.isEmpty() || dirty(value)) return null
            return FactDraft("我", "猫的名字", body, value, "我的猫叫什么名字？", value)
        }
        val name = Regex("(?i)^my name is (.+)$").find(body)
        if (name != null) {
            val value = name.groupValues[1].trim()
            if (!looksLikeName(value)) return null
            return FactDraft("我", "名字", body, value, "我叫什么？", value)
        }
        val called = Regex("(?i)^(.+?) is called (.+)$").find(body) ?: return null
        val entity = called.groupValues[1].trim()
        val value = called.groupValues[2].trim()
        if (entity.length !in 2..24 || value.length !in 1..24 || dirty(value)) return null
        if (entity.lowercase() in setOf("it", "this", "that", "there")) return null
        return FactDraft(entity, "名字", body, value, "${entity}叫什么？", value)
    }

    private fun draftCopula(body: String): FactDraft? {
        val match = Regex("^(.+?)是(.+)$").find(body) ?: return null
        val entity = stripOrg(match.groupValues[1].trim())
        val value = match.groupValues[2].trim()
        if (entity.length !in 2..24 || value.length !in 1..24 || dirty(value)) return null
        if (entity in BARE || entity.any { it in "你我" }) return null
        if (HEDGE.any { it in entity }) return null
        return FactDraft(entity, "是", finish(body), value, "${entity}是什么？", value)
    }

    private fun sentences(body: String): List<String> {
        return body.split(Regex("[。！!\\n；;]+"))
            .map { it.trim().trimEnd('。', '.', '！', '!', ' ') }
            .filter { it.isNotBlank() }
    }

    private fun commaParts(body: String): List<String> {
        return body.split(Regex("[，,]+")).map { it.trim() }.filter { it.isNotBlank() }
    }

    private fun stripRemember(text: String): String {
        var body = text.trim()
        val prefixes = listOf(
            "请帮我记住", "帮我记住", "请记住", "请记下", "帮我记下", "记下：", "记下:", "记下，", "记下,",
            "记住：", "记住:", "记住，", "记住,", "记住",
        )
        for (prefix in prefixes) {
            if (body.startsWith(prefix)) {
                body = body.removePrefix(prefix).trim()
                break
            }
        }
        return body
    }

    private fun isQuestion(body: String): Boolean {
        val text = body.trim()
        if (text.endsWith("?") || text.endsWith("？")) return true
        if (listOf("什么", "吗", "哪", "怎么", "告诉我", "请问", "为什么", "多少", "谁").any { it in text }) return true
        val lower = text.lowercase()
        return listOf("what ", "which ", "how ", "why ", "who ").any { it in lower }
    }

    private fun isChore(body: String): Boolean {
        return listOf("帮我写", "帮我翻译", "请翻译", "翻译一下", "解释一下", "请解释", "总结一下", "帮我总结", "请总结").any { it in body }
    }

    private fun looksLikeName(value: String): Boolean {
        if (value.length !in 1..8 || dirty(value)) return false
        if (value.any { it in "的是不在有要想说会能个了吗呢啊呀" }) return false
        val spaces = value.count { it == ' ' }
        if (spaces > 1) return false
        return value.all { it.isLetter() || it == ' ' || it == '·' || it == '•' || it in '\u4e00'..'\u9fff' }
    }

    private fun dirty(value: String) = value.any { it in "，,。；;！!\n？" || it == '?' }

    private fun stripOrg(name: String): String {
        var text = name.trim()
        for (suffix in listOf("有限责任公司", "股份有限公司", "有限公司", "公司", "集团")) {
            if (text.endsWith(suffix) && text.length > suffix.length + 1) {
                text = text.removeSuffix(suffix).trim()
                break
            }
        }
        return text
    }

    private fun finish(text: String): String {
        val trimmed = text.trim().trimEnd('。', '.', ' ', '！', '!')
        if (trimmed.isEmpty()) return trimmed
        return trimmed + if (trimmed.any { it in '\u4e00'..'\u9fff' }) "。" else "."
    }

    private val BARE = setOf("这", "那", "这里", "那里", "今天", "现在", "你", "他", "她", "它", "这个", "那个", "我们", "他们")
    private val HEDGE = listOf("觉得", "认为", "希望", "可以", "应该", "可能", "想要", "不想", "请")
}
