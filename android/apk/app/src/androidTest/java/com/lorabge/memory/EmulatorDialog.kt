package com.lorabge.memory

import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice

/** The default emulator image can cover the UI with a nested-virtualization warning. */
internal fun dismissEmulatorOverlays(device: UiDevice) {
    repeat(3) {
        try {
            val nested = device.findObject(By.textContains("nested virtualization"))
            val never = device.findObject(By.textContains("Never show this again"))
            if (nested == null && never == null) return
            never?.click()
            device.findObject(By.text("OK"))?.click()
        } catch (_: androidx.test.uiautomator.StaleObjectException) {
            return
        }
        Thread.sleep(400)
    }
}
