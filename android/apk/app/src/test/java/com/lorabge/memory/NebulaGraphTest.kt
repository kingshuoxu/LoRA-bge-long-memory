package com.lorabge.memory

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class NebulaGraphTest {
    @Test
    fun humanNamesLinksAndRecall() {
        val root = File("build/nebula-store")
        root.deleteRecursively()
        val store = MemoryStore(root)
        store.ensure()
        val facts0 = listOf(
            ReviewedFact("塔佐巴洛", "塔佐巴洛公司成立于1978年。", "1978", listOf("塔佐巴洛公司是哪一年成立的?" to "1978"), emptyList(), attr = "成立年份"),
            ReviewedFact("佐雷", "佐雷公司成立于1979年。", "1979", emptyList(), emptyList()),
        )
        val facts1 = listOf(
            ReviewedFact("佩莫", "佩莫公司的总部位于特希市。", "特希市", emptyList(), emptyList()),
            ReviewedFact("塔佐巴洛", "塔佐巴洛的门牌是12号。", "12", emptyList(), emptyList()).copy(gate = "0.81"),
        )
        store.registerExpert(ExpertRecord("expert_0", 0, 2, 32, "k", "adapter.gguf"), facts0)
        store.registerExpert(ExpertRecord("expert_1", 1, 2, 32, "k", "adapter.gguf"), facts1)
        val memory = org.json.JSONArray(File(store.expertsDir, "expert_1/fact_memory.json").readText())
        memory.getJSONObject(1).put("gate_score", 0.81).put("attr", "门牌")
        File(store.expertsDir, "expert_1/fact_memory.json").writeText(memory.toString())
        val now = "2026-01-01T00:00:00Z"
        store.saveConversation(
            Conversation(
                "c-tazo",
                "塔佐巴洛",
                now,
                now,
                listOf(ChatMessage("user", "塔佐巴洛公司是哪一年成立的?"), ChatMessage("assistant", "1978年。", "expert_0")),
            ),
        )
        val doc = JSONObject(NebulaGraph.build(store, "zh", "expert_0"))
        val experts = doc.getJSONArray("experts")
        assertEquals("塔佐巴洛、佐雷", experts.getJSONObject(0).getString("display_name"))
        assertEquals("佩莫、塔佐巴洛", experts.getJSONObject(1).getString("display_name"))
        assertTrue(experts.getJSONObject(0).getBoolean("explicit"))
        val blob = doc.toString()
        assertFalse(blob.contains("\"display_name\":\"expert_"))
        assertFalse(blob.contains("\"expert_label\":\"expert_"))
        val facts = doc.getJSONArray("facts")
        var sawGate = false
        var sawSource = false
        for (i in 0 until facts.length()) {
            val fact = facts.getJSONObject(i)
            assertFalse(fact.getString("expert_label").contains("expert_"))
            if (fact.has("gate_score")) {
                sawGate = true
                assertEquals(0.81, fact.getDouble("gate_score"), 0.001)
            }
            if (fact.has("source_title")) {
                sawSource = true
                assertEquals("塔佐巴洛", fact.getString("source_title"))
            }
        }
        assertTrue(sawGate)
        assertTrue(sawSource)
        val kinds = HashSet<String>()
        val links = doc.getJSONArray("links")
        for (i in 0 until links.length()) kinds.add(links.getJSONObject(i).getString("kind"))
        assertTrue(kinds.contains("source"))
        assertTrue(kinds.contains("entity"))
        val trace = JSONObject(NebulaGraph.recall(store, "zh", "expert_0", true, 0.81, "塔佐巴洛公司是哪一年成立的?"))
        assertTrue(trace.getBoolean("mounted"))
        assertTrue(trace.getString("banner").contains("塔佐巴洛、佐雷"))
        assertTrue(trace.getString("banner").contains("0.81"))
        assertFalse(trace.getString("banner").contains("expert_"))
        assertTrue(trace.getJSONArray("matched_facts").length() >= 1)
        val en = JSONObject(NebulaGraph.build(store, "en"))
        assertEquals("塔佐巴洛, 佐雷", en.getJSONArray("experts").getJSONObject(0).getString("display_name"))
        val enTrace = JSONObject(NebulaGraph.recall(store, "en", "expert_0", true, 0.81, "塔佐巴洛公司是哪一年成立的?"))
        assertTrue(enTrace.getString("banner").startsWith("Recall "))
        assertFalse(enTrace.getString("banner").contains("回忆"))
        writeShots(store)
    }

    @Test
    fun consolidateTimelineMarksTheTrainStage() {
        val running = stageStates("train")
        assertEquals("active", running[stageIds.indexOf("train")])
        assertEquals("done", running[stageIds.indexOf("build")])
        assertEquals("pending", running[stageIds.indexOf("recall")])
        val review = stageStates("gate")
        assertEquals("active", review[stageIds.indexOf("gate")])
        assertEquals("done", review[stageIds.indexOf("extract")])
        val idle = stageStates("")
        assertTrue(idle.all { it == "pending" })
        assertEquals(listOf("extract", "gate", "build", "train", "recall", "register"), stageIds)
        assertEquals("写闸门", skyText("zh", "stage.gate"))
        assertEquals("生成样本", skyText("zh", "stage.build"))
        assertEquals("注册专家", skyText("zh", "stage.register"))
    }

    @Test
    fun emptyExpertUsesMemoryNotRawId() {
        assertEquals("记忆", NebulaGraph.displayName(listOf("expert_0"), "zh"))
        assertEquals("Memory", NebulaGraph.displayName(emptyList(), "en"))
    }

    @Test
    fun backendLineHidesRawCodes() {
        val record = BackendRecord("auto", "cpu", "mali_unproven", true, "0.1.2+iso1", false, mali = true)
        val line = backendLine("zh", record, true, true)
        assertTrue(line.contains("基座已就绪"))
        assertTrue(line.contains("Mali"))
        assertFalse(line.contains("mali_unproven"))
        assertFalse(line.contains(" ok"))
        val status = presentTrainStatus("zh", """{"state":"running","detail":"expert_0"}""")
        assertEquals("巩固中", status)
    }

    private fun writeShots(store: MemoryStore) {
        val out = File("/tmp/nebula-fixtures")
        out.mkdirs()
        for (lang in listOf("zh", "en")) {
            val data = JSONObject(NebulaGraph.build(store, lang, null))
            val title = if (lang == "en") "Nebula" else "星云"
            fun wrap(mode: String, focus: String?, openFact: String?, recall: JSONObject?, tab: String): String {
                val obj = JSONObject()
                    .put("lang", lang)
                    .put("tab", tab)
                    .put("title", title)
                    .put("mode", mode)
                    .put("data", data)
                if (focus != null) obj.put("focus", focus)
                if (openFact != null) obj.put("openFact", openFact)
                if (recall != null) obj.put("recall", recall)
                return obj.toString()
            }
            val recall = JSONObject(NebulaGraph.recall(store, lang, "expert_0", true, 0.81, "塔佐巴洛公司是哪一年成立的?"))
            File(out, "overview-$lang.json").writeText(wrap("full", null, null, null, "nebula"))
            File(out, "expanded-$lang.json").writeText(wrap("full", "expert_1", "fact:expert_1:1", null, "nebula"))
            File(out, "recall-$lang.json").writeText(wrap("full", null, null, recall, "nebula"))
            File(out, "consolidate-$lang.json").writeText(wrap("dim", null, null, null, "nebula"))
        }
    }
}
