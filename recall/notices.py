"""面向家庭的通知：修订只追加，旧内容永久保留。

已售家庭需要能核对"当时看到的通知原文"，因此通知的每次修订
都生成新修订号，历史修订不可变、不可删除；当前内容只是指向
最新修订，绝不覆盖旧内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NoticeRevision:
    """通知的一次修订，内容不可变。"""

    revision: int
    title: str
    body: str
    issued_by: str
    issued_at: datetime


class Notice:
    """一条通知及其全部修订历史。"""

    def __init__(self, notice_id: str, order_id: str, first: NoticeRevision) -> None:
        self.notice_id = notice_id
        self.order_id = order_id
        self._revisions: list[NoticeRevision] = [first]

    @property
    def revisions(self) -> tuple[NoticeRevision, ...]:
        return tuple(self._revisions)

    def current(self) -> NoticeRevision:
        return self._revisions[-1]

    def revise(self, *, title: str, body: str, issued_by: str, at: datetime) -> NoticeRevision:
        revision = NoticeRevision(
            revision=len(self._revisions) + 1,
            title=title,
            body=body,
            issued_by=issued_by,
            issued_at=at,
        )
        self._revisions.append(revision)
        return revision


class NoticeBoard:
    """通知的发布与查询。"""

    def __init__(self) -> None:
        self._notices: dict[str, Notice] = {}
        self._sequence = 0

    def publish(
        self,
        order_id: str,
        *,
        title: str,
        body: str,
        issued_by: str,
        at: datetime,
    ) -> Notice:
        self._sequence += 1
        first = NoticeRevision(1, title, body, issued_by, at)
        notice = Notice(f"NTC-{self._sequence:04d}", order_id, first)
        self._notices[notice.notice_id] = notice
        return notice

    def get(self, notice_id: str) -> Notice:
        try:
            return self._notices[notice_id]
        except KeyError:
            raise KeyError(f"通知不存在：{notice_id}") from None
