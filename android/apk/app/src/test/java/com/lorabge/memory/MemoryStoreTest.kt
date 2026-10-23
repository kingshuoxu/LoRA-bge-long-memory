package com.lorabge.memory

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

class MemoryStoreTest {
    @Test
    fun tailCoversEveryRow() {
        val n = 450
        val k = MemoryStore.tailCount(n)
        assertTrue(kotlin.math.floor((n + k) * 0.95).toInt() >= n)
    }

    @Test
    fun expertRoundTripMatchesRepoFields() {
        val root = Files.createTempDirectory("memory").toFile()
        val store = MemoryStore(root)
        val fact = ReviewedFact(
            entity = "塔佐巴洛",
            statement = "塔佐巴洛公司成立于1978年。",
            value = "1978",
            qa = listOf("塔佐巴洛公司是哪一年成立的?" to "1978"),
            sources = listOf("c-1"),
        )
        store.registerExpert(
            ExpertRecord("expert_9", 9, 1, 32, "experts/expert_9/router_key.f32", "experts/expert_9/adapter.gguf"),
            listOf(fact),
        )
        val line = store.listExperts().single()
        assertEquals("expert_9", line.expert)
        assertEquals(32, line.rank)
        val arr = org.json.JSONArray(root.resolve("experts/expert_9/fact_memory.json").readText())
        assertEquals("塔佐巴洛", arr.getJSONObject(0).getString("entity"))
        assertEquals("1978", arr.getJSONObject(0).getString("value"))
        assertFalse(arr.getJSONObject(0).has("attr"))
        val texts = org.json.JSONArray(root.resolve("experts/expert_9/key_texts.json").readText())
        assertEquals("塔佐巴洛公司成立于1978年。", texts.getString(0))
        val router = JSONObject(root.resolve("experts/router.jsonl").readText().trim())
        assertEquals("float32", router.getString("key_format"))
        store.deleteExpert("expert_9")
        assertTrue(store.listExperts().isEmpty())
        assertFalse(root.resolve("experts/expert_9").exists())
    }

    @Test
    fun trainingJsonlIsAssistantTurns() {
        val fact = ReviewedFact("甲", "甲公司成立于2000年。", "2000", listOf("甲哪年成立?" to "2000"), emptyList())
        val text = MemoryStore.trainingJsonl(listOf(fact))
        assertTrue(text.contains("\"role\":\"assistant\""))
        assertTrue(text.contains("请说出这条事实。"))
        assertTrue(text.contains("请简短回答。"))
        assertTrue(text.lines().filter { it.isNotBlank() }.size > 2)
    }
}
