package com.lorabge.memory

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

class Engine(private val context: Context, private val store: MemoryStore) {
    private val nativeDir = context.applicationInfo.nativeLibraryDir

    fun tool(name: String): File? {
        val file = File(nativeDir, name)
        return if (file.exists()) file else null
    }

    fun modelsDir(): File {
        // 真机基准经 run-as 把模型放进私有目录。外部目录仍给手动 adb 推送用。
        val internal = File(context.filesDir, "models")
        if (File(internal, "base.gguf").exists() || File(internal, "Qwen2.5-0.5B-Instruct/config.json").exists()) {
            return internal
        }
        val dir = File(context.getExternalFilesDir(null), "models")
        dir.mkdirs()
        return dir
    }

    fun baseModel(): File? = File(modelsDir(), "base.gguf").takeIf { it.exists() }
    fun bgeModel(): File? = File(modelsDir(), "bge.gguf").takeIf { it.exists() }

    fun binariesReady(): Boolean =
        tool("libllama-cli.so") != null && tool("libllama-embedding.so") != null

    fun route(text: String): RouteHit {
        val index = File(store.indexDir, "index.json")
        if (!index.exists()) rebuildIndex()
        if (!index.exists()) return RouteHit(null, false, "no_index", 0.0)
        val names = entityNames()
        val masked = maskQuery(text, names)
        val bge = bgeModel()
        val embedder = tool("libllama-embedding.so")
        if (bge == null || embedder == null) {
            return RouteHit(null, false, "no_bge", 0.0)
        }
        val vectors = embed(embedder, bge, listOf(text, masked))
        val json = NativeRouter.decide(index.absolutePath, text, vectors[0], vectors[1])
        val obj = JSONObject(json)
        val expert = if (obj.isNull("expert")) null else obj.optString("expert").ifBlank { null }
        return RouteHit(
            expert = expert,
            fired = obj.optBoolean("fired"),
            reason = obj.optString("reason"),
            sim = obj.optDouble("sim"),
        )
    }

    fun answer(question: String, expert: String?, ngl: Int): String {
        val cli = tool("libllama-cli.so") ?: return "没有 llama-cli。请安装带 QVAC 二进制的 APK。"
        val base = baseModel() ?: return "还没有基座。把 GGUF 推到 ${modelsDir().absolutePath}/base.gguf"
        val template = File(store.root, "qwen25_chat_template.jinja")
        if (!template.exists()) {
            context.assets.open("qwen25_chat_template.jinja").use { input ->
                template.writeBytes(input.readBytes())
            }
        }
        val cmd = mutableListOf(
            cli.absolutePath, "-m", base.absolutePath,
            "--jinja", "--chat-template-file", template.absolutePath,
            "-sys", "你是助手。",
            "-p", question + " 请简短回答。",
            "--temp", "0", "--top-k", "1", "--top-p", "1", "--min-p", "0",
            "-n", "40", "--single-turn", "-ngl", ngl.toString(), "--no-warmup", "-c", "512",
        )
        if (expert != null) {
            val weight = File(store.expertsDir, "$expert/adapter.gguf")
            if (weight.exists()) {
                cmd.add(3, "--lora")
                cmd.add(4, weight.absolutePath)
            }
        }
        val output = runTool(cmd, File(context.cacheDir, "gen"))
        val mark = "assistant\n"
        if (!output.contains(mark)) return output.lineSequence().lastOrNull { it.isNotBlank() } ?: "没有生成"
        return output.substringAfterLast(mark).replace("[end of text]", "").trim()
    }

    fun embedTexts(texts: List<String>): List<FloatArray> {
        val embedder = tool("libllama-embedding.so") ?: error("没有 llama-embedding")
        val bge = bgeModel() ?: error("没有 bge.gguf")
        return embed(embedder, bge, texts)
    }

    fun rebuildIndex() {
        store.ensure()
        val experts = store.listExperts()
        val expertJson = JSONArray()
        val factRows = JSONArray()
        val factVectors = ArrayList<FloatArray>()
        for (record in experts) {
            val dir = File(store.expertsDir, record.expert)
            val keyFile = File(dir, "router_key.f32")
            val texts = File(dir, "key_texts.json").takeIf { it.exists() }?.readText() ?: "[]"
            val entities = try {
                JSONArray(NativeRouter.extract(texts))
            } catch (_: Throwable) {
                JSONArray()
            }
            val nKeys = if (keyFile.exists()) (keyFile.length() / (512 * 4)).toInt() else 0
            if (nKeys > 0) keyFile.copyTo(File(store.indexDir, "${record.expert}.f32"), overwrite = true)
            expertJson.put(
                JSONObject()
                    .put("name", record.expert)
                    .put("entities", entities)
                    .put("n_keys", nKeys)
                    .put("keys", if (nKeys > 0) "${record.expert}.f32" else ""),
            )
            val memoryFile = File(dir, "fact_memory.json")
            val factVec = File(dir, "fact_vectors.f32")
            if (memoryFile.exists() && factVec.exists()) {
                val rows = JSONArray(memoryFile.readText())
                val floats = readF32(factVec)
                var cursor = 0
                for (i in 0 until rows.length()) {
                    val row = rows.getJSONObject(i)
                    val questions = row.optJSONArray("questions")
                    val n = 1 + (questions?.length() ?: 0)
                    repeat(n) {
                        if (cursor + 512 <= floats.size) {
                            factRows.put(JSONObject().put("entity", row.getString("entity")))
                            factVectors.add(floats.copyOfRange(cursor, cursor + 512))
                            cursor += 512
                        }
                    }
                }
            }
        }
        if (factVectors.isNotEmpty()) writeF32(File(store.indexDir, "facts.f32"), factVectors)
        val index = JSONObject()
            .put("tau", 0.6)
            .put("dim", 512)
            .put("experts", expertJson)
        if (factVectors.isNotEmpty()) {
            index.put(
                "facts",
                JSONObject()
                    .put("tau", 0.622)
                    .put("mask", "某")
                    .put("vectors", "facts.f32")
                    .put("rows", factRows),
            )
        }
        File(store.indexDir, "index.json").writeText(index.toString())
    }

