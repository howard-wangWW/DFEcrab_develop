"""
重过载数据查询技能 (Reload Data Query)
"""
import argparse
import json
import requests
import time
import sys
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

# ============ 日志打印配置 ============
LOG_PREFIX = "[RELOAD-DATA]"

def log_info(msg: str):
    """打印信息日志"""
    print(f"{LOG_PREFIX} [INFO] {msg}", flush=True)

def log_warn(msg: str):
    """打印警告日志"""
    print(f"{LOG_PREFIX} [WARN] {msg}", flush=True)

def log_error(msg: str):
    """打印错误日志"""
    print(f"{LOG_PREFIX} [ERROR] {msg}", flush=True)

def log_debug(msg: str):
    """打印调试日志"""
    print(f"{LOG_PREFIX} [DEBUG] {msg}", flush=True)

# ============ 技能元数据 ============
SKILL_METADATA = {
    "name": "reload_data_query",
    "description": "查询馈线或配变的重过载数据。当用户询问馈线/线路/配变/变压器的重载、过载、负载率相关问题时自动调用。支持智能时间推断。",
    "parameters": {
        "query_type": {
            "type": "string",
            "description": "查询类型：'feeder' 馈线重过载 或 'transformer' 配变重过载",
            "enum": ["feeder", "transformer"]
        },
        "time_desc": {
            "type": "string",
            "description": "时间描述，如'今天'、'昨天'、'最近7天'、'2025-09-23'等。为空则默认最近24小时",
            "default": ""
        },
        "start_date": {
            "type": "string",
            "description": "开始时间，格式 YYYY-MM-DD HH:mm:ss。如果提供则优先使用",
            "default": ""
        },
        "end_date": {
            "type": "string",
            "description": "结束时间，格式 YYYY-MM-DD HH:mm:ss。如果提供则优先使用",
            "default": ""
        }
    }
}

BASE_URL = "http://172.20.42.72:8080/database"

# ============ Bearer Token 认证 ============
AUTH_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJpYXQiOjE3ODIzNDc3MDA1MzksImV4cCI6MTc4Mjk0NzY0MDUzOSwianRpIjoiY2I3MDliZjMtMWMyOS00YjE2LTgwMDUtNjNkOWYwYmRiOTYwIiwidXNlciI6eyJ1c2VySWQiOjgyMTIsInVzZXJuYW1lIjoid3l5IiwicGFzc3dvcmQiOiJjMmVjYjU3NmE4ZTY0NTlmZmM3N2M1YjY3NjJlYWY1NjI0N2UxMDY4ZmM3NTNhZGQwMjJjMGFkYTNiZTgxODQ3Iiwic2FsdCI6IjZDUTZsV3NRTElPQUZFazlWNG9OIiwiZGVwdElkIjowLCJlbWFpbCI6IiIsIm1vYmlsZSI6IiIsInN0YXR1cyI6MSwiY3JlYXRlVXNlcklkIjoyLCJjcmVhdGVUaW1lIjoxNzgxNTE1MTI4MDAwLCJjaGFuZ2VQYXNzTmV4dCI6Ik4iLCJ0cnlOdW1iZXIiOjAsInVwZGF0ZVBhc3NUaW1lIjoxNzgxNTE1MjQxMDAwLCJhcmVhSWQiOiIiLCJkZXNjcmlwdGlvbiI6IiJ9fQ"
    ".5isGLshq8kYbGl1eZ0FoRzyijILuG012LE7p0H8Sf28"
)

