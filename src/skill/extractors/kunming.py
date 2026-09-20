"""
kunming.py - 昆明配网确定性参数提取器（ParamGuard 内置件）

把 legacy worker（services/agent_service/agent_service_grpc.py
`_code_assist_kunming_classifier`）里已在现场验证过的"代码主导分类 + 时间解析"
收敛到此处，作为弱模型参数填错时的兜底：
    - 分类（category）：正则/关键词确定性判定
    - 时间（startTime/endTime/date）：src.utils.time_parser 解析自然语言时间
    - 人名 / 局名：正则提取
    - endpoint / params：由 category 映射，模型不用碰

修复策略（与 param_guard 契约一致）：
    模型填对的字段原样保留；填错/缺失且代码能确定性推导的字段才替换。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from src.utils.time_parser import parse_time
from src.skill.param_guard import register_extractor

# ==================== 昆明业务常量 ====================

VALID_CATEGORIES = (5, 6, 7, 8, 9, 10, 11, 12, 13)

# category → API endpoint（与 kunming_api / DM-kunming.py 对齐）
CATEGORY_ENDPOINT = {
    6: "tiaozha",
    7: "zaohui",
    8: "check_qualification",
    9: "get_abnormal_signals",
    10: "today-chengqu-1h-trip",
    11: "today-baogongdian-trip",
    12: "today-bureau-trip",
    13: "overload",
}

# kunming_api 已知接口（用于合法性校验，非映射目标）
ALL_ENDPOINTS = set(CATEGORY_ENDPOINT.values()) | {"meta", "svg_groups", "query", "generate-excel"}

# kunming_api params 允许的键（过滤模型瞎编的键，如 {'a': '1'}）
ALLOWED_PARAM_KEYS = {
    "startTime", "endTime", "date", "personName",
    "bureau", "mode", "area", "days", "load_threshold", "sql",
}

DATETIME_FIELDS = {"startTime", "endTime"}
DATE_FIELDS = {"date"}

TIME_WORDS = ["今天", "今日", "昨天", "前天", "明天", "这周", "上周", "这月", "上月", "今年", "去年"]
TRIP_WORDS = ["跳闸", "跳了", "跳停"]
BUREAU_PATTERN = r'([\u4e00-\u9fa5]{2,4}供电局|[\u4e00-\u9fa5]{2,3}局)'


def _now() -> datetime:
    return datetime.now()


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _date_valid(value: Any, now: datetime) -> bool:
    """日期字段合法性：格式正确、可解析、年份与当前年份相差不超过 1 年。

    （现场实测：模型把"今日"填成 2023-04-10，年份校验即可判定无效并触发修复）
    """
    if not isinstance(value, str) or not value.strip():
        return False
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T]\d{2}:\d{2}:\d{2})?$", value.strip())
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if abs(year - now.year) > 1:
        return False
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


def _extract_person_name(message: str) -> str:
    """受令资格查询的人名提取（多种语序，精确匹配优先）—— 移植 legacy 逻辑。"""
    patterns = [
        r'([\u4e00-\u9fa5]{2,3})是否具备受令资格',
        r'查看\s*([\u4e00-\u9fa5]{2,3})\s*是否具备受令资格',
        r'(?:查一下|查询)\s*([\u4e00-\u9fa5]{2,4})\s+的\s+受令资格',
        r'查\s*([\u4e00-\u9fa5]{2,4})\s+的\s+受令资格',
        r'([\u4e00-\u9fa5]{2,4})\s*受令资格',
        r'受令资格[^\u4e00-\u9fa5]*([\u4e00-\u9fa5]{2,4})',
    ]
    for pattern in patterns:
        m = re.search(pattern, message)
        if m:
            return m.group(1)
    return ""


def classify(message: str) -> Dict[str, Any]:
    """代码主导分类 + 粗提取参数（移植 legacy `_code_assist_kunming_classifier` 阶段1）。

    分类优先级：12=某局跳闸 > 11=保供电跳闸 > 10=城区一小时跳闸 > 9=异常信号统计
                > 8=受令资格 > 13=重过载 > 7=早会材料 > 6=跳闸统计 > 5=其他对话
    """
    params: Dict[str, Any] = {
        "query": message,
        "category": 5,
        "startTime": "",
        "endTime": "",
        "personName": "",
        "date": "",
        "bureau": "",
        "mode": "",
        "area": "",
        "days": 3,
        "load_threshold": 80,
    }
    message = message or ""
    has_trip = any(tw in message for tw in TRIP_WORDS)

    def _strip_time_prefix(text: str) -> str:
        for tw in TIME_WORDS:
            if text.startswith(tw):
                return text[len(tw):].strip()
        return text

    cleaned = _strip_time_prefix(message)
    bureau_match = re.search(BUREAU_PATTERN, cleaned)

    if bureau_match and (has_trip or "统计" in message or "情况" in message):
        # 12=某局跳闸
        params["category"] = 12
        params["bureau"] = bureau_match.group(1)
    elif "保供电" in message and (has_trip or "统计" in message):
        params["category"] = 11
    elif ("城区一小时" in message or "1小时" in message or "一小时" in message) and (
        has_trip or "线路" in message or "情况" in message
    ):
        params["category"] = 10
    elif "异常信号" in message:
        params["category"] = 9
    elif "受令资格" in message or "调度受令" in message:
        params["category"] = 8
        name = _extract_person_name(message)
        if name:
            params["personName"] = name
    elif "重过载" in message or "过载" in message:
        params["category"] = 13
        params["load_threshold"] = 80
        if "汇总" in message or "全局" in message or "全区" in message:
            params["mode"] = "total_count"
        elif "趋势" in message or "变化" in message or "最近" in message:
            params["mode"] = "trend"
            days_match = re.search(r'最近(\d+)天', message)
            params["days"] = int(days_match.group(1)) if days_match else 3
        elif "详细" in message or "列表" in message:
            params["mode"] = "detail"
        elif "最多" in message or "排行" in message or "top" in message.lower():
            params["mode"] = "top_feeders"
        else:
            if bureau_match:
                params["mode"] = "area_count"
                params["area"] = bureau_match.group(1)
            else:
                params["mode"] = "total_count"
    elif "早会材料" in message:
        params["category"] = 7
    elif has_trip:
        params["category"] = 6

    # 时间解析（今日/昨天/本周/本月… → 具体日期；模型不需要知道今天几号）
    _, time_info = parse_time(message)
    if time_info.get("resolved"):
        if time_info.get("start_time"):
            params["startTime"] = time_info["start_time"]
        if time_info.get("end_time"):
            params["endTime"] = time_info["end_time"]
        if time_info.get("dates"):
            params["date"] = time_info["dates"][0]

    return params


def build_api_call(cls: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """分类结果 → (endpoint, params)。"""
    category = cls.get("category", 5)
    endpoint = CATEGORY_ENDPOINT.get(category)
    if not endpoint:
        return "", {}

    params: Dict[str, Any] = {}
    if category in (6, 7, 10, 11):
        if cls.get("startTime"):
            params["startTime"] = cls["startTime"]
        if cls.get("endTime"):
            params["endTime"] = cls["endTime"]
    elif category == 8:
        if cls.get("personName"):
            params["personName"] = cls["personName"]
    elif category == 9:
        if cls.get("date"):
            params["date"] = cls["date"]
    elif category == 12:
        if cls.get("bureau"):
            params["bureau"] = cls["bureau"]
    elif category == 13:
        for key in ("mode", "area"):
            if cls.get(key):
                params[key] = cls[key]
        params["days"] = cls.get("days", 3)
        params["load_threshold"] = cls.get("load_threshold", 80)
    return endpoint, params


# ==================== ParamGuard 提取器实现 ====================


def _extract_classifier(args: Dict[str, Any], message: str) -> Dict[str, Any]:
    now = _now()
    cls = classify(message)
    invalid: List[str] = []
    repair: Dict[str, Any] = {}

    # 分类：模型填无效 或 与代码确定性分类不一致 → 以代码为准
    cat = args.get("category")
    code_cat = cls.get("category", 5)
    cat_ok = isinstance(cat, int) and cat in VALID_CATEGORIES
    if (not cat_ok) or (code_cat != 5 and cat != code_cat):
        invalid.append("category")
        repair["category"] = code_cat
    eff_cat = code_cat if (code_cat != 5 and cat != code_cat) else (cat if cat_ok else code_cat)

    # 时间字段：仅"需要时间"的类别（6/7/10/11）参与修复/校验，
    #   避免给 category=6 的查询凭空补一个用不到的 date 之类（保持强模型零干预）。
    if eff_cat in (6, 7, 10, 11):
        for field in ("startTime", "endTime"):
            code_val = cls.get(field) or ""
            cur = args.get(field)
            if code_val:
                if cur != code_val:
                    invalid.append(field)
                    repair[field] = code_val
            elif not _date_valid(cur, now) and not _is_empty(cur):
                invalid.append(field)

    # date（异常信号统计，类别9）
    code_date = cls.get("date") or ""
    cur_date = args.get("date")
    if eff_cat == 9:
        if code_date and cur_date != code_date:
            invalid.append("date")
            repair["date"] = code_date
    elif code_date and not _is_empty(cur_date) and cur_date != code_date:
        # 模型主动填了日期但与代码解析不一致 → 以代码为准
        invalid.append("date")
        repair["date"] = code_date

    # 人名（受令资格）
    if eff_cat == 8:
        code_name = cls.get("personName") or ""
        if code_name and args.get("personName") != code_name:
            invalid.append("personName")
            repair["personName"] = code_name

    # 局名（某局跳闸）
    if eff_cat == 12:
        code_bureau = cls.get("bureau") or ""
        if code_bureau and args.get("bureau") != code_bureau:
            invalid.append("bureau")
            repair["bureau"] = code_bureau

    # 模式（重过载）
    if eff_cat == 13:
        code_mode = cls.get("mode") or ""
        if code_mode and args.get("mode") != code_mode:
            invalid.append("mode")
            repair["mode"] = code_mode

    return {"invalid": invalid, "repair": repair}


def _extract_api(args: Dict[str, Any], message: str) -> Dict[str, Any]:
    now = _now()
    cls = classify(message)
    code_endpoint, code_params = build_api_call(cls)
    invalid: List[str] = []
    repair: Dict[str, Any] = {}

    endpoint_raw = args.get("endpoint")
    endpoint = endpoint_raw.strip().lower() if isinstance(endpoint_raw, str) else ""

    if code_endpoint:
        if endpoint != code_endpoint:
            # 代码分类明确且与模型不一致 → endpoint + params 整体以代码为准
            invalid.append("endpoint")
            repair["endpoint"] = code_endpoint
            if code_params:
                invalid.append("params")
                repair["params"] = dict(code_params)
            return {"invalid": invalid, "repair": repair}

        # endpoint 一致 → 逐字段校验模型 params（日期有效性 / 缺失 / 键合法性）
        raw_params = args.get("params") if isinstance(args.get("params"), dict) else {}
        fixed = {k: v for k, v in raw_params.items() if k in ALLOWED_PARAM_KEYS}
        changed = set(raw_params.keys()) != set(fixed.keys())
        for key, code_val in code_params.items():
            cur = fixed.get(key)
            if key in DATETIME_FIELDS or key in DATE_FIELDS:
                if not _date_valid(cur, now):
                    fixed[key] = code_val
                    changed = True
            elif _is_empty(cur):
                fixed[key] = code_val
                changed = True
        if changed:
            invalid.append("params")
            repair["params"] = fixed
        return {"invalid": invalid, "repair": repair}

    # 代码无法确定性分类（category=5）→ 只做 endpoint 合法性校验，不强行修
    if endpoint and endpoint not in ALL_ENDPOINTS:
        invalid.append("endpoint")
    return {"invalid": invalid, "repair": repair}


def extract(tool_name: str, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """ParamGuard 提取器入口：按工具名分发。"""
    message = ""
    if isinstance(ctx, dict):
        message = ctx.get("user_message") or ""
    if not message and isinstance(args, dict):
        message = args.get("query") or ""
    if tool_name == "kunming_classifier":
        return _extract_classifier(args, message)
    if tool_name == "kunming_api":
        return _extract_api(args, message)
    return {}


register_extractor("kunming_classifier", extract)
register_extractor("kunming_api", extract)