    fun importExternal() {
        val incoming = File(context.getExternalFilesDir(null), "import")
        importBundle(incoming)
    }

    fun importBundle(incoming: File) {
        if (!incoming.exists()) return
        val routerFile = File(incoming, "router.jsonl")
        if (routerFile.exists()) {
            val existing = store.listExperts().map { it.expert }.toMutableSet()
            for (line in routerFile.readLines().filter { it.isNotBlank() }) {
                val record = ExpertRecord.fromJson(line)
                if (record.expert in existing) continue
                val src = File(incoming, record.expert)
                if (!src.exists()) continue
                src.copyRecursively(File(store.expertsDir, record.expert), overwrite = true)
                store.writeRouter((store.listExperts() + record).sortedBy { it.batch })
                existing.add(record.expert)
            }
            val gate = File(incoming, "fact_gate.json")
            if (gate.exists()) gate.copyTo(File(store.expertsDir, "fact_gate.json"), overwrite = true)
        }
        rebuildIndex()
    }

    fun selfCheck(): String {
        val dir = File(store.root, "selfcheck")
        dir.mkdirs()
        val vec = FloatArray(4) { 0.5f }
        writeF32(File(dir, "e.f32"), listOf(vec))
        File(dir, "index.json").writeText(
            """
            {"tau":0.6,"dim":4,"experts":[{"name":"expert_0","entities":["塔佐巴洛"],"n_keys":1,"keys":"e.f32"}]}
            """.trimIndent(),
        )
        val hit = NativeRouter.decide(
            File(dir, "index.json").absolutePath,
            "塔佐巴洛公司的总部在哪里?",
            vec,
            FloatArray(0),
        )
        val obj = JSONObject(hit)
        val ok = obj.optBoolean("fired") && obj.optString("expert") == "expert_0" && obj.optString("reason") == "entity"
        return if (ok) "路由自检通过: ${obj.optString("reason")}" else "路由自检失败: $hit"
    }

    private fun entityNames(): List<String> {
        val index = File(store.indexDir, "index.json")
        if (!index.exists()) return emptyList()
        val experts = JSONObject(index.readText()).optJSONArray("experts") ?: return emptyList()
        val names = ArrayList<String>()
        for (i in 0 until experts.length()) {
            val ents = experts.getJSONObject(i).optJSONArray("entities") ?: continue
            for (j in 0 until ents.length()) names.add(ents.getString(j))
        }
        return names.distinct().sortedByDescending { it.length }
    }

    private fun embed(bin: File, model: File, texts: List<String>): List<FloatArray> {
        val work = File(context.cacheDir, "emb").apply { mkdirs() }
        File(work, "prompts.txt").writeText(texts.joinToString("\n") { it.replace("\n", " ") } + "\n")
        val ngl = if (File(store.root, "use_gpu").exists()) "99" else "0"
        val output = runTool(
            listOf(
                bin.absolutePath, "-m", model.absolutePath, "-f", File(work, "prompts.txt").absolutePath,
                "--pooling", "mean", "--embd-normalize", "2", "-c", "128", "-ngl", ngl,
                "--embd-output-format", "array",
            ),
            work,
        )
        val raw = output.trim().substringAfterLast('\n').let { line ->
            val start = output.indexOf('[')
            if (start < 0) error("embedding 没有数组: ${output.take(200)}")
            output.substring(start).trim()
        }
        val parsed = JSONArray(raw)
        if (texts.size == 1 && parsed.length() > 0 && parsed.optJSONArray(0) == null) {
            return listOf(floatRow(parsed))
        }
        return (0 until parsed.length()).map { floatRow(parsed.getJSONArray(it)) }
    }

    private fun runTool(cmd: List<String>, work: File): String {
        work.mkdirs()
        val proc = ProcessBuilder(cmd)
            .directory(work)
            .redirectErrorStream(false)
            .apply { environment()["LD_LIBRARY_PATH"] = nativeDir }
            .start()
        val stdout = proc.inputStream.bufferedReader().readText()
        val stderr = proc.errorStream.bufferedReader().readText()
        val code = proc.waitFor()
        if (code != 0 && stdout.isBlank()) error(stderr.lineSequence().lastOrNull { it.isNotBlank() } ?: "exit $code")
        return stdout.ifBlank { stderr }
    }

    companion object {
        fun maskQuery(text: String, namesLongestFirst: List<String>): String {
            var out = text
            for (name in namesLongestFirst) {
                if (name.isNotEmpty() && name in out) out = out.replace(name, "某")
            }
            return out
        }

        fun writeF32(file: File, rows: List<FloatArray>) {
            file.outputStream().buffered().use { out ->
                val buf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
                for (row in rows) {
                    for (value in row) {
                        buf.clear()
                        buf.putFloat(value)
                        out.write(buf.array())
                    }
                }
            }
        }

        fun readF32(file: File): FloatArray {
            val bytes = file.readBytes()
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val out = FloatArray(bytes.size / 4)
            for (i in out.indices) out[i] = buf.float
            return out
        }

        private fun floatRow(arr: JSONArray): FloatArray {
            val out = FloatArray(arr.length())
            for (i in 0 until arr.length()) out[i] = arr.getDouble(i).toFloat()
            return out
        }
    }
}

data class RouteHit(val expert: String?, val fired: Boolean, val reason: String, val sim: Double)