COMMON_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json",
    "Origin": "http://localhost:8090",
    "Referer": "http://localhost:8090/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _format_time(time_desc: str) -> Tuple[str, str]:
    """
    智能时间解析
    """
    log_info(f"开始解析时间描述: '{time_desc}'")
    now = datetime.now()
    log_debug(f"当前系统时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    if not time_desc or time_desc.strip() == "":
        log_info("时间描述为空，使用默认规则: 最近24小时")
        start = now - timedelta(hours=24)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"默认时间范围: {result[0]} ~ {result[1]}")
        return result

    time_desc = time_desc.strip()
    log_debug(f"处理后的时间描述: '{time_desc}'")

    if time_desc in ["今天", "today"]:
        log_info("匹配到'今天'，生成当天时间范围")
        start = now.replace(hour=0, minute=0, second=0)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"今天时间范围: {result[0]} ~ {result[1]}")
        return result

    if time_desc in ["昨天", "yesterday"]:
        log_info("匹配到'昨天'，生成昨天时间范围")
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0)
        end = yesterday.replace(hour=23, minute=59, second=59)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"昨天时间范围: {result[0]} ~ {result[1]}")
        return result

    if any(x in time_desc for x in ["最近7天", "近7天", "最近一周", "本周"]):
        log_info("匹配到'最近7天/本周'，生成7天时间范围")
        start = now - timedelta(days=7)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"最近7天时间范围: {result[0]} ~ {result[1]}")
        return result

    if any(x in time_desc for x in ["最近30天", "近30天", "最近一个月", "本月"]):
        log_info("匹配到'最近30天/本月'，生成30天时间范围")
        start = now - timedelta(days=30)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"最近30天时间范围: {result[0]} ~ {result[1]}")
        return result

    # 尝试解析具体日期 "2025-09-23"
    try:
        dt = datetime.strptime(time_desc, "%Y-%m-%d")
        log_info(f"成功解析日期格式: {time_desc}")
        start = dt.replace(hour=0, minute=0, second=0)
        end = dt.replace(hour=23, minute=59, second=59)
        result = (
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"指定日期时间范围: {result[0]} ~ {result[1]}")
        return result
    except ValueError:
        log_debug(f"无法按 '%Y-%m-%d' 解析: '{time_desc}'")

    # 尝试解析完整时间 "2025-09-23 14:00:00"
    try:
        dt = datetime.strptime(time_desc, "%Y-%m-%d %H:%M:%S")
        log_info(f"成功解析完整时间格式: {time_desc}")
        result = (
            time_desc,
            now.strftime("%Y-%m-%d %H:%M:%S")
        )
        log_info(f"指定时间范围: {result[0]} ~ {result[1]}")
        return result
    except ValueError:
        log_debug(f"无法按 '%Y-%m-%d %H:%M:%S' 解析: '{time_desc}'")

    # 默认返回最近24小时
    log_warn(f"无法识别时间描述 '{time_desc}'，回退到默认: 最近24小时")
    start = now - timedelta(hours=24)
    result = (
        start.strftime("%Y-%m-%d %H:%M:%S"),
        now.strftime("%Y-%m-%d %H:%M:%S")
    )
    log_info(f"默认时间范围: {result[0]} ~ {result[1]}")
    return result


def _build_payload(start_date: str, end_date: str) -> Dict[str, Any]:
    """构建统一的请求体（馈线和配变共用）"""
    return {
        "startDate": start_date,
        "endDate": end_date,
        "dataType": "",
        "start": "",
        "limit": "",
        "typeFlag": 1
    }


def _do_post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """通用 POST 请求发送"""
    log_info(f"准备调用接口: {url}")
    log_debug(f"请求参数: {json.dumps(payload, ensure_ascii=False)}")

    try:
        log_info("开始发送 HTTP POST 请求...")
        resp = requests.post(url, json=payload, headers=COMMON_HEADERS, timeout=30)
        log_info(f"收到响应, HTTP状态码: {resp.status_code}")
        log_debug(f"响应内容(前500字): {resp.text[:500]}")

        resp.raise_for_status()

        try:
            data = resp.json()
            log_info(f"响应JSON解析成功, success={data.get('success')}, code={data.get('code')}, message={data.get('message')}")
            total = data.get('data', {}).get('totalSize', 'N/A')
            log_info(f"数据条数: {total}")
            return data
        except json.JSONDecodeError as e:
            log_error(f"响应JSON解析失败: {e}")
            log_error(f"原始响应内容: {resp.text}")
            return {
                "success": False,
                "code": 500,
                "message": f"响应JSON解析失败: {e}, 原始内容: {resp.text[:200]}",
                "data": None
            }

    except requests.exceptions.Timeout as e:
        log_error(f"请求超时: {e}")
        return {
            "success": False,
            "code": 500,
            "message": f"请求超时(30s): {str(e)}",
            "data": None
        }
    except requests.exceptions.ConnectionError as e:
        log_error(f"连接错误: {e}")
        return {
            "success": False,
            "code": 500,
            "message": f"连接失败，请检查网络是否可达 {BASE_URL}: {str(e)}",
            "data": None
        }
    except requests.exceptions.HTTPError as e:
        log_error(f"HTTP错误: {e}")
        return {
            "success": False,
            "code": resp.status_code,
            "message": f"HTTP错误 {resp.status_code}: {str(e)}",
            "data": None
        }
    except requests.exceptions.RequestException as e:
        log_error(f"请求异常: {type(e).__name__}: {e}")
        return {
            "success": False,
            "code": 500,
            "message": f"请求异常 {type(e).__name__}: {str(e)}",
            "data": None
        }


