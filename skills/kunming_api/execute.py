"""
昆明配网数据 API 调用技能 (kunming_api)
通过 HTTP 调用 DM-kunming.py 的所有接口，获取配网数据

支持的接口：
  POST: /tiaozha, /zaohui, /check_qualification, /meta, /query, /svg_groups, /generate-excel,
        /get_abnormal_signals, /today-chengqu-1h-trip, /today-baogongdian-trip, /overload
  GET:  /meta, /svg_groups, /today-bureau-trip
"""
import argparse
import json
import requests

API_BASE = "http://192.168.113.15:8088"

SKILL_METADATA = {
    "name": "kunming_api",
    "description": "调用昆明配网数据API（DM-kunming.py 192.168.113.15:8088），支持所有接口",
    "parameters": {
        "endpoint": {
            "type": "string",
            "description": "API接口名：tiaozha(跳闸统计), zaohui(早会材料), check_qualification(受令资格), get_abnormal_signals(异常信号统计), today-chengqu-1h-trip(城区一小时跳闸), today-baogongdian-trip(保供电跳闸), today-bureau-trip(某局跳闸), svg_groups(SVG查询), meta(表结构), query(执行SQL), generate-excel(生成Excel)"
        },
        "params": {
            "type": "object",
            "description": "接口参数，根据endpoint不同传入不同参数。如tiaozha/zaohui/today-chengqu-1h-trip/today-baogongdian-trip需要{startTime, endTime}，check_qualification需要{personName}，get_abnormal_signals需要{date}，today-bureau-trip需要{bureau}，query需要{sql}"
        }
    }
}

# ==================== POST 接口列表 ====================
POST_ENDPOINTS = {"tiaozha", "zaohui", "check_qualification", "query", "generate-excel", "get_abnormal_signals", "today-chengqu-1h-trip", "today-baogongdian-trip", "overload"}

# ==================== GET 接口列表 ====================
GET_ENDPOINTS = {"meta", "svg_groups", "today-bureau-trip"}


def _request_without_env_proxy(method: str, url: str, **kwargs):
    """内网接口请求默认禁用环境代理，避免被服务器代理配置误拦截。"""
    with requests.Session() as session:
        session.trust_env = False
        if method == "post":
            return session.post(url, **kwargs)
        return session.get(url, **kwargs)


def execute(endpoint="", params=None, **kwargs):
    """调用昆明配网数据 API"""
    if not endpoint:
        return {"status": "error", "message": "endpoint 不能为空"}

    endpoint = endpoint.strip().lower()
    params = params or {}

    if endpoint not in POST_ENDPOINTS and endpoint not in GET_ENDPOINTS:
        return {"status": "error", "message": f"未知 endpoint: {endpoint}，支持的接口: {', '.join(sorted(POST_ENDPOINTS | GET_ENDPOINTS))}"}

    try:
        url = f"{API_BASE}/{endpoint}"

        if endpoint in POST_ENDPOINTS:
            resp = _request_without_env_proxy("post", url, json=params, timeout=30)
        else:
            resp = _request_without_env_proxy("get", url, params=params, timeout=30)

        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        return {
            "status": "success",
            "endpoint": endpoint,
            "data": data
        }

    except requests.exceptions.Timeout:
        return {"status": "error", "message": f"API 请求超时: {endpoint}"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": f"API 连接失败: {API_BASE}/{endpoint}，请检查服务是否运行"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"API 请求失败: {endpoint}, {str(e)}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--params", default="{}")
    args = parser.parse_args()
    try:
        p = json.loads(args.params)
    except json.JSONDecodeError:
        p = {}
    result = execute(endpoint=args.endpoint, params=p)
    print(json.dumps(result, ensure_ascii=False, default=str))
