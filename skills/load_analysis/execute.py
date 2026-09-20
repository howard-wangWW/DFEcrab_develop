"""
电网负载率分析技能

功能：
1. 获取量测数据（模拟接口）
2. 计算负载率 = 有功 / 容量 * 100%
3. 分类：过载 (>100%) 和 高负载 (80%-100%)
4. 排序：按负载率降序
5. 输出格式化结果
"""

import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径，以便导入（如果需要）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

SKILL_METADATA = {
    "name": "load_analysis",
    "version": "1.0.0",
    "description": "分析电网负载率，分类并排序",
    "parameters": {
        "type": "object",
        "properties": {
            "api_url": {"type": "string", "description": "量测数据接口地址（可选，默认使用 Mock 数据）"}
        }
    }
}


def fetch_measurement_data(api_url=None):
    """
    获取量测数据
    TODO: 替换为真实的 API 调用
    """
    # Mock 数据
    print(f"[DEBUG] 正在获取量测数据... (API: {api_url or 'Mock'})")
    return [
        {"device": "变压器 A", "active_power": 120, "capacity": 100},
        {"device": "变压器 B", "active_power": 85, "capacity": 100},
        {"device": "变压器 C", "active_power": 50, "capacity": 100},
        {"device": "变压器 D", "active_power": 105, "capacity": 100},
        {"device": "变压器 E", "active_power": 90, "capacity": 100},
        {"device": "变压器 F", "active_power": 110, "capacity": 100},
        {"device": "变压器 G", "active_power": 82, "capacity": 100},
    ]


def execute(api_url=None, **kwargs):
    """
    执行负载率分析

    Args:
        api_url: 数据接口地址
        **kwargs: 其他参数

    Returns:
        str: 分析结果报告
    """
    # 1. 获取数据
    data = fetch_measurement_data(api_url)

    # 2. 计算负载率
    for item in data:
        capacity = item.get('capacity', 0)
        active_power = item.get('active_power', 0)
        if capacity > 0:
            item['load_rate'] = (active_power / capacity) * 100
        else:
            item['load_rate'] = 0.0

    # 3. 分类
    overload = [x for x in data if x['load_rate'] > 100]
    high_load = [x for x in data if 80 < x['load_rate'] <= 100]

    # 4. 排序（按负载率降序）
    overload.sort(key=lambda x: x['load_rate'], reverse=True)
    high_load.sort(key=lambda x: x['load_rate'], reverse=True)

    # 5. 格式化输出
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result = f"=== 负载率分析结果 ({timestamp}) ===\n\n"

    result += f"📊 总设备数：{len(data)}\n"
    result += f"🔴 过载设备数：{len(overload)}\n"
    result += f"🟡 高负载设备数：{len(high_load)}\n\n"

    result += "🔴 过载设备 (>100%):\n"
    if overload:
        for i, item in enumerate(overload, 1):
            result += f"  {i}. {item['device']}: {item['load_rate']:.1f}% (有功: {item['active_power']}, 容量: {item['capacity']})\n"
    else:
        result += "  无\n"

    result += "\n🟡 高负载设备 (80%-100%):\n"
    if high_load:
        for i, item in enumerate(high_load, 1):
            result += f"  {i}. {item['device']}: {item['load_rate']:.1f}% (有功: {item['active_power']}, 容量: {item['capacity']})\n"
    else:
        result += "  无\n"

    return result


if __name__ == "__main__":
    # 本地测试
    print(execute())