def _get_fd_overload(start_date: str, end_date: str) -> Dict[str, Any]:
    """获取馈线重过载数据"""
    url = f"{BASE_URL}/getFdOverloadData"
    log_info(f"准备调用馈线重过载接口: {url}")
    payload = _build_payload(start_date, end_date)
    return _do_post(url, payload)


def _get_pb_overload(start_date: str, end_date: str) -> Dict[str, Any]:
    """获取配变重过载数据"""
    url = f"{BASE_URL}/getPbOverloadData"
    log_info(f"准备调用配变重过载接口: {url}")
    payload = _build_payload(start_date, end_date)
    return _do_post(url, payload)


def _format_result(raw_data: Dict[str, Any], query_type: str, start_date: str, end_date: str) -> Dict[str, Any]:
    """格式化返回结果为标准结构"""
    log_info(f"开始格式化结果, query_type={query_type}")

    if not raw_data.get("success"):
        log_warn(f"接口返回 success=false, message={raw_data.get('message')}")
        return {
            "status": "error",
            "message": raw_data.get("message", "未知错误"),
            "query_type": query_type,
            "time_range": {"start": start_date, "end": end_date},
            "columns": [],
            "data": [],
            "row_count": 0
        }

    result_data = raw_data.get("data", {})
    total = result_data.get("totalSize", 0)
    items = result_data.get("data", [])
    log_info(f"接口返回数据条数: totalSize={total}, data数组长度={len(items)}")

    if total == 0 or not items:
        log_info("数据为空，返回空结果")
        return {
            "status": "success",
            "message": "该时间段内未检测到重过载数据",
            "query_type": query_type,
            "time_range": {"start": start_date, "end": end_date},
            "columns": [],
            "data": [],
            "row_count": 0
        }

    # 统一字段映射
    if query_type == "feeder":
        log_info("格式化馈线数据...")
        columns = ["序号", "馈线名称", "所属变电站", "所属区县", "供电所", "负载率(%)", "电流(A)", "限流(A)", "发生时间", "设备编号"]
        formatted_data = []
        for i, item in enumerate(items, 1):
            try:
                rate = float(item.get("LOAD_RATE", 0))
            except (ValueError, TypeError) as e:
                log_warn(f"第{i}条记录 LOAD_RATE 解析失败: {item.get('LOAD_RATE')}, 错误: {e}")
                rate = 0.0

            formatted_data.append({
                "序号": i,
                "馈线名称": item.get("FD_DESC", "-"),
                "所属变电站": item.get("SS_DESC", "-"),
                "所属区县": item.get("AREA_DESC", "-"),
                "供电所": item.get("ZONE_DESC", "-"),
                "负载率(%)": rate,
                "电流(A)": item.get("ELET_VALUE", "-"),
                "限流(A)": item.get("LIMIT_VALUE", "-"),
                "发生时间": item.get("OCCUR_DATE", "-"),
                "设备编号": item.get("DEV_NO", "-"),
                "_risk_level": "high" if rate >= 120 else "overload" if rate >= 100 else "heavy" if rate >= 80 else "normal"
            })
    else:
        log_info("格式化配变数据...")
        columns = ["序号", "配变名称", "类型", "所属馈线", "所属变电站", "所属区县", "供电所", "负载率(%)", "额定容量(kVA)", "有功功率(kW)", "发生时间", "设备编号"]
        formatted_data = []
        for i, item in enumerate(items, 1):
            try:
                rate = float(item.get("LOAD_RATE", 0))
            except (ValueError, TypeError) as e:
                log_warn(f"第{i}条记录 LOAD_RATE 解析失败: {item.get('LOAD_RATE')}, 错误: {e}")
                rate = 0.0

            formatted_data.append({
                "序号": i,
                "配变名称": item.get("PB_DESC", "-"),
                "类型": item.get("PB_TYPE", "-"),
                "所属馈线": item.get("FD_DESC", "-"),
                "所属变电站": item.get("SS_DESC", "-"),
                "所属区县": item.get("AR_DESC", "-"),
                "供电所": item.get("ZN_DESC", "-"),
                "负载率(%)": rate,
                "额定容量(kVA)": item.get("CAP_VALUE", "-"),
                "有功功率(kW)": item.get("YG_VALUE", "-"),
                "发生时间": item.get("OCCUR_DATE", "-"),
                "设备编号": item.get("DEV_NO", "-"),
                "_risk_level": "high" if rate >= 120 else "overload" if rate >= 100 else "heavy" if rate >= 80 else "normal"
            })

    risk_summary = {
        "high": len([x for x in formatted_data if x["_risk_level"] == "high"]),
        "overload": len([x for x in formatted_data if x["_risk_level"] == "overload"]),
        "heavy": len([x for x in formatted_data if x["_risk_level"] == "heavy"]),
        "normal": len([x for x in formatted_data if x["_risk_level"] == "normal"])
    }
    log_info(f"风险统计: 严重过载={risk_summary['high']}, 过载={risk_summary['overload']}, 重载={risk_summary['heavy']}, 正常={risk_summary['normal']}")

    return {
        "status": "success",
        "message": "查询成功",
        "query_type": query_type,
        "time_range": {"start": start_date, "end": end_date},
        "columns": columns,
        "data": formatted_data,
        "row_count": total,
        "risk_summary": risk_summary
    }


