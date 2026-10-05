"""领域事件的序列化：支持枚举、frozenset、嵌套值对象与 JSON 往返。"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any


def to_jsonable(value: Any) -> Any:
    """把领域值转换为可 JSON 序列化的结构。"""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, frozenset) or isinstance(value, set):
        return sorted(to_jsonable(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value


def dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True)


def event_to_envelope(event: Any) -> dict[str, Any]:
    """把事件转换为带类型标记的持久化信封。"""
    if not is_dataclass(event):
        raise TypeError("只有领域事件可以序列化")
    return {
        "type": type(event).__name__,
        "seq": event.seq,
        "data": {
            item.name: to_jsonable(getattr(event, item.name))
            for item in fields(event)
            if item.name != "seq"
        },
    }
