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
        val json = DeviceTune.deviceJson(
            DiagnosticFacts(
                "t", "vivo", "V2413", "MT6991", "Mali-G925", "15", "0.1.1",
                "cpu", "auto", "chat_mismatch", 4, listOf(3_620_000L), true, true, true, true,
            ),
        )
        assertEquals("MT6991", json.getString("soc"))
        assertEquals("Mali-G925", json.getString("gpu"))
        assertEquals(4, json.getInt("threads"))
    }
}
