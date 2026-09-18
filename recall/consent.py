"""家长同意账本：同意与撤回都只追加记录，当前状态由最新记录决定。

同意按"设备序列号 + 范围"登记，范围通常是功能代码（含付费功能）。
撤回不删除历史，便于在争议时还原"当时是否取得过同意"。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConsentRecord:
    """一次同意或撤回的留痕。"""

    serial: str
    scope: str
    granted: bool
    guardian: str
    recorded_at: datetime


class ConsentBook:
    """只追加的同意账本。"""

    def __init__(self) -> None:
        self._records: list[ConsentRecord] = []

    def record(
        self,
        serial: str,
        scope: str,
        granted: bool,
        *,
        guardian: str,
        at: datetime,
    ) -> ConsentRecord:
        entry = ConsentRecord(serial, scope, granted, guardian, at)
        self._records.append(entry)
        return entry

    def history(self, serial: str, scope: str) -> tuple[ConsentRecord, ...]:
        return tuple(
            entry for entry in self._records if entry.serial == serial and entry.scope == scope
        )

    def is_granted(self, serial: str, scope: str, *, at: datetime | None = None) -> bool:
        """指定时刻（默认当前）是否处于已同意状态。"""
        latest: ConsentRecord | None = None
        for entry in self.history(serial, scope):
            if at is None or entry.recorded_at <= at:
                latest = entry
        return bool(latest and latest.granted)
