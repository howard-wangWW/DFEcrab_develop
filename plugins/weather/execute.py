"""
Weather - 天气查询
使用wttr.in服务查询当前天气（无需API密钥）
"""

import subprocess
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any

SKILL_METADATA = {
    "name": "weather",
    "description": "查询指定城市的当前天气和预报，使用 wttr.in 服务",
    "parameters": {
        "city": {
            "type": "string",
            "description": "城市名称（支持中文，如'北京'）",
            "default": "北京"
        },
        "format_type": {
            "type": "string",
            "description": "输出格式：compact(简洁) 或 full(详细)",
            "default": "compact"
        }
    }
}


def get_weather(city: str = "Beijing", format_type: str = "compact") -> str:
    """
    使用wttr.in查询天气

    Args:
        city: 城市名称（支持中文城市名）
        format_type: 输出格式 (compact/full/png)

    Returns:
        天气信息
    """
    # 城市名称映射（中文到英文）
    city_mapping = {
        "北京": "Beijing",
        "上海": "Shanghai",
        "广州": "Guangzhou",
        "深圳": "Shenzhen",
        "杭州": "Hangzhou",
        "南京": "Nanjing",
        "成都": "Chengdu",
        "重庆": "Chongqing",
        "武汉": "Wuhan",
        "西安": "Xian",
        "大理": "Dali",
        "昆明": "Kunming",
        "丽江": "Lijiang",
        "三亚": "Sanya",
        "厦门": "Xiamen",
        "青岛": "Qingdao",
        "大连": "Dalian",
        "天津": "Tianjin",
        "苏州": "Suzhou",
        "无锡": "Wuxi",
        "香港": "Hong Kong",
        "台北": "Taipei",
    }
    
    # 转换城市名称
    city_en = city_mapping.get(city, city)
    
    # URL编码城市名称
    city_encoded = urllib.parse.quote(city_en)
    
    try:
        if format_type == "compact":
            # 紧凑格式：城市: 天气图标 + 温度
            url = f"https://wttr.in/{city_encoded}?format=3"
        elif format_type == "full":
            # 完整格式
            url = f"https://wttr.in/{city_encoded}?T"
        else:
            url = f"https://wttr.in/{city_encoded}?format=3"
        
        # 发送请求
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'curl/7.68.0'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = response.read().decode('utf-8').strip()
            
            if format_type == "compact":
                # 格式化紧凑输出
                if ":" in result:
                    location, weather = result.split(":", 1)
                    return f"🌤️ {location.strip()} 当前天气: {weather.strip()}"
                return f"🌤️ {result}"
            else:
                return result
                
    except urllib.error.URLError as e:
        return f"❌ 获取天气信息失败: {e}"
    except Exception as e:
        return f"❌ 查询天气时出错: {e}"


def execute(city: str = "北京", format_type: str = "compact") -> str:
    """
    查询指定城市的天气

    Args:
        city: 城市名称（支持中文）
        format_type: 输出格式 (compact/full)

    Returns:
        ServiceResponse 对象
    """
    from agentscope.service import ServiceResponse, ServiceExecStatus

    try:
        result = get_weather(city, format_type)
        return ServiceResponse(status=ServiceExecStatus.SUCCESS, content=result)
    except Exception as e:
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"查询天气失败: {str(e)}")
