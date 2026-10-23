package com.lorabge.memory

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class EntityGroundTest {
    @Test
    fun openQuestionsUseEveryImportedExpert() {
        val facts = loadImported()
        assertTrue(facts.size >= 5)
        val byEntity = facts.groupBy { it.entity }
        val numbers = Regex("\\d+")
        for ((entity, own) in byEntity) {
            val reply = EntityGround.reply("告诉我${entity}公司相关信息", facts, "zh")
            assertNotNull("open question missed $entity", reply)
            assertEquals("entity", reply!!.reason)
            assertEquals(entity, reply.entity)
            for (fact in own) {
                if (fact.value.isNotBlank()) assertTrue(reply.answer.contains(fact.value))
            }
            fun nums(text: String) = numbers.findAll(text).map { it.value }.toList()
            val ownNumbers = own.flatMap { nums(it.value) + nums(it.statement) }.toSet()
            val foreign = facts.filter { it.entity != entity }
                .flatMap { nums(it.value) }
                .filter { it.length >= 2 && it !in ownNumbers }
                .toSet()
            for (found in numbers.findAll(reply.answer).map { it.value }) {
                assertFalse("$entity answer invented $found", found in foreign)
            }
        }
    }

    @Test
    fun zoreOpenQuestionReturns1979AndDoesNotInvent1998() {
        val facts = loadImported()
        val reply = EntityGround.reply("告诉我佐雷公司相关信息", facts, "zh")
        assertNotNull(reply)
        assertTrue(reply!!.answer.contains("1979"))
        assertFalse(reply.answer.contains("1998"))
        assertFalse(reply.answer.contains("圣迭戈"))
        assertEquals("entity", reply.reason)
    }

    @Test
    fun unknownSlotStaysInsideStoredFacts() {
        val facts = loadImported()
        val reply = EntityGround.reply("佐雷公司的首席执行官是谁", facts, "zh")
        assertNotNull(reply)
        assertEquals("entity_partial", reply!!.reason)
        assertTrue(reply.answer.contains("1979"))
        assertTrue(reply.answer.contains("其余不在记忆里"))
        assertFalse(reply.answer.contains("1998"))
        assertFalse(reply.answer.contains("圣迭戈"))
    }

    @Test
    fun catQuestionUsesTheStoredName() {
        val cat = StoredFact("expert_cat", "我", "我的猫猫叫咪咪", "咪咪", listOf("我的猫叫什么名字？"), "猫的名字")
        val reply = EntityGround.reply("我的猫叫什么名字？", listOf(cat), "zh")
        assertNotNull(reply)
        assertTrue(reply!!.answer.contains("咪咪"))
        assertEquals("entity", reply.reason)
    }

    @Test
    fun routeRecordKeepsTheNativeMiss() {
        val json = lastRouteJson(
            "告诉我佐雷公司相关信息",
            RouteHit(null, false, "abstain_fact", 0.41),
            GroundedReply("expert_0", "佐雷", "佐雷公司成立于1979年。", "entity"),
        )
        assertTrue(json.contains("\"nativeFired\":false"))
        assertTrue(json.contains("abstain_fact"))
        assertTrue(json.contains("\"grounded\":true"))
        assertTrue(json.contains("佐雷"))
    }

    private fun loadImported(): List<StoredFact> {
        val root = File("../../../experts")
        val dirs = root.listFiles()?.filter { it.isDirectory && it.name.startsWith("expert_") }?.sortedBy { it.name }.orEmpty()
        assertEquals(5, dirs.size)
        val facts = ArrayList<StoredFact>()
        for (dir in dirs) {
            val file = File(dir, "fact_memory.json")
            val text = file.readText().trim()
            assertTrue("${file.path} is not JSON", text.startsWith("["))
            val arr = JSONArray(text)
            for (i in 0 until arr.length()) {
                val row = arr.getJSONObject(i)
                val questions = ArrayList<String>()
                val raw = row.optJSONArray("questions")
                if (raw != null) for (q in 0 until raw.length()) questions.add(raw.optString(q))
                facts.add(
                    StoredFact(
                        dir.name,
                        row.getString("entity"),
                        row.getString("statement"),
                        row.optString("value"),
                        questions,
                        row.optString("attr"),
                    ),
                )
            }
        }
        return facts
    }
}
