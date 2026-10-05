"""追加式事件账本：所有状态变化与访问评估都写入哈希链，历史不可改写。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Iterator

GENESIS_HASH = "GENESIS"


def canonical_json(payload: object) -> str:
    """生成稳定排序的 JSON，供哈希与审计使用。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(seq: int, at: str, type_: str, data: dict, prev_hash: str) -> str:
    payload = {"seq": seq, "at": at, "type": type_, "data": data, "prev_hash": prev_hash}
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Event:
    """账本中的一条事件。"""

    seq: int
    at: str
    type: str
    data: dict
    prev_hash: str
    hash: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            seq=int(data["seq"]),
            at=data["at"],
            type=data["type"],
            data=dict(data["data"]),
            prev_hash=data["prev_hash"],
            hash=data["hash"],
        )


class Ledger:
    """只增不改的事件序列，携带防篡改哈希链。"""

    def __init__(self, events: list[Event] | None = None) -> None:
        self._events: list[Event] = list(events or [])
        if not self.verify():
            raise ValueError("事件账本校验失败：哈希链不完整")

    def append(self, type_: str, data: dict, at: str) -> Event:
        seq = len(self._events) + 1
        prev_hash = self._events[-1].hash if self._events else GENESIS_HASH
        event_hash = compute_hash(seq, at, type_, data, prev_hash)
        event = Event(seq=seq, at=at, type=type_, data=data, prev_hash=prev_hash, hash=event_hash)
        self._events.append(event)
        return event

    def verify(self) -> bool:
        prev_hash = GENESIS_HASH
        for expected_seq, event in enumerate(self._events, start=1):
            if event.seq != expected_seq or event.prev_hash != prev_hash:
                return False
            if event.hash != compute_hash(event.seq, event.at, event.type, event.data, event.prev_hash):
                return False
            prev_hash = event.hash
        return True

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def to_list(self) -> list[dict]:
        return [event.to_dict() for event in self._events]

    @classmethod
    def from_list(cls, items: list[dict]) -> "Ledger":
        return cls([Event.from_dict(item) for item in items])
