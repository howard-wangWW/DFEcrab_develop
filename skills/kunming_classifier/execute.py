"""
昆明配网查询分类技能 (kunming_classifier)
对用户查询进行分类，确定应调用的 API 接口，并提取结构化参数

分类规则（由 LLM 在 SKILL.md 中定义）：
  类别5  - 其他对话（直接回复，不调 API；理论/知识类问答请路由到 knowledge_agent）
  类别6  - 跳闸统计（调 /tiaozha）
  类别7  - 早会材料（调 /zaohui）
  类别8  - 受令资格（调 /check_qualification）
  类别9  - 异常信号统计（调 /get_abnormal_signals）
  类别10 - 城区一小时跳闸（调 /today-chengqu-1h-trip）
  类别11 - 保供电跳闸（调 /today-baogongdian-trip）
  类别12 - 某局跳闸（调 /today-bureau-trip）
  类别13 - 重过载（调 /overload）

注意：类别1-4 暂放，后续实现；类别14（理论题）已随 kunming_theory_qa 下线移除。
"""
import argparse
import json

SKILL_METADATA = {
    "name": "kunming_classifier",
    "description": "对用户查询进行分类，确定应调用的API接口并提取参数。类别: 5-其他对话(不调API), 6-跳闸统计, 7-早会材料, 8-受令资格, 9-异常信号统计, 10-城区一小时跳闸, 11-保供电跳闸, 12-某局跳闸, 13-重过载",
    "parameters": {
        "query": {
            "type": "string",
            "description": "用户原始查询文本（时间已被解析为具体日期）"
        },
        "category": {
            "type": "integer",
            "description": "分类编号: 5=其他对话(直接回复), 6=跳闸统计(/tiaozha), 7=早会材料(/zaohui), 8=受令资格(/check_qualification), 9=异常信号统计(/get_abnormal_signals), 10=城区一小时跳闸(/today-chengqu-1h-trip), 11=保供电跳闸(/today-baogongdian-trip), 12=某局跳闸(/today-bureau-trip), 13=重过载(/overload)",
            "default": 5
        },
        "startTime": {
            "type": "string",
            "description": "查询起始时间，格式 YYYY-MM-DD HH:MM:SS（类别6/7/10/11需要）",
            "default": ""
        },
        "endTime": {
            "type": "string",
            "description": "查询结束时间，格式 YYYY-MM-DD HH:MM:SS（类别6/7/10/11需要）",
            "default": ""
        },
        "personName": {
            "type": "string",
            "description": "受令资格查询的人员姓名（类别8需要）",
            "default": ""
        },
        "date": {
            "type": "string",
            "description": "查询日期，格式 YYYY-MM-DD（类别9需要）",
            "default": ""
        },
        "bureau": {
            "type": "string",
            'description': '供电局名称（类别12需要，如"西山局"、"官渡局"等）',
            "default": ""
        },
        "mode": {
            "type": "string",
            "description": "重过载查询模式（类别13需要）：area_count/total_count/trend/detail/top_feeders",
            "default": ""
        },
        "area": {
            "type": "string",
            "description": "区局名称（类别13需要，如\"官渡供电局\"、\"西山局\"）",
            "default": ""
        },
        "days": {
            "type": "integer",
            "description": "查询天数（类别13的trend模式需要，默认3天）",
            "default": 3
        },
        "load_threshold": {
            "type": "integer",
            "description": "负载率阈值（类别13需要，默认80）",
            "default": 80
        }
    }
}

def execute(query="", category=5, startTime="", endTime="", personName="", date="", bureau="", mode="", area="", days=3, load_threshold=80, **kwargs):
    """
    分类器执行函数。
    LLM 通过 function calling 确定分类和参数后，这里做校验和返回。
    """
    # 校验参数
    if category in (6, 7, 10, 11):
        if not startTime or not endTime:
            return {"status": "error", "message": f"类别{category}需要提供 startTime 和 endTime"}
    elif category == 8:
        if not personName:
            return {"status": "error", "message": "类别8（受令资格）需要提供 personName"}
    elif category == 9:
        if not date:
            return {"status": "error", "message": "类别9（异常信号统计）需要提供 date"}
    elif category == 12:
        if not bureau:
            return {"status": "error", "message": "类别12（某局跳闸）需要提供 bureau（供电局名称）"}
    elif category == 13:
        if not mode:
            return {"status": "error", "message": "类别13（重过载）需要提供 mode（查询模式）"}
        if mode == "area_count" and not area:
            return {"status": "error", "message": "类别13（重过载）area_count模式需要提供 area（区局名称）"}
    elif category not in (5, 6, 7, 8, 9, 10, 11, 12, 13):
        return {"status": "error", "message": f"不支持的类别: {category}，当前仅支持5/6/7/8/9/10/11/12/13"}

    result = {
        "status": "success",
        "category": category,
        "startTime": startTime,
        "endTime": endTime,
        "personName": personName,
        "date": date,
        "bureau": bureau
    }

    if category == 13:
        result.update({
            "mode": mode,
            "area": area,
            "days": days,
            "load_threshold": load_threshold
        })

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--category", type=int, default=5)
    parser.add_argument("--start-time", default="")
    parser.add_argument("--end-time", default="")
    parser.add_argument("--person-name", default="")
    parser.add_argument("--date", default="")
    parser.add_argument("--bureau", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--area", default="")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--load-threshold", type=int, default=80)
    args = parser.parse_args()
    result = execute(
        query=args.query,
        category=args.category,
        startTime=args.start_time,
        endTime=args.end_time,
        personName=args.person_name,
        date=args.date,
        bureau=args.bureau,
        mode=args.mode,
        area=args.area,
        days=args.days,
        load_threshold=args.load_threshold
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
