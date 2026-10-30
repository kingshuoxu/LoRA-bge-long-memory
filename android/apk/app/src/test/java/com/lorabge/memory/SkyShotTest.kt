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
    fun selfIntroZh() {
        paparazzi.snapshot { SkyFrame(selfIntroSample()) {} }
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
    fun settingsUpdateZh() {
        paparazzi.snapshot {
            SkyFrame(
                settingsSample("zh").copy(
                    updatePhase = "downloading",
                    updateVersion = "0.1.18",
                    updateMessage = "正在下载",
                    updateNotes = "0.1.18 把两条待巩固都列出来。更新说明单独成块，不再盖住设置里的字。",
                ),
            ) {}
        }
    }

    @Test
    fun consolidateQueueZh() {
        paparazzi.snapshot { SkyFrame(fourPending()) {} }
    }

    @Test
    fun consolidateBatchRunningZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = true,
                    loss = listOf(1.2f, 0.4f),
                    train = TrainSnapshot(
                        state = "running",
                        stage = "train",
                        step = 3,
                        total = 8,
                        epoch = 2,
                        epochs = 4,
                        loss = 0.4f,
                        elapsedSec = 40,
                        etaSec = 67,
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "running"),
                        SkyBatchItem("我叫徐金朔", "queued"),
                        SkyBatchItem("我是徐金朔。", "queued"),
                        SkyBatchItem("我的猫猫叫咪咪", "queued"),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateBatchDoneZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = false,
                    loss = listOf(1.2f, 0.08f),
                    train = TrainSnapshot(state = "done", stage = "done", step = 8, total = 8, epoch = 4, epochs = 4, loss = 0.08f),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "done"),
                        SkyBatchItem("我叫徐金朔", "done"),
                        SkyBatchItem("我是徐金朔。", "done"),
                        SkyBatchItem("我的猫猫叫咪咪", "done"),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateBatchWaitingZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = false,
                    status = "要等充电并且屏幕关闭。点「现在训练」会立刻开始。",
                    train = TrainSnapshot(state = "waiting", detail = "要等充电并且屏幕关闭。点「现在训练」会立刻开始。"),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "waiting"),
                        SkyBatchItem("我叫徐金朔", "waiting"),
                        SkyBatchItem("我是徐金朔。", "waiting"),
                        SkyBatchItem("我的猫猫叫咪咪", "waiting"),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateTrainLiveZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = true,
                    loss = emptyList(),
                    train = TrainSnapshot(
                        state = "running",
                        stage = "train",
                        total = 12,
                        epochs = 4,
                        elapsedSec = 48,
                        etaSec = 120,
                        pendingStep = 1,
                        micro = 4,
                        microTotal = 8,
                        microElapsedSec = 12,
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "running", 2),
                        SkyBatchItem("我叫徐金朔", "running", 2),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateTrainRetryZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = true,
                    status = "这一微批超过 45 秒没有新输出，改用 1 个 CPU 线程重试",
                    train = TrainSnapshot(
                        state = "running",
                        stage = "train",
                        total = 12,
                        epochs = 4,
                        elapsedSec = 50,
                        pendingStep = 1,
                        micro = 4,
                        microTotal = 8,
                        microElapsedSec = 45,
                        detail = "这一微批超过 45 秒没有新输出，改用 1 个 CPU 线程重试",
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "running", 2),
                        SkyBatchItem("我叫徐金朔", "running", 2),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateOomZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = false,
                    status = "失败",
                    train = TrainSnapshot(
                        state = "error",
                        stage = "train",
                        step = 2,
                        total = 8,
                        detail = "内存不足被系统终止",
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "error", 2),
                        SkyBatchItem("我叫徐金朔", "error", 2),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateSuccessZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = false,
                    status = "已完成",
                    loss = listOf(1.2f, 0.1788f),
                    train = TrainSnapshot(
                        state = "done",
                        stage = "done",
                        step = 20,
                        total = 20,
                        epoch = 4,
                        epochs = 4,
                        loss = 0.1788f,
                        detail = "已登记 expert_self",
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "done", 2),
                        SkyBatchItem("我叫徐金朔", "done", 2),
                    ),
                ),
            ) {}
        }
    }

    @Test
    fun consolidateTrainStallZh() {
        paparazzi.snapshot {
            SkyFrame(
                fourPending().copy(
                    training = false,
                    status = "失败",
                    train = TrainSnapshot(
                        state = "error",
                        stage = "train",
                        total = 12,
                        elapsedSec = 179,
                        pendingStep = 1,
                        micro = 4,
                        microTotal = 8,
                        microElapsedSec = 120,
                        detail = "这一微批没有再往前走。点「重试」再训一次，或点「放弃」。\n停在第 1 步的第 4 个微批",
                    ),
                    batchItems = listOf(
                        SkyBatchItem("我的猫叫咪咪", "error", 2),
                        SkyBatchItem("我叫徐金朔", "error", 2),
                    ),
                ),
            ) {}
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
        paparazzi.snapshot { SkyFrame(consolidateSample("zh")) {} }
    }

    @Test
    fun consolidateEn() {
        paparazzi.snapshot { SkyFrame(consolidateSample("en")) {} }
    }

    @Test
    fun consolidateMicro() {
        paparazzi.snapshot { SkyFrame(consolidateMicroSample()) {} }
    }

    @Test
    fun libraryZh() {
        paparazzi.snapshot {
            SkyFrame(
                sample().copy(
                    tab = SkyTab.Library,
                    statusTop = 36.dp,
                    navBottom = 24.dp,
                    pendingFacts = listOf("我的猫猫叫咪咪"),
                ),
            ) {}
        }
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

    private fun selfIntroSample() = SkyState(
        lang = "zh",
        tab = SkyTab.Chat,
        statusTop = 36.dp,
        navBottom = 24.dp,
        currentTitle = "你好 我是徐金朔",
        messages = listOf(
            SkyMessage("user", "你好 我是徐金朔"),
            SkyMessage("assistant", "好的，记住了，你是徐金朔。", noticed = true),
        ),
        toast = "图形后端异常，已改用 CPU",
    )

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
        versionName = "0.1.27",
    )

    private fun fourPending() = SkyState(
        lang = "zh",
        tab = SkyTab.Consolidate,
        statusTop = 36.dp,
        navBottom = 24.dp,
        entity = "我",
        statement = "我叫徐金朔",
        value = "徐金朔",
        question = "我叫什么？",
        answer = "徐金朔",
        pendingDrafts = listOf(
            SkyPending("我", "我的猫叫咪咪", "咪咪", "我的猫叫什么名字？", "咪咪", "猫的名字"),
            SkyPending("我", "我叫徐金朔", "徐金朔", "我叫什么？", "徐金朔", "名字"),
            SkyPending("我", "我是徐金朔。", "徐金朔", "我叫什么？", "徐金朔", "名字"),
            SkyPending("我", "我的猫猫叫咪咪", "咪咪", "我的猫叫什么名字？", "咪咪", "猫的名字"),
        ),
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

    /** The vivo frame: last loss is step 2, micro 6 of step 3 is in progress. */
    private fun consolidateMicroSample() = sample().copy(
        tab = SkyTab.Consolidate,
        training = true,
        statusTop = 36.dp,
        navBottom = 24.dp,
        entity = "我",
        statement = "我的猫猫叫咪咪",
        value = "咪咪",
        question = "我的猫叫什么名字？",
        answer = "咪咪",
        force = true,
        loss = listOf(1.10f, 0.74f),
        status = "巩固中",
        train = TrainSnapshot(
            state = "running",
            stage = "train",
            step = 2,
            total = 8,
            epoch = 1,
            epochs = 4,
            loss = 0.74f,
            elapsedSec = 117,
            etaSec = 351,
            pendingStep = 3,
            micro = 6,
            microTotal = 8,
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
