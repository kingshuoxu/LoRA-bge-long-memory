package com.lorabge.memory

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import org.junit.Rule
import org.junit.Test

class SkyShotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    @Test
    fun chat() {
        paparazzi.snapshot {
            SkyFrame(sample().copy(tab = SkyTab.Chat, pending = PendingCorrection("塔佐巴洛", "塔佐巴洛的成立年份是1979年。", "1979年"))) {}
        }
    }

    @Test
    fun consolidate() {
        paparazzi.snapshot {
            SkyFrame(
                sample().copy(
                    tab = SkyTab.Consolidate,
                    training = true,
                    loss = listOf(5.35f, 2.56f, 1.19f, 0.36f, 0.19f),
                    status = "第 2 轮,loss 0.19",
                ),
            ) {}
        }
    }

    @Test
    fun nebula() {
        paparazzi.snapshot {
            SkyFrame(
                sample().copy(
                    tab = SkyTab.Nebula,
                    highlightExpert = "expert_0",
                    experts = listOf(
                        SkyExpert("expert_0", listOf("塔佐巴洛公司成立于1978年。", "佐雷公司成立于1979年。")),
                        SkyExpert("expert_1", listOf("佩莫公司的总部位于特希市。")),
                    ),
                ),
            ) {}
        }
    }

    private fun sample() = SkyState(
        lang = "zh",
        messages = listOf(
            SkyMessage("user", "塔佐巴洛公司是哪一年成立的?", null),
            SkyMessage("assistant", "1978年。", "expert_0"),
        ),
        conversations = listOf("塔佐巴洛"),
        ready = "基座 ok · bge ok",
        entity = "塔佐巴洛",
        statement = "塔佐巴洛公司成立于1978年。",
        value = "1978",
        question = "塔佐巴洛公司是哪一年成立的?",
        answer = "1978",
    )
}
