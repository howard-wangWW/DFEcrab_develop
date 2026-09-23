"""
Weather Forecast - 天气预报
查询指定城市的天气预报信息
"""

import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional


def get_weather_forecast(latitude: float, longitude: float, hourly_params: str = "temperature_2m") -> Dict[str, Any]:
    """
    从Open-Meteo API获取天气预报

    Args:
        latitude: 纬度 (-90 到 90)
        longitude: 经度 (-180 到 180)
        hourly_params: 小时参数，逗号分隔 (默认: temperature_2m)

    Returns:
        包含天气数据的字典
    """
    # 验证坐标
    if not (-90 <= latitude <= 90):
        raise ValueError(f"无效的纬度: {latitude}。必须在 -90 到 90 之间")
    if not (-180 <= longitude <= 180):
        raise ValueError(f"无效的经度: {longitude}。必须在 -180 到 180 之间")

    # 构建API URL
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "hourly": hourly_params
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    # 发送API请求
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.getcode() != 200:
                raise urllib.error.HTTPError(
                    url, response.getcode(), f"HTTP {response.getcode()}", response.headers, None
                )
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        raise Exception(f"网络请求失败: {e}")


def get_city_coordinates(city_name: str) -> tuple:
    """
    获取城市坐标（简化版本，使用常见城市坐标）
    
    Args:
        city_name: 城市名称
        
    Returns:
        (纬度, 经度) 元组
    """
    # 常见城市坐标映射
    city_coords = {
        "北京": (39.9042, 116.4074),
        "上海": (31.2304, 121.4737),
        "广州": (23.1291, 113.2644),
        "深圳": (22.5431, 114.0579),
        "杭州": (30.2741, 120.1551),
        "南京": (32.0603, 118.7969),
        "成都": (30.5728, 104.0668),
        "重庆": (29.5630, 106.5516),
        "武汉": (30.5928, 114.3055),
        "西安": (34.3416, 108.9398),
        "大理": (25.6065, 100.2676),
        "昆明": (25.0389, 102.7183),
        "丽江": (26.8721, 100.2306),
        "三亚": (18.2528, 109.5120),
        "厦门": (24.4798, 118.0894),
        "青岛": (36.0671, 120.3826),
        "大连": (38.9140, 121.6147),
        "天津": (39.1252, 117.1904),
        "苏州": (31.2989, 120.5853),
        "无锡": (31.4912, 120.3119),
    }
    
    # 尝试匹配城市名称
    for name, coords in city_coords.items():
        if name in city_name or city_name in name:
            return coords
    
    # 如果找不到，返回大理的坐标作为默认值
    return (25.6065, 100.2676)


def execute(city: str = "大理", days: int = 1) -> str:
    """
    查询指定城市的天气预报

    Args:
        city: 城市名称（支持中文城市名）
        days: 预报天数（1-7天）

    Returns:
        天气预报信息
    """
    try:
        # 获取城市坐标
        lat, lon = get_city_coordinates(city)
        
        # 获取天气预报
        weather_data = get_weather_forecast(lat, lon, "temperature_2m,weathercode")
        
        # 解析天气数据
        hourly = weather_data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weathercode", [])
        
        if not times or not temps:
            return f"无法获取 {city} 的天气预报数据"
        
        # 构建输出
        output = [f"🌤️ {city} 天气预报", "=" * 40]
        
        # 获取未来24小时的数据（每3小时显示一次）
        for i in range(0, min(24, len(times)), 3):
            time_str = times[i].split("T")[1][:5] if "T" in times[i] else times[i]
            temp = temps[i]
            code = codes[i] if i < len(codes) else 0
            
            # 天气代码转描述
            weather_desc = get_weather_description(code)
            output.append(f"{time_str}: {temp}°C {weather_desc}")
        
        return "\n".join(output)
        
    except Exception as e:
        return f"获取 {city} 天气预报时出错: {str(e)}"


def get_weather_description(code: int) -> str:
    """
    将天气代码转换为中文描述

    Args:
        code: WMO天气代码

    Returns:
        天气描述
    """
    weather_codes = {
        0: "☀️ 晴朗",
        1: "🌤️ 多云",
        2: "⛅ 多云",
        3: "☁️ 阴天",
        45: "🌫️ 雾",
        48: "🌫️ 雾凇",
        51: "🌧️ 毛毛雨",
        53: "🌧️ 小雨",
        55: "🌧️ 中雨",
        61: "🌧️ 小雨",
        63: "🌧️ 中雨",
        65: "🌧️ 大雨",
        71: "🌨️ 小雪",
        73: "🌨️ 中雪",
        75: "🌨️ 大雪",
        95: "⛈️ 雷雨",
        96: "⛈️ 雷雨伴冰雹",
        99: "⛈️ 强雷雨伴冰雹",
    }
    return weather_codes.get(code, "🌡️ 未知天气")
