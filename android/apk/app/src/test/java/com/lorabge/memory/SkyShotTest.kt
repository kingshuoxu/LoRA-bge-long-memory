package com.lorabge.memory

import androidx.compose.ui.unit.dp
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
            SkyFrame(sample().copy(tab = SkyTab.Chat, statusTop = 28.dp)) {}
        }
    }

    @Test
    fun chatKeyboardZh() {
        paparazzi.snapshot {
            SkyFrame(keyboardSample("zh")) {}
        }
    }

    @Test
    fun chatKeyboardEn() {
        paparazzi.snapshot {
            SkyFrame(keyboardSample("en")) {}
        }
    }

    @Test
    fun downloadZh() {
        paparazzi.snapshot { SetupFrame(downloadSample("zh")) }
    }

    @Test
    fun downloadEn() {
        paparazzi.snapshot { SetupFrame(downloadSample("en")) }
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

    private fun keyboardSample(lang: String): SkyState {
        val zh = lang != "en"
        return SkyState(
            lang = lang,
            tab = SkyTab.Chat,
            statusTop = 36.dp,
            imeBottom = 280.dp,
            draft = if (zh) "我的猫猫叫咪咪" else "My cat is called Mimi",
            ready = if (zh) "基座 ok · bge ok · CPU" else "base ok · bge ok · CPU",
            note = if (zh) "图形后端异常，已改用 CPU" else "Graphics backend failed, switched to CPU",
            messages = listOf(
                SkyMessage("user", if (zh) "我的猫猫叫咪咪" else "My cat is called Mimi"),
                SkyMessage(
                    "assistant",
                    if (zh) "好的,我记住了。" else "Okay, I'll remember that.",
                    noticed = true,
                ),
            ),
        )
    }

    private fun downloadSample(lang: String) = SetupState(
        lang = lang,
        statusTop = 36.dp,
        navBottom = 24.dp,
        mirror = "github.com",
        speedBps = 4_500_000,
        state = "running",
        message = if (lang == "en") "Downloading" else "下载中",
        url = "https://github.com/kingshuoxu/LoRA-bge-long-memory/releases/download/android-v0.1.0/manifest.json",
        files = listOf(
            SetupFileUi("tokenizer.json", 800, 1200, "running"),
            SetupFileUi("base.gguf", 120_000_000, 994_156_416, "wait"),
            SetupFileUi("bge.gguf", 95_000_000, 95_000_000, "checking"),
        ),
    )
}
