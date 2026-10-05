"""校企联合实验室成果协同的领域错误类型。"""

from __future__ import annotations


class DomainError(Exception):
    """领域操作失败的基类。"""


class ValidationError(DomainError):
    """输入不满足领域约束。"""


class NotFoundError(DomainError):
    """引用的对象不存在。"""


class StateError(DomainError):
    """当前状态不允许执行该操作。"""


class ConflictError(DomainError):
    """标识冲突或重复提交。"""
