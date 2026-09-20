"""
轻量兼容层：为旧 skill 提供最小的 AgentScope 响应对象。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ServiceExecStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class ServiceResponse:
    status: ServiceExecStatus
    content: Any = None
    message: str = ""
