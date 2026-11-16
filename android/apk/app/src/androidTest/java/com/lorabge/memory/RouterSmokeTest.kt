package com.lorabge.memory

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** 装到 arm64 模拟器或真机上,确认 libmemoryroute.so 能加载并且实体优先路由还在。 */
@RunWith(AndroidJUnit4::class)
class RouterSmokeTest {
    @Test
    fun entityFirstRouteLoadsNativeLibrary() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = File(context.cacheDir, "router-smoke").apply { mkdirs() }
        val vec = FloatArray(4) { 0.5f }
        Engine.writeF32(File(dir, "e.f32"), listOf(vec))
        File(dir, "index.json").writeText(
            """{"tau":0.6,"dim":4,"experts":[{"name":"expert_0","entities":["塔佐巴洛"],"n_keys":1,"keys":"e.f32"}]}""",
        )
        val hit = JSONObject(
            NativeRouter.decide(
                File(dir, "index.json").absolutePath,
                "塔佐巴洛公司的总部在哪里?",
                vec,
                FloatArray(0),
            ),
        )
        assertTrue(hit.getBoolean("fired"))
        assertEquals("expert_0", hit.getString("expert"))
        assertEquals("entity", hit.getString("reason"))
        val names = JSONArray(NativeRouter.extract("""["塔佐巴洛公司成立于1978年。"]"""))
        var found = false
        for (i in 0 until names.length()) {
            if (names.getString(i) == "塔佐巴洛") found = true
        }
        assertTrue(found)
    }
}
