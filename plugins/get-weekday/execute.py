"""
获取今天是星期几
"""

import datetime


def execute(date_str: str = None):
    """获取指定日期或今天是星期几

    Args:
        date_str: 日期字符串，格式为 YYYY-MM-DD，如果为空则使用今天

    Returns:
        星期几
    """
    if date_str:
        date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    else:
        date = datetime.datetime.now()

    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return weekdays[date.weekday()]
