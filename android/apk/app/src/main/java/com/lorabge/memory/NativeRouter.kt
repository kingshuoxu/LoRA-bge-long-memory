package com.lorabge.memory

object NativeRouter {
    init {
        System.loadLibrary("memoryroute")
    }

    external fun decide(indexPath: String, text: String, query: FloatArray, masked: FloatArray): String

    external fun extract(keyTextsJson: String): String
}
