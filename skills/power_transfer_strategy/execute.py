"""
电网转电策略生成技能

功能：
1. 接收过载设备列表
2. 模拟计算最优转电路径（基于拓扑和备用容量）
3. 生成包含操作步骤、预期效果的结构化 JSON 方案
"""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

SKILL_METADATA = {
    "name": "power_transfer_strategy",
    "version": "1.0.0",
    "description": "根据过载情况生成转电策略方案",
    "parameters": {
        "type": "object",
        "properties": {
            "analysis_result": {
                "type": "string", 
                "description": "负载分析技能输出的 JSON 字符串"
            }
        },
        "required": ["analysis_result"]
    }
}

def execute(analysis_result: str, **kwargs):
    """
    执行转电策略生成

    Args:
        analysis_result: 上游负载分析技能输出的 JSON 字符串
        **kwargs: 其他参数

    Returns:
        str: 转电策略方案 (JSON 字符串)
    """
    try:
        # 1. 解析上游输入
        data = json.loads(analysis_result)
        overload_devices = data.get("overload_devices", [])
        
        if not overload_devices:
            return json.dumps({"status": "skipped", "reason": "无过载设备，无需转电"}, ensure_ascii=False)

        print(f"[DEBUG] 正在为 {len(overload_devices)} 台过载设备生成转电策略...")

        # 2. 模拟策略计算 (Mock 逻辑)
        strategy_actions = []
        expected_loads = {}
        
        for device in overload_devices:
            dev_name = device['name']
            current_load = device['value']
            
            target_line = f"备用线路 {dev_name}-B"
            
            strategy_actions.append({
                "step": len(strategy_actions) + 1,
                "device": f"{dev_name} 进线开关",
                "action": "分闸",
                "reason": f"降低 {dev_name} 负载"
            })
            strategy_actions.append({
                "step": len(strategy_actions) + 1,
                "device": f"{target_line} 联络开关",
                "action": "合闸",
                "reason": f"由 {target_line} 承担部分负荷"
            })
            
            expected_loads[dev_name] = 80.0

        # 3. 构建输出 JSON
        result = {
            "strategy_id": f"STRAT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "risk_level": "high" if len(overload_devices) > 2 else "medium",
            "actions": strategy_actions,
            "expected_load_after": expected_loads,
            "note": "请人工核对开关状态后执行"
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

if __name__ == "__main__":
    mock_input = json.dumps({
        "overload_devices": [
            {"name": "1#主变", "value": 118.5, "active": 118.5}
        ]
    })
    print(execute(analysis_result=mock_input))
