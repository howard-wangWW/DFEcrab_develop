"""
时间解析模块 - 将自然语言时间描述转换为具体日期。
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

DAY_KEYWORDS = {
    "大前天": -3,
    "前天": -2,
    "昨天": -1,
    "今天": 0,
    "今日": 0,
    "本日": 0,
    "明日": 1,
    "明天": 1,
    "后天": 2,
}


def _get_monday(today: datetime) -> datetime:
    return today - timedelta(days=today.weekday())


def _get_sunday(today: datetime) -> datetime:
    return _get_monday(today) + timedelta(days=6)


def _resolve_md(month: int, day: int, today: datetime) -> str:
    year = today.year
    if (month > today.month) or (month == today.month and day > today.day):
        year -= 1
    return f"{year}-{month:02d}-{day:02d}"


def _resolve_day(day: int, today: datetime) -> str:
    year = today.year
    month = today.month
    if day > today.day:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return f"{year}-{month:02d}-{day:02d}"


def _chinese(dt: datetime) -> str:
    return f"{dt.year}年{dt.month}月{dt.day}日"


def parse_time(text: str, reference_time: Optional[datetime] = None) -> Tuple[str, Dict]:
    if reference_time is None:
        reference_time = datetime.now()
    today = reference_time

    result = {
        "dates": [],
        "date_range": None,
        "resolved": False,
        "date_descriptions": [],
    }
    placeholders = []
    current_text = text

    def _replace_ymd(match):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        dt = datetime(year, month, day)
        date_str = _chinese(dt)
        date_val = f"{year:04d}-{month:02d}-{day:02d}"
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, date_val, f"日期 -> {date_str}"))
        return placeholder

    current_text = re.sub(
        r"(?<!\d)(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        _replace_ymd,
        current_text,
    )

    def _replace_md(match):
        month, day = int(match.group(1)), int(match.group(2))
        resolved = _resolve_md(month, day, today)
        dt = datetime.strptime(resolved, "%Y-%m-%d")
        date_str = _chinese(dt)
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, resolved, f"{month}月{day}日 -> {date_str}"))
        return placeholder

    current_text = re.sub(
        r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日(?!\s*[\d年])",
        _replace_md,
        current_text,
    )

    def _replace_last_weekday(match):
        wd = match.group(2) or match.group(1)
        target_wd = WEEKDAY_NAMES[wd]
        dt = (_get_monday(today) - timedelta(days=7)) + timedelta(days=target_wd)
        date_str = _chinese(dt)
        date_val = dt.strftime("%Y-%m-%d")
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, date_val, f"上周{wd} -> {date_str}"))
        return placeholder

    current_text = re.sub(r"上(周|星期)([一二三四五六日天])", _replace_last_weekday, current_text)

    def _replace_this_weekday(match):
        wd = match.group(2) or match.group(1)
        target_wd = WEEKDAY_NAMES[wd]
        dt = _get_monday(today) + timedelta(days=target_wd)
        date_str = _chinese(dt)
        date_val = dt.strftime("%Y-%m-%d")
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, date_val, f"本周{wd} -> {date_str}"))
        return placeholder

    current_text = re.sub(r"本(周|星期)([一二三四五六日天])", _replace_this_weekday, current_text)

    def _replace_week(match):
        kw = match.group(0)
        if kw == "本周":
            monday = _get_monday(today)
            sunday = _get_sunday(today)
        else:
            monday = _get_monday(today) - timedelta(days=7)
            sunday = _get_sunday(today) - timedelta(days=7)
        date_str = f"{_chinese(monday)}~{_chinese(sunday)}"
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, None, f"{kw} -> {date_str}"))
        return placeholder

    current_text = re.sub(r"(上周|本周)(?!\s*[一二三四五六日天])", _replace_week, current_text)

    def _replace_dayonly(match):
        day = int(match.group(1))
        resolved = _resolve_day(day, today)
        dt = datetime.strptime(resolved, "%Y-%m-%d")
        date_str = _chinese(dt)
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, resolved, f"{day}日 -> {date_str}"))
        return placeholder

    current_text = re.sub(r"(?<!\d)(\d{1,2})\s*日(?!\s*[\d年])", _replace_dayonly, current_text)

    def _replace_daykeyword(match):
        kw = match.group(0)
        offset = DAY_KEYWORDS[kw]
        if offset > 0:
            return kw
        dt = today + timedelta(days=offset)
        date_str = _chinese(dt)
        date_val = dt.strftime("%Y-%m-%d")
        placeholder = f"\x00DATE_{len(placeholders)}\x00"
        placeholders.append((placeholder, date_str, date_val, f"{kw} -> {date_str}"))
        return placeholder

    current_text = re.sub(r"(大前天|前天|昨天|今天|今日|本日|明天|明日|后天)", _replace_daykeyword, current_text)

    for placeholder, final_text, date_val, desc in placeholders:
        current_text = current_text.replace(placeholder, final_text, 1)
        if date_val:
            result["dates"].append(date_val)
            result["resolved"] = True
        elif "~" in final_text:
            parts = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", final_text)
            if len(parts) >= 2:
                start = f"{parts[0][0]}-{int(parts[0][1]):02d}-{int(parts[0][2]):02d}"
                end = f"{parts[1][0]}-{int(parts[1][1]):02d}-{int(parts[1][2]):02d}"
                result["dates"].extend([start, end])
                result["date_range"] = [start, end]
                result["resolved"] = True
        result["date_descriptions"].append(desc)

    result["dates"] = sorted(set(result["dates"]))
    if result["dates"]:
        if result["date_range"]:
            result["time_type"] = "date_range"
            start = datetime.strptime(result["date_range"][0], "%Y-%m-%d")
            end = datetime.strptime(result["date_range"][1], "%Y-%m-%d")
            result["start_time"] = start.strftime("%Y-%m-%d 00:00:00")
            result["end_time"] = end.strftime("%Y-%m-%d 23:59:59")
        else:
            result["time_type"] = "single_day"
            dt = datetime.strptime(sorted(result["dates"])[0], "%Y-%m-%d")
            result["start_time"] = dt.strftime("%Y-%m-%d 00:00:00")
            result["end_time"] = dt.strftime("%Y-%m-%d 23:59:59")
    else:
        result["time_type"] = "not_time_related"
        result["start_time"] = None
        result["end_time"] = None

    result["description"] = "；".join(result["date_descriptions"]) if result["date_descriptions"] else ""
    return current_text, result


def get_time_context(reference_time: Optional[datetime] = None) -> str:
    if reference_time is None:
        reference_time = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"[当前时间]\n当前日期: {_chinese(reference_time)} {weekdays[reference_time.weekday()]}"
