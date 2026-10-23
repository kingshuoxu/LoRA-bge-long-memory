package com.lorabge.memory

import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import org.junit.Rule
import org.junit.Test

class SkyShotTest {
    @get:Rule
    val paparazzi = Paparazzi(
        deviceConfig = DeviceConfig.PIXEL_6,
        useDeviceResolution = true,
    )

    @Test
    fun chatEmptyZh() {
        paparazzi.snapshot { SkyFrame(emptyChat("zh")) {} }
    }

    @Test
    fun chatEmptyEn() {
        paparazzi.snapshot { SkyFrame(emptyChat("en")) {} }
    }

    @Test
    fun chat() {
        paparazzi.snapshot { SkyFrame(sample().copy(tab = SkyTab.Chat, statusTop = 36.dp, navBottom = 24.dp)) {} }
    }

    @Test
    fun chatKeyboardZh() {
        paparazzi.snapshot { SkyFrame(keyboardSample("zh")) {} }
    }

    @Test
    fun chatKeyboardEn() {
        paparazzi.snapshot { SkyFrame(keyboardSample("en")) {} }
    }

    @Test
    fun settingsZh() {
        paparazzi.snapshot { SkyFrame(settingsSample("zh")) {} }
    }

    @Test
    fun settingsEn() {
        paparazzi.snapshot { SkyFrame(settingsSample("en")) {} }
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
        paparazzi.snapshot { SkyFrame(consolidateSample("zh")) {} }
    }

    @Test
    fun consolidateEn() {
        paparazzi.snapshot { SkyFrame(consolidateSample("en")) {} }
    }

    @Test
    fun nebula() {
        paparazzi.snapshot { SkyFrame(nebulaSample("zh", recall = false)) {} }
    }

    @Test
    fun nebulaEn() {
        paparazzi.snapshot { SkyFrame(nebulaSample("en", recall = false)) {} }
    }

    @Test
    fun recallZh() {
        paparazzi.snapshot { SkyFrame(nebulaSample("zh", recall = true)) {} }
    }

    @Test
    fun recallEn() {
        paparazzi.snapshot { SkyFrame(nebulaSample("en", recall = true)) {} }
    }

    private fun emptyChat(lang: String) = SkyState(
        lang = lang,
        tab = SkyTab.Chat,
        statusTop = 36.dp,
        navBottom = 24.dp,
        liveNebula = false,
    )

    private fun sample() = SkyState(
        lang = "zh",
        messages = listOf(
            SkyMessage("user", "塔佐巴洛公司是哪一年成立的?"),
            SkyMessage("assistant", "1978年。", "expert_0"),
        ),
        conversations = listOf(SkyConversation("c1", "塔佐巴洛")),
        currentTitle = "塔佐巴洛",
        entity = "塔佐巴洛",
        statement = "塔佐巴洛公司成立于1978年。",
        value = "1978",
        question = "塔佐巴洛公司是哪一年成立的?",
        answer = "1978",
        experts = listOf(
            SkyExpert("expert_0", listOf("塔佐巴洛公司成立于1978年。", "佐雷公司成立于1979年。"), "塔佐巴洛、佐雷"),
            SkyExpert("expert_1", listOf("佩莫公司的总部位于特希市。"), "佩莫"),
        ),
    )

    private fun keyboardSample(lang: String): SkyState {
        val zh = lang != "en"
        return SkyState(
            lang = lang,
            tab = SkyTab.Chat,
            statusTop = 36.dp,
            imeBottom = 280.dp,
            navBottom = 24.dp,
            currentTitle = if (zh) "我的猫猫叫咪咪" else "My cat is called Mimi",
            draft = if (zh) "我的猫猫叫咪咪" else "My cat is called Mimi",
            toast = if (zh) "图形后端异常，已改用 CPU" else "Graphics backend failed, switched to CPU",
            messages = listOf(
                SkyMessage("user", if (zh) "我的猫猫叫咪咪" else "My cat is called Mimi"),
                SkyMessage(
                    "assistant",
                    if (zh) "好的，记住了，你的猫叫咪咪。" else "Okay, I'll remember. Your cat is named Mimi.",
                    noticed = true,
                ),
            ),
        )
    }

    private fun settingsSample(lang: String) = SkyState(
        lang = lang,
        settingsOpen = true,
        statusTop = 36.dp,
        navBottom = 24.dp,
        backendMode = "auto",
        backendLine = if (lang == "en") {
            "Base ready · bge ready · CPU\nThis Mali GPU stays on CPU until an isolated test is faster."
        } else {
            "基座已就绪 · bge 已就绪 · CPU\n这台 Mali 还没在独立进程里证明更快，先用 CPU。"
        },
        wifiOnly = false,
        manifestUrl = "",
        storageLabel = "1.8 GB",
        versionName = "0.1.3",
    )

    private fun consolidateSample(lang: String) = sample().copy(
        lang = lang,
        tab = SkyTab.Consolidate,
        training = true,
        statusTop = 36.dp,
        navBottom = 24.dp,
        loss = listOf(5.35f, 2.56f, 1.19f, 0.36f, 0.19f),
        status = if (lang == "en") "Train LoRA" else "训练 LoRA",
        train = TrainSnapshot(
            state = "running",
            stage = "train",
            step = 5,
            total = 16,
            epoch = 2,
            epochs = 4,
            loss = 0.19f,
            elapsedSec = 40,
            etaSec = 88,
        ),
    )

    private fun nebulaSample(lang: String, recall: Boolean) = sample().copy(
        lang = lang,
        tab = SkyTab.Nebula,
        statusTop = 36.dp,
        navBottom = 24.dp,
        highlightExpert = if (recall) "expert_0" else null,
        recallBanner = if (!recall) {
            ""
        } else if (lang == "en") {
            "Recall 塔佐巴洛, 佐雷 · similarity 0.81"
        } else {
            "回忆 塔佐巴洛、佐雷 · 相似度 0.81"
        },
        liveNebula = false,
    )

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
            SetupFileUi("tokenizer.json", 2_400_000, 2_400_000, "done"),
            SetupFileUi("base.gguf", 180L * 1024 * 1024, 1_266_425_696L, "running"),
            SetupFileUi("bge.gguf", 0, 95L * 1024 * 1024, "wait"),
        ),
    )
}
