"""
自定义日志处理器：单文件滚动，只保留最近若干天的日志内容。
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path


class DailyTrimmedFileHandler(logging.FileHandler):
    """
    单文件日志处理器：
    - 只有一个 `.log` 文件，没有后缀
    - 每天最多裁剪一次
    - 按日期块删除过期内容
    """

    def __init__(self, filename, keep_days=7, encoding="utf-8"):
        super().__init__(filename, "a", encoding=encoding)
        self.keep_days = keep_days
        self._last_cleanup_date = ""

    def emit(self, record):
        super().emit(record)
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_cleanup_date:
            self._last_cleanup_date = today
            self._trim_old()

    def _trim_old(self):
        cutoff = (datetime.now() - timedelta(days=self.keep_days)).strftime("%Y-%m-%d")
        path = Path(self.baseFilename)
        if not path.exists():
            return

        try:
            lines = path.read_text(encoding=self.encoding).splitlines(True)
            keep = []
            should_keep_current_block = True
            removed_lines = 0

            for line in lines:
                if re.match(r"^\d{4}-\d{2}-\d{2}\s", line):
                    should_keep_current_block = line[:10] >= cutoff
                    if should_keep_current_block:
                        keep.append(line)
                    else:
                        removed_lines += 1
                else:
                    if should_keep_current_block:
                        keep.append(line)
                    else:
                        removed_lines += 1

            path.write_text("".join(keep), encoding=self.encoding)
            logger = logging.getLogger(__name__)
            logger.info(
                "日志裁剪完成: %s, 保留 >= %s, 保留 %s 行, 删除 %s 行",
                path.name,
                cutoff,
                len(keep),
                removed_lines,
            )
        except Exception as exc:
            try:
                logging.getLogger(__name__).warning("日志裁剪失败: %s", exc)
            except Exception:
                pass
