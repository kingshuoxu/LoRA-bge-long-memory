package com.lorabge.memory

import java.io.File

/**
 * 只在 `-Plorabge.e2eHooks=true` 的仪器测试包里编译。
 * 中文句子没法用 `input text` 打进去，测试把草稿写到这个文件，界面再读出来。
 */
internal object E2eDraft {
    private const val RELATIVE = "setup/e2e-draft.txt"

    fun poll(filesDir: File): String? {
        val file = File(filesDir, RELATIVE)
        if (!file.isFile) return null
        val text = file.readText()
        return text.ifEmpty { null }
    }

    fun clear(filesDir: File) {
        File(filesDir, RELATIVE).delete()
    }
}
