package com.lorabge.memory

import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.GLES20
import android.os.Build
import java.io.File

object PhoneFacts {
    fun maxFreqsKhz(): List<Long> {
        val root = File("/sys/devices/system/cpu")
        val cpus = root.listFiles()?.filter { it.name.matches(Regex("cpu[0-9]+")) }
            ?.sortedBy { it.name.drop(3).toIntOrNull() ?: 0 }
            ?: emptyList()
        val perCpu = cpus.map { cpu ->
            readFreq(File(cpu, "cpufreq/cpuinfo_max_freq"))
                ?: readFreq(File(cpu, "cpufreq/scaling_max_freq"))
                ?: 0L
        }
        if (perCpu.any { it > 0 }) return perCpu
        val policies = File(root, "cpufreq").listFiles()?.filter { it.name.startsWith("policy") } ?: return emptyList()
        val expanded = ArrayList<Long>()
        for (policy in policies) {
            val freq = readFreq(File(policy, "cpuinfo_max_freq"))
                ?: readFreq(File(policy, "scaling_max_freq"))
                ?: continue
            val related = File(policy, "related_cpus").takeIf { it.canRead() }
                ?.readText()?.trim()?.split(Regex("\\s+"))?.count { it.isNotEmpty() }
                ?: 1
            repeat(related.coerceAtLeast(1)) { expanded.add(freq) }
        }
        return expanded
    }

    fun threads(): Int = DeviceTune.performanceThreads(maxFreqsKhz(), Runtime.getRuntime().availableProcessors())

    fun glRenderer(): String {
        return try {
            val display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
            if (display == EGL14.EGL_NO_DISPLAY) return ""
            val version = IntArray(2)
            if (!EGL14.eglInitialize(display, version, 0, version, 1)) return ""
            val attribs = intArrayOf(
                EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
                EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT,
                EGL14.EGL_NONE,
            )
            val configs = arrayOfNulls<EGLConfig>(1)
            val count = IntArray(1)
            if (!EGL14.eglChooseConfig(display, attribs, 0, configs, 0, 1, count, 0) || count[0] == 0) {
                EGL14.eglTerminate(display)
                return ""
            }
            val pbuffer = intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE)
            val surface = EGL14.eglCreatePbufferSurface(display, configs[0], pbuffer, 0)
            val ctxAttrib = intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE)
            val context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT, ctxAttrib, 0)
            if (surface == EGL14.EGL_NO_SURFACE || context == EGL14.EGL_NO_CONTEXT) {
                EGL14.eglTerminate(display)
                return ""
            }
            EGL14.eglMakeCurrent(display, surface, surface, context)
            val name = GLES20.glGetString(GLES20.GL_RENDERER).orEmpty()
            EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT)
            EGL14.eglDestroySurface(display, surface)
            EGL14.eglDestroyContext(display, context)
            EGL14.eglTerminate(display)
            name
        } catch (_: Throwable) {
            ""
        }
    }

    fun socName(): String {
        val fromBuild = if (Build.VERSION.SDK_INT >= 31) {
            listOf(Build.SOC_MANUFACTURER, Build.SOC_MODEL)
                .filter { it.isNotBlank() && !it.equals("unknown", ignoreCase = true) }
                .joinToString(" ")
        } else {
            ""
        }
        val hardware = File("/proc/cpuinfo").takeIf { it.canRead() }
            ?.readLines()
            ?.firstOrNull { it.startsWith("Hardware") }
            ?.substringAfter(":")
            ?.trim()
            .orEmpty()
        return listOf(fromBuild, hardware).filter { it.isNotBlank() }.distinct().joinToString(" / ")
    }

    fun collect(engine: Engine, appVersion: String): DiagnosticFacts {
        val record = engine.backendRecord()
        return DiagnosticFacts(
            whenIso = java.time.Instant.now().toString(),
            manufacturer = Build.MANUFACTURER.orEmpty(),
            model = Build.MODEL.orEmpty(),
            soc = socName(),
            gpu = glRenderer(),
            androidRelease = Build.VERSION.RELEASE.orEmpty(),
            appVersion = appVersion,
            backend = DeviceTune.active(record),
            mode = record.mode,
            reason = DeviceTune.explain(record),
            threads = threads(),
            freqsKhz = maxFreqsKhz().filter { it > 0 },
            vulkanLib = engine.tool("libggml-vulkan.so") != null,
            cpuLib = engine.tool("libggml-cpu.so") != null,
            base = engine.baseModel() != null,
            bge = engine.bgeModel() != null,
        )
    }

    private fun readFreq(file: File): Long? {
        if (!file.canRead()) return null
        return file.readText().trim().toLongOrNull()
    }
}
