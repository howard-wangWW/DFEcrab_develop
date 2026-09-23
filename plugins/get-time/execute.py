"""
获取当前系统时间
"""

import datetime


def execute():
    """获取当前系统时间

    Returns:
        当前时间字符串
    """
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
