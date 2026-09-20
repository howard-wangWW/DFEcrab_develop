"""
工具函数库 - 提供 Agent 可以调用的各种工具
每个工具都有详细的描述，方便 DeepSeek Agent 理解和调用
"""

import json
import requests
from datetime import datetime
from typing import Dict, Any, List
from .config import config


# ============== 通用服务调用函数 ==============

def call_service_api(url: str, payload: Dict[str, Any], tool_name: str) -> str:
    """
    通用服务 API 调用函数
    """
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        # 打印调用信息
        try:
            payload_preview = json.dumps(payload, ensure_ascii=False)
        except Exception:
            payload_preview = str(payload)
        print(f"[服务调用] {tool_name} POST {url} payload={payload_preview}")

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        status = response.status_code
        print(f"[服务返回] {tool_name} HTTP {status}")

        if status == 200:
            # 尝试解析 JSON
            try:
                result_data = response.json()
                result_preview = json.dumps(result_data, ensure_ascii=False)
            except Exception:
                result_preview = response.text

            # 截断输出以避免日志过长
            truncated = result_preview if len(result_preview) <= 2000 else result_preview[:2000] + '...'
            print(f"     {tool_name} 查询成功，返回内容预览: {truncated}")
            return json.dumps(result_data, ensure_ascii=False) if status == 200 and result_preview else result_preview
        else:
            detailed_error = f"{tool_name} API 错误 (状态码: {status}): {response.text}"
            print(f"      {detailed_error}")
            return f"查询失败 ({tool_name} 状态码: {status})。错误详情: {response.text}"

    except Exception as e:
        error_msg = f"调用 {tool_name} 时发生异常: {str(e)}"
        print(f"     {error_msg}")
        return f"查询时发生技术错误: {str(e)}"


def search_taizhang(station: str, line_name: str = "", bus_name: str = "") -> str:
    """
    查询站点台账信息。
    """
    print(f"[工具执行] search_taizhang(station='{station}', line_name='{line_name}', bus_name='{bus_name}')")
    payload = {
        "station": station,
        "line_name": line_name,
        "bus_name": bus_name
    }
    return call_service_api(config.TAIZHANG_SERVICE_URL, payload, "search_taizhang")

# def search_livework_ticket(station: str, line_name: str) -> str:
#     """
#     查询站点livework票信息。
#     """
#     print(f"[工具执行] search_livework_ticket(station='{station}', line_name='{line_name}')")
#     payload = {
#         "station": station,
#         "line_name": line_name
#     }
#     return call_service_api(config.SEARCH_LIVEWORK_TICKET_SERVICE_URL, payload, "search_livework_ticket")

def search_diaodulog(date: str, station: str) -> str:
    """
    根据信号日期、站点名称，搜索调度日志。
    """
    print(f"[工具执行] search_diaodulog(date='{date}', station='{station}')")
    payload = {
        "date": date,
        "station": station
    }
    return call_service_api(config.DIAODULOG_SERVICE_URL, payload, "search_diaodulog")


def search_caozuotickets(station: str = "", line_name: str = "", queries: List[Dict[str, str]] = None) -> str:
    """
    查询操作票信息。支持单条 station/line_name 参数，也支持批量 queries 参数。
    """
    def _normalize_station_name(name: str) -> str:
        if not name:
            return name
        name = name.strip()
        if name.endswith("变电站"):
            return name
        if name.endswith("站"):
            return name[:-1] + "变电站"
        return name + "变电站"

    if queries and isinstance(queries, list):
        results = []
        for query in queries:
            if not isinstance(query, dict):
                continue
            station_value = query.get("station", "")
            line_name_value = query.get("line_name", "")
            print(f"[工具执行] search_caozuotickets(station='{station_value}', line_name='{line_name_value}')")
            payload = {
                "station": _normalize_station_name(station_value),
                "line_name": line_name_value
            }
            result = call_service_api(config.CAOZUO_TICKETS_SERVICE_URL, payload, "search_caozuotickets")
            results.append(result)

        if len(results) == 1:
            return results[0]
        return json.dumps(results, ensure_ascii=False)

    print(f"[工具执行] search_caozuotickets(station='{station}', line_name='{line_name}')")
    payload = {
        "station": _normalize_station_name(station),
        "line_name": line_name
    }
    return call_service_api(config.CAOZUO_TICKETS_SERVICE_URL, payload, "search_caozuotickets")


