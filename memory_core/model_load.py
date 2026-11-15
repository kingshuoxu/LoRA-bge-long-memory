"""基座和嵌入不能同时用 accelerate 的 meta 设备初始化。"""
from __future__ import annotations

import threading

LOAD_LOCK = threading.Lock()
