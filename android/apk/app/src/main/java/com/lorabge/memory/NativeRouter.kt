package com.lorabge.memory

object NativeRouter {
    init {
        System.loadLibrary("memoryroute")
    }

    external fun armCrashLog(path: String)

    external fun setStage(stage: String, backend: String)

    external fun decide(indexPath: String, text: String, query: FloatArray, masked: FloatArray): String

    external fun extract(keyTextsJson: String): String
}
