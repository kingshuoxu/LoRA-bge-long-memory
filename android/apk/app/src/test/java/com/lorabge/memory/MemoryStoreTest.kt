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
    fun selfFactsAccumulateUnderOneExpert() {
        val root = Files.createTempDirectory("memory-self").toFile()
        val store = MemoryStore(root)
        val cat = ReviewedFact("我", "我的猫猫叫咪咪", "咪咪", listOf("我的猫叫什么名字？" to "咪咪"), emptyList(), attr = "猫的名字")
        val city = ReviewedFact("我", "我住在上海", "上海", emptyList(), emptyList(), attr = "城市")
        store.registerExpert(
            ExpertRecord("expert_968112", 3, 1, 32, "experts/expert_968112/router_key.f32", "experts/expert_968112/adapter.gguf"),
            listOf(cat),
        )
        store.registerExpert(
            ExpertRecord("expert_company", 4, 1, 32, "experts/expert_company/router_key.f32", "experts/expert_company/adapter.gguf"),
            listOf(ReviewedFact("佐雷", "佐雷公司成立于1979年。", "1979", emptyList(), emptyList())),
        )
        assertEquals(SELF_EXPERT, store.expertNameFor(listOf(city), "expert_111111"))
        assertEquals("expert_111111", store.expertNameFor(listOf(ReviewedFact("佐雷", "佐雷公司成立于1979年。", "1979", emptyList(), emptyList())), "expert_111111"))
        val merged = store.factsForTrain(listOf(city))
        assertEquals(listOf("我的猫猫叫咪咪", "我住在上海"), merged.map { it.statement })
        assertTrue(merged.all { it.entity == "我" })
        store.registerExpert(
            ExpertRecord(SELF_EXPERT, 5, merged.size, 32, "experts/$SELF_EXPERT/router_key.f32", "experts/$SELF_EXPERT/adapter.gguf"),
            merged,
        )
        val names = store.listExperts().map { it.expert }.sorted()
        assertEquals(listOf("expert_company", SELF_EXPERT), names)
        assertEquals("关于你", NebulaGraph.displayName(listOf("我"), "zh"))
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