def execute(
    query_type: str = "",
    time_desc: str = "",
    start_date: str = "",
    end_date: str = ""
) -> Dict[str, Any]:
    """
    执行重过载数据查询
    """
    log_info("=" * 60)
    log_info("技能执行开始")
    log_info("=" * 60)
    log_info(f"输入参数: query_type={query_type}, time_desc={time_desc}, start_date={start_date}, end_date={end_date}")

    # 参数校验
    if not query_type:
        log_error("参数校验失败: query_type 为空")
        return {
            "status": "error",
            "message": "请指定查询类型: 'feeder'(馈线) 或 'transformer'(配变)",
            "data": []
        }

    if query_type not in ["feeder", "transformer"]:
        log_error(f"参数校验失败: query_type='{query_type}' 不在允许值 [feeder, transformer] 中")
        return {
            "status": "error",
            "message": f"查询类型 '{query_type}' 不合法，请使用 'feeder'(馈线) 或 'transformer'(配变)",
            "data": []
        }

    # 确定时间范围
    if start_date and end_date:
        log_info("用户直接提供了时间范围，跳过智能推断")
    else:
        log_info("开始智能推断时间范围...")
        start_date, end_date = _format_time(time_desc)

    log_info(f"最终时间范围: {start_date} ~ {end_date}")

    # 调用对应接口
    start_perf = time.perf_counter()

    if query_type == "feeder":
        log_info("选择调用: 馈线重过载接口")
        raw_data = _get_fd_overload(start_date, end_date)
    else:
        log_info("选择调用: 配变重过载接口")
        raw_data = _get_pb_overload(start_date, end_date)

    # 格式化结果
    result = _format_result(raw_data, query_type, start_date, end_date)
    elapsed_ms = round((time.perf_counter() - start_perf) * 1000, 3)
    result["elapsed_ms"] = elapsed_ms

    log_info(f"技能执行完成，耗时: {elapsed_ms}ms")
    log_info("=" * 60)

    return result


if __name__ == "__main__":
    log_info("脚本启动，解析命令行参数...")

    parser = argparse.ArgumentParser(description="重过载数据查询")
    parser.add_argument("--query-type", default="", help="查询类型: feeder/transformer")
    parser.add_argument("--time-desc", default="", help="时间描述")
    parser.add_argument("--start-date", default="", help="开始时间")
    parser.add_argument("--end-date", default="", help="结束时间")
    args = parser.parse_args()

    log_info(f"命令行参数: query_type={args.query_type}, time_desc={args.time_desc}, start_date={args.start_date}, end_date={args.end_date}")

    result = execute(
        query_type=args.query_type,
        time_desc=args.time_desc,
        start_date=args.start_date,
        end_date=args.end_date
    )

    log_info("输出最终结果(JSON)...")
    print(json.dumps(result, ensure_ascii=False, default=str))
    log_info("脚本结束")
