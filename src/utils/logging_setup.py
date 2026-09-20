"""
统一日志配置模块

为各服务提供一致的日志初始化：
- 统一格式、统一文件滚动（DailyTrimmedFileHandler，单文件保留近 7 天）
- 启动时自动写入 Banner（服务名 + PID + 启动时间），重启可明确区分
- 可选输出到控制台
- 压制第三方库（httpx/kazoo/httpcore）噪音

使用示例：
    from src.utils.logging_setup import setup_root_logging, setup_service_logging

    setup_root_logging(LOG_DIR / "gateway_grpc.log", service_name="gateway")
    setup_service_logging("dfecrab.manager", LOG_DIR / "manager_agent.log")
    setup_service_logging("dfecrab.react", LOG_DIR / "worker_agents.log")
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from src.utils.log_handler import DailyTrimmedFileHandler

# 需要压制的第三方库（避免污染业务日志）
NOISY_LIBRARIES = ("httpx", "kazoo", "httpcore")

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _ensure_dir(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)


def _build_banner_text(service_name: str) -> str:
    """构建启动 Banner 文本（服务名 + PID + 启动时间）。"""
    return (
        f"\n{'=' * 60}\n"
        f"# {service_name} | PID: {os.getpid()} | 启动时间: "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'=' * 60}\n"
    )


def _write_banner(logger: logging.Logger, service_name: str, log_file: Path) -> None:
    """向目标 logger 写入启动 Banner。"""
    logger.info("%s", _build_banner_text(service_name))


def write_startup_banner(log_file: Union[str, Path], service_name: str) -> None:
    """直接向日志文件追加启动 Banner（用于子进程/独立进程，如知识库 API）。

    这类服务的日志是重定向到文件句柄的，无法通过 logger 写入，
    因此在启动子进程前手动把 Banner 追加到文件。
    """
    log_file = Path(log_file)
    _ensure_dir(log_file)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(_build_banner_text(service_name))
        f.flush()


def _suppress_noisy_libraries(level: int = logging.WARNING) -> None:
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(level)


def setup_root_logging(
    log_file: Union[str, Path],
    service_name: str = "gateway",
    level: int = logging.INFO,
    log_to_console: bool = True,
) -> logging.Logger:
    """配置 ROOT logger（面向主进程 / Gateway）。

    Args:
        log_file: 主日志文件路径
        service_name: 启动 Banner 展示的服务名
        level: 日志级别
        log_to_console: 是否同时输出到 stdout

    Returns:
        root logger
    """
    log_file = Path(log_file)
    _ensure_dir(log_file)

    handlers = [DailyTrimmedFileHandler(log_file, keep_days=7, encoding="utf-8")]
    if log_to_console:
        handlers.append(logging.StreamHandler(sys.stdout))

    # 仅当 root 尚未配置时才 basicConfig，避免重复叠加 handler
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format=_LOG_FORMAT,
            handlers=handlers,
        )

    root = logging.getLogger()
    _write_banner(root, service_name, log_file)
    _suppress_noisy_libraries()
    return root


def setup_service_logging(
    name: str,
    log_file: Union[str, Path],
    level: int = logging.INFO,
    log_to_console: bool = True,
) -> logging.Logger:
    """配置独立的命名 logger（面向各业务模块，如 dfecrab.manager / dfecrab.react）。

    Args:
        name: logger 名称
        log_file: 该模块的日志文件路径
        level: 日志级别
        log_to_console: 是否同时输出到 stdout

    Returns:
        配置好的命名 logger
    """
    log_file = Path(log_file)
    _ensure_dir(log_file)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 防止重复添加 handler（服务重启 / 多入口时保持幂等）
    if not logger.handlers:
        fmt = logging.Formatter(_LOG_FORMAT)
        fh = DailyTrimmedFileHandler(log_file, keep_days=7, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        if log_to_console:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            logger.addHandler(sh)
        logger.propagate = False

    _write_banner(logger, name, log_file)
    _suppress_noisy_libraries()
    return logger
