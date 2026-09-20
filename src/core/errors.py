"""
DFEcrab 统一错误处理体系
参考 LibreChat mcp-server.js 的 userError + errorToolResult + 候选建议模式

设计原则:
- UserError: 用户可理解的错误，带候选建议和可操作的修复提示
- SystemError: 系统错误，不暴露堆栈给用户但记录完整日志
- error_response: 标准化错误响应格式，所有接口统一
- 全局异常捕获: 未捕获异常有日志记录，避免静默失败
"""

from __future__ import annotations

import sys
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dfecrab.errors")


# ══════════════════════════════════════════════════════════════════════════════
# 错误类型定义
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class UserError(Exception):
    """用户可理解的错误 — 不暴露堆栈，提供候选建议和修复提示

    参考 LibreChat userError 模式:
    - 对用户友好的错误描述
    - 候选建议列表（candidates）
    - 可操作的修复提示（build_hint）
    """
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Any] = field(default_factory=list)
    build_hint: str = ""
    status_code: int = 400

    def __post_init__(self):
        super().__init__(self.message)


@dataclass
class SystemError(Exception):
    """系统错误 — 不暴露给用户，只记录日志"""
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    original_error: Optional[Exception] = None

    def __post_init__(self):
        super().__init__(self.message)


# ══════════════════════════════════════════════════════════════════════════════
# 标准化错误响应
# ══════════════════════════════════════════════════════════════════════════════

def error_response(error: Exception) -> Dict[str, Any]:
    """标准化错误响应格式

    所有接口（HTTP/WS/gRPC）统一使用此函数生成错误响应。

    Args:
        error: 异常对象

    Returns:
        标准化错误字典:
        {
            "success": False,
            "isError": True,
            "error": "错误描述",
            "details": {...},
            "candidates": [...],     # 仅 UserError
            "buildHint": "...",      # 仅 UserError
        }
    """
    if isinstance(error, UserError):
        logger.warning(
            f"[UserError] {error.message} "
            f"| candidates={len(error.candidates)} "
            f"| hint={error.build_hint[:80] if error.build_hint else 'N/A'}"
        )
        return {
            "success": False,
            "isError": True,
            "error": error.message,
            "details": error.details,
            "candidates": error.candidates,
            "buildHint": error.build_hint,
            "status_code": error.status_code,
        }

    if isinstance(error, SystemError):
        logger.error(
            f"[SystemError] {error.message}",
            exc_info=error.original_error
        )
        return {
            "success": False,
            "isError": True,
            "error": "系统内部错误，请稍后重试",
            "details": error.details,
            "status_code": 500,
        }

    # 未知异常: 记录完整堆栈，返回通用错误
    logger.error(f"[UnhandledError] {type(error).__name__}: {error}")
    logger.error(traceback.format_exc())

    return {
        "success": False,
        "isError": True,
        "error": "系统内部错误，请稍后重试",
        "details": {"error_type": type(error).__name__},
        "status_code": 500,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 全局异常捕获
# ══════════════════════════════════════════════════════════════════════════════

def setup_global_exception_handlers():
    """设置全局未捕获异常处理器

    确保所有未捕获的异常至少被记录到日志中，避免静默失败。
    在 Gateway 启动时调用一次。
    """
    _logger = logging.getLogger("dfecrab")

    def _handle_uncaught(exc_type, exc_value, exc_tb):
        """同步代码未捕获异常处理器"""
        if issubclass(exc_type, KeyboardInterrupt):
            # KeyboardInterrupt 不处理，保持原有行为
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _logger.critical(
            f"[UNCAUGHT] {exc_type.__name__}: {exc_value}",
            exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _handle_uncaught

    logger.info("[Errors] 全局异常处理器已注册")


def setup_asyncio_exception_handler(loop=None):
    """设置 asyncio 事件循环异常处理器

    Args:
        loop: asyncio 事件循环，默认使用当前运行中的循环
    """
    import asyncio

    _logger = logging.getLogger("dfecrab")

    try:
        if loop is None:
            loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[Errors] 无运行中的事件循环，跳过 asyncio 异常处理器")
        return

    def _handler(loop, context):
        msg = context.get("message", "异步异常")
        exception = context.get("exception")
        _logger.error(
            f"[ASYNC_UNCAUGHT] {msg}",
            exc_info=exception
        )

    loop.set_exception_handler(_handler)
    logger.info("[Errors] asyncio 异常处理器已注册")


# ══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════════════════════

def raise_not_found(entity: str, query: Dict[str, Any], candidates: List[Any] = None):
    """抛出"未找到"错误，带候选建议"""
    candidates = candidates or []
    query_str = ", ".join(f"{k}={v}" for k, v in query.items())
    raise UserError(
        message=f"未找到匹配的{entity}",
        details={"query": query},
        candidates=candidates,
        build_hint=f"请检查查询条件: {query_str}",
        status_code=404,
    )


def raise_ambiguous(entity: str, query: Dict[str, Any], candidates: List[Any]):
    """抛出"多条结果"错误，提供候选列表"""
    query_str = ", ".join(f"{k}={v}" for k, v in query.items())
    raise UserError(
        message=f"匹配到多条{entity}，请补充查询条件",
        details={"query": query},
        candidates=candidates,
        build_hint=f"使用更精确的条件: {query_str}",
        status_code=400,
    )


def raise_validation_error(field: str, value: Any, reason: str = ""):
    """抛出"参数校验"错误"""
    detail = {"field": field, "value": value}
    if reason:
        detail["reason"] = reason
    raise UserError(
        message=f"参数校验失败: {field}",
        details=detail,
        build_hint=f"请提供有效的 {field} 参数" + (f" ({reason})" if reason else ""),
        status_code=400,
    )