def search_livework_ticket(station: str, line_name: str) -> str:
    """
    查询带电作业工单信息。
    """
    print(f"[工具执行] search_livework_ticket(station='{station}', line_name='{line_name}')")
    payload = {
        "station": station,
        "line_name": line_name
    }
    return call_service_api(config.LIVEWORK_TICKETS_SERVICE_URL, payload, "search_livework_ticket")


# ============== 工具注册表 ==============
# 定义工具的元数据，供 DeepSeek Agent 使用

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_taizhang",
            "description": "查询站点台账信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "station": {
                        "type": "string",
                        "description": "站点名称，例如：光明站"
                    },
                    "line_name": {
                        "type": "string",
                        "description": "馈线名称"
                    },
                    "bus_name": {
                        "type": "string",
                        "description": "母线名称"
                    }
                },
                "required": ["station","line_name","bus_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_diaodulog",
            "description": "根据信号日期、站点名称，搜索调度日志。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "信号日期"
                    },
                    "station": {
                        "type": "string",
                        "description": "站点名称"
                    }
                },
                "required": ["date", "station"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_livework_ticket",
            "description": "根据站点名称、馈线名称，搜索带电作业工单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "station": {
                        "type": "string",
                        "description": "站点名称"
                    },
                    "line_name": {
                        "type": "string",
                        "description": "馈线名称"
                    }
                },
                "required": ["station", "line_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_caozuotickets",
            "description": "查询操作票信息。支持单条 station/line_name 参数或批量 queries 参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "description": "批量查询条件列表，可包含多条馈线，每项包含 station 和 line_name。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "station": {
                                    "type": "string",
                                    "description": "站点名称，例如：雅苑站"
                                },
                                "line_name": {
                                    "type": "string",
                                    "description": "馈线名称，例如：F14"
                                }
                            },
                            "required": ["station", "line_name"]
                        }
                    },
                    "station": {
                        "type": "string",
                        "description": "站点名称，例如：雅苑站"
                    },
                    "line_name": {
                        "type": "string",
                        "description": "馈线名称，例如：F14"
                    }
                },
                "required": []
            }
        }
    }
]


# ============== 工具调用映射 ==============
# 将工具名称映射到实际的函数

TOOL_FUNCTIONS = {
    "search_taizhang": search_taizhang,
    "search_diaodulog": search_diaodulog,
    "search_livework_ticket": search_livework_ticket,
    "search_caozuotickets": search_caozuotickets
}


def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """
    执行指定的工具函数

    参数:
        tool_name (str): 工具名称
        tool_args (dict): 工具参数

    返回:
        str: 工具执行结果
    """
    if tool_name not in TOOL_FUNCTIONS:
        return f"错误: 未知的工具 '{tool_name}'"

    try:
        func = TOOL_FUNCTIONS[tool_name]
        try:
            args_preview = json.dumps(tool_args, ensure_ascii=False)
        except Exception:
            args_preview = str(tool_args)
        print(f"[execute_tool] 调用 {tool_name} 参数: {args_preview}")
        result = func(**tool_args)
        try:
            result_preview = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception:
            result_preview = str(result)
        truncated = result_preview if len(result_preview) <= 2000 else result_preview[:2000] + '...'
        print(f"[execute_tool] {tool_name} 返回内容预览: {truncated}")
        return result
    except Exception as e:
        error_msg = f"执行工具 '{tool_name}' 时发生错误: {str(e)}"
        print(f"  {error_msg}")
        return error_msg
