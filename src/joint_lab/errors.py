"""领域错误类型。"""


class DomainError(Exception):
    """违反协同业务规则。"""


class NotFound(DomainError):
    """引用的对象不存在。"""


class ConflictError(DomainError):
    """状态、并发或唯一性冲突。"""
