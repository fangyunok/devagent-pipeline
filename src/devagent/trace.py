"""结构化日志与全链路 trace。

- logging：标准 logging，格式统一、级别可配置；
- Trace：一次全链路运行的过程记录，落盘为 JSON Lines（每事件一行），
  供评测回溯、耗时分析、跨版本对比使用。开/关由 config.trace_enabled 控制。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

# 统一 logger，模块内用 getLogger(__name__) 复用同一配置
LOGGER = logging.getLogger("devagent")


def configure_logging(level: str = "INFO") -> None:
    """初始化根 logger，重复调用幂等（避免重复 handler）。"""
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level.upper())
    LOGGER.propagate = False


class Trace:
    """一次运行的事件流水，append-only，按需 flush 到 JSON Lines 文件。"""

    def __init__(self, run_id: str, enabled: bool = True):
        self.run_id = run_id
        self.enabled = enabled
        self.events: list[dict[str, Any]] = []
        self._stage_start: dict[str, float] = {}

    def stage_start(self, stage: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self._stage_start[stage] = time.monotonic()
        self.events.append({"run_id": self.run_id, "event": "stage_start",
                            "stage": stage, "ts": time.time(), **fields})

    def stage_end(self, stage: str, **fields: Any) -> None:
        if not self.enabled:
            return
        start = self._stage_start.pop(stage, None)
        duration_ms = None
        if start is not None:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
        self.events.append({"run_id": self.run_id, "event": "stage_end",
                            "stage": stage, "ts": time.time(),
                            "duration_ms": duration_ms, **fields})

    def record(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self.events.append({"run_id": self.run_id, "event": event,
                            "ts": time.time(), **fields})

    def write(self, path: str | Path) -> None:
        """把事件流落盘为 JSON Lines；未启用时跳过。"""
        if not self.enabled or not self.events:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for ev in self.events:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def stage_durations_ms(self) -> dict[str, float]:
        """按阶段聚合耗时（毫秒），供报告对比。"""
        durations: dict[str, float] = {}
        for ev in self.events:
            if ev["event"] == "stage_end" and ev.get("duration_ms") is not None:
                durations[ev["stage"]] = ev["duration_ms"]
        return durations
