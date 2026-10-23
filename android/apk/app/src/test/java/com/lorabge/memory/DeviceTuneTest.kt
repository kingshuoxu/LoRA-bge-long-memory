package com.lorabge.memory

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceTuneTest {
    @Test
    fun eliteKeepsBothOryonClusters() {
        val freqs = List(2) { 4_320_000L } + List(6) { 3_530_000L }
        assertEquals(8, DeviceTune.performanceThreads(freqs, 8))
    }

    @Test
    fun dimensityDropsTheLittleCluster() {
        val freqs = listOf(3_620_000L) + List(3) { 3_300_000L } + List(4) { 2_400_000L }
        assertEquals(4, DeviceTune.performanceThreads(freqs, 8))
    }

    @Test
    fun missingFreqsUseTheFallback() {
        assertEquals(6, DeviceTune.performanceThreads(emptyList(), 6))
        assertEquals(8, DeviceTune.performanceThreads(listOf(0L, 0L), 99))
    }

    @Test
    fun autoFallsBackWhenChatOrEmbeddingDisagrees() {
        val mismatch = DeviceTune.decide(
            mode = "auto",
            vulkanPresent = true,
            modelsReady = true,
            gpuChatStatus = 0,
            cpuReply = "2",
            gpuReply = "NaN",
            gpuEmbedStatus = 0,
            cpuVec = null,
            gpuVec = null,
            version = "0.1.1",
        )
        assertEquals("cpu", DeviceTune.active(mismatch))
        assertEquals("chat_mismatch", mismatch.reason)

        val embed = DeviceTune.decide(
            mode = "auto",
            vulkanPresent = true,
            modelsReady = true,
            gpuChatStatus = 0,
            cpuReply = "2",
            gpuReply = "2",
            gpuEmbedStatus = 0,
            cpuVec = floatArrayOf(1f, 0f),
            gpuVec = floatArrayOf(0f, 1f),
            version = "0.1.1",
        )
        assertEquals("cpu", embed.probe)
        assertEquals("embed_mismatch", embed.reason)
    }

    @Test
    fun crashAndTimeoutAreRememberedAsCpu() {
        val crashed = DeviceTune.decide("auto", true, true, 1, "", "", 0, null, null, "0.1.1")
        assertEquals("chat_exit", crashed.reason)
        assertTrue(crashed.probed)
        val timed = DeviceTune.decide("auto", true, true, 2, "", "", 0, null, null, "0.1.1")
        assertEquals("chat_timeout", timed.reason)
    }

    @Test
    fun matchingProbeSelectsVulkan() {
        val vec = floatArrayOf(0.6f, 0.8f)
        val chosen = DeviceTune.decide("auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.1")
        assertEquals("vulkan", DeviceTune.active(chosen))
        assertEquals("matched", chosen.reason)
        assertEquals(99, DeviceTune.ngl(chosen))
    }

    @Test
    fun forceGpuStaysOnVulkanAndForceCpuDoesNot() {
        val gpu = DeviceTune.decide("gpu", true, true, 1, "", "", 1, null, null, "0.1.1")
        assertEquals("vulkan", DeviceTune.active(gpu))
        assertEquals(99, DeviceTune.ngl(gpu))
        val cpu = DeviceTune.decide("cpu", true, true, 0, "2", "2", 0, floatArrayOf(1f), floatArrayOf(1f), "0.1.1")
        assertEquals("cpu", DeviceTune.active(cpu))
        assertEquals(0, DeviceTune.ngl(cpu))
        val missing = DeviceTune.decide("gpu", false, true, 0, "", "", 0, null, null, "0.1.1")
        assertEquals("cpu", DeviceTune.active(missing))
        assertEquals("no_vulkan", missing.reason)
    }

    @Test
    fun vectorsRejectNanAndAcceptCloseCopies() {
        assertFalse(DeviceTune.vectorsMatch(floatArrayOf(1f, 0f), floatArrayOf(Float.NaN, 0f)))
        assertTrue(DeviceTune.vectorsMatch(floatArrayOf(1f, 0f), floatArrayOf(0.999f, 0.001f)))
        assertTrue(DeviceTune.chatMatch("2\n", "  2  "))
        assertFalse(DeviceTune.chatMatch("2", ""))
    }

    @Test
    fun reportNamesTheSocGpuAndBackend() {
        val text = DeviceTune.renderDiagnostics(
            DiagnosticFacts(
                whenIso = "2026-10-23T00:00:00Z",
                manufacturer = "vivo",
                model = "V2413",
                soc = "MediaTek Dimensity 9400",
                gpu = "Mali-G925-Immortalis",
                androidRelease = "15",
                appVersion = "0.1.1",
                backend = "cpu",
                mode = "auto",
                reason = "chat_mismatch",
                threads = 4,
                freqsKhz = listOf(3_620_000L, 2_400_000L),
                vulkanLib = true,
                cpuLib = true,
                base = true,
                bge = true,
            ),
        )
        assertTrue(text.contains("Dimensity 9400"))
        assertTrue(text.contains("Mali-G925-Immortalis"))
        assertTrue(text.contains("后端: cpu"))
        assertTrue(text.contains("线程: 4"))
        assertTrue(text.contains("GPU 解码 tok/s: 未测"))
        assertTrue(text.contains("Vulkan 子组: 未知"))
        val json = DeviceTune.deviceJson(
            DiagnosticFacts(
                "t", "vivo", "V2413", "MT6991", "Mali-G925", "15", "0.1.1",
                "cpu", "auto", "chat_mismatch", 4, listOf(3_620_000L), true, true, true, true,
            ),
        )
        assertEquals("MT6991", json.getString("soc"))
        assertEquals("Mali-G925", json.getString("gpu"))
        assertEquals(4, json.getInt("threads"))
        assertEquals(0.0, json.getDouble("gpu_decode_tps"), 0.0)
    }

    @Test
    fun maliUsesGpuOnlyWhenFaster() {
        val vec = floatArrayOf(1f, 0f)
        val slower = DeviceTune.decide(
            "auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.2+iso1",
            mali = true, gpuSpeedStatus = 0, gpuDecodeTps = 12.0, cpuDecodeTps = 20.0, isolated = true,
        )
        assertEquals("cpu", slower.probe)
        assertEquals("gpu_slower", slower.reason)
        assertEquals(0, DeviceTune.ngl(slower))

        val unproven = DeviceTune.decide(
            "auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.2+iso1",
            mali = true, gpuSpeedStatus = 0, gpuDecodeTps = 40.0, cpuDecodeTps = 20.0, isolated = false,
        )
        assertEquals("cpu", unproven.probe)
        assertEquals("mali_unproven", unproven.reason)
        assertEquals(0, DeviceTune.ngl(unproven))

        val faster = DeviceTune.decide(
            "auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.2+iso1",
            mali = true, gpuSpeedStatus = 0, gpuDecodeTps = 40.0, cpuDecodeTps = 20.0, isolated = true,
        )
        assertEquals("vulkan", faster.probe)
        assertEquals("matched_faster", faster.reason)
        assertEquals(99, DeviceTune.ngl(faster))

        val unknown = DeviceTune.decide(
            "auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.2+iso1",
            mali = true, gpuSpeedStatus = -1, gpuDecodeTps = 40.0, cpuDecodeTps = 20.0, isolated = true,
        )
        assertEquals("speed_unknown", unknown.reason)

        val stale = BackendRecord(
            "auto", "vulkan", "matched_faster", true, "0.1.1+mali1", false,
            mali = true, isolated = false,
        )
        assertEquals("cpu", DeviceTune.active(stale))
        assertEquals("vulkan", DeviceTune.active(stale.copy(isolated = true)))
        assertTrue(DeviceTune.suspectMali("MediaTek Dimensity 9400", "V2413", ""))
        assertFalse(DeviceTune.suspectMali("Qualcomm", "2407FPN8EG", "Adreno 830"))
        assertEquals("0.1.2+iso1", DeviceTune.probeStamp("0.1.2"))
    }

    @Test
    fun adrenoKeepsGpuWhenItIsSlower() {
        val vec = floatArrayOf(1f, 0f)
        val chosen = DeviceTune.decide(
            "auto", true, true, 0, "2", "2", 0, vec, vec, "0.1.1+mali1",
            mali = false, gpuSpeedStatus = 0, gpuDecodeTps = 5.0, cpuDecodeTps = 30.0,
        )
        assertEquals("vulkan", chosen.probe)
        assertEquals("matched", chosen.reason)
    }

    @Test
    fun logKeepsPrefillAndDecodeApart() {
        val log = """
            ggml_vulkan: caps name="Mali-G925-Immortalis MC12" driver="Mali" driver_info="v1.r47p0" driver_version=92274688 vendor=0x13b5 subgroup=16 fp16=1 bf16=0 coopmat=0 coopmat2=0 int_dot=1 uma=1 max_alloc=2147483648 max_buffer=1073741824 suballoc=268435456 storage_buffers=24 wg_invocations=1024 wg=64x64 mali=1
            I common_perf_print: prompt eval time =     120.00 ms /    40 tokens (    3.00 ms per token,   333.30 tokens per second)
            I common_perf_print:        eval time =      80.00 ms /    16 runs   (    5.00 ms per token,   200.00 tokens per second)
        """.trimIndent()
        val tps = DeviceTune.parseTps(log)
        assertEquals(333.3, tps.first, 0.01)
        assertEquals(200.0, tps.second, 0.01)
        val caps = DeviceTune.parseVulkanCaps(log)
        assertEquals("Mali-G925-Immortalis MC12", caps.name)
        assertEquals("v1.r47p0", caps.driverInfo)
        assertEquals(92274688L, caps.driverVersion)
        assertEquals(0x13B5L, caps.vendor)
        assertEquals(16, caps.subgroup)
        assertEquals(1, caps.fp16)
        assertEquals(0, caps.bf16)
        assertEquals(0, caps.coopmat)
        assertEquals(268435456L, caps.suballoc)
        assertTrue(DeviceTune.looksLikeMali(caps, "Adreno"))
        assertFalse(DeviceTune.looksLikeMali(VulkanCaps(name = "Adreno (TM) 830", vendor = 0x5143), "Adreno (TM) 830"))
        val text = DeviceTune.renderDiagnostics(
            DiagnosticFacts(
                "t", "vivo", "V2413", "MT6991", "Mali-G925", "15", "0.1.1",
                "vulkan", "auto", "matched_faster", 4, listOf(3_620_000L), true, true, true, true,
                gpuPrefillTps = 333.3, gpuDecodeTps = 200.0, cpuPrefillTps = 80.0, cpuDecodeTps = 40.0,
                vkName = caps.name, vkDriver = caps.driver, vkDriverVersion = caps.versionText(),
                vkSubgroup = caps.subgroup, vkFlags = caps.flags(),
            ),
        )
        assertTrue(text.contains("GPU 预填充 tok/s: 333.3"))
        assertTrue(text.contains("GPU 解码 tok/s: 200.0"))
        assertTrue(text.contains("CPU 解码 tok/s: 40.0"))
        assertTrue(text.contains("Vulkan 设备: Mali-G925-Immortalis MC12"))
        assertTrue(text.contains("Vulkan 子组: 16"))
        assertTrue(text.contains("fp16=1"))
        assertTrue(text.contains("bf16=0"))
        assertTrue(text.contains("coopmat=0"))
        val json = DeviceTune.deviceJson(
            DiagnosticFacts(
                "t", "vivo", "V2413", "MT6991", "Mali-G925", "15", "0.1.1",
                "vulkan", "auto", "matched_faster", 4, emptyList(), true, true, true, true,
                gpuDecodeTps = 200.0, vkName = caps.name, vkSubgroup = 16, vkFlags = caps.flags(),
            ),
        )
        assertEquals(200.0, json.getDouble("gpu_decode_tps"), 0.01)
        assertEquals(16, json.getInt("vk_subgroup"))
        assertEquals("Mali-G925-Immortalis MC12", json.getString("vk_name"))
    }
}
