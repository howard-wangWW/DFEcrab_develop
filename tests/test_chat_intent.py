"""对话意图/信号解析工具单测（拆分 parity 验证）

`src/gateway/chat/intent.py` 里的函数是从 `grpc_server.GatewayV2GRPC` 抽出的，
本测试锁定其行为，防止拆分过程中语义漂移（尤其"快检"与"严格判定"两种告警识别）。

运行：
    python tests/test_chat_intent.py      # 期望 exit 0
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gateway.chat.intent import (  # noqa: E402
    extract_json_fragment,
    extract_json_object,
    is_alert_signal_json,
    looks_like_alert_json,
    normalize_target_agent,
    truncate_system_prompt,
)

_PASSED = []


def ok(name):
    _PASSED.append(name)
    print(f"  ✅ {name}")


# ──────────────────────────────────────────────────────────────

def test_looks_like_alert_json():
    """快检：不解析 JSON，只看首字符 + 特征字段子串"""
    assert looks_like_alert_json('{"station_inside_outer":"A","throbNum":1}') is True
    assert looks_like_alert_json('  {"alert_content":"x"}') is True
    assert looks_like_alert_json('{"foo":1}') is False          # 无特征字段
    assert looks_like_alert_json('station_inside_outer') is False  # 非 JSON 对象
    assert looks_like_alert_json("") is False
    assert looks_like_alert_json(None) is False
    assert looks_like_alert_json({"station_inside_outer": 1}) is False  # 仅接受字符串
    ok("looks_like_alert_json（快检）")


def test_is_alert_signal_json():
    """严格判定：必须可解析 + 命中 ≥2 个特征字段"""
    good = json.dumps({"station_inside_outer": "A", "throbNum": 3, "alert_content": "过载"})
    assert is_alert_signal_json(good) is True

    # 只命中 1 个 → False（这是与"快检"的关键差异）
    one = json.dumps({"station_inside_outer": "A"})
    assert is_alert_signal_json(one) is False
    assert looks_like_alert_json(one) is True  # 快检会放过，用于路由预检

    # 数组形式的多条告警
    nested = json.dumps({"alerts": [{"station_inside_outer": "A", "throbNum": 1}]})
    assert is_alert_signal_json(nested) is True

    # 非法 JSON / 非对象
    assert is_alert_signal_json("{station_inside_outer") is False
    assert is_alert_signal_json('["a","b"]') is False
    assert is_alert_signal_json("") is False
    assert is_alert_signal_json(None) is False
    ok("is_alert_signal_json（严格判定 + 数组兼容）")


def test_normalize_target_agent():
    for alias in ("target", "agent", "agent_id"):
        out = normalize_target_agent({alias: "dfecrab"})
        assert out["target_agent"] == "dfecrab", alias
    # 已有 target_agent 不被覆盖
    out = normalize_target_agent({"target_agent": "a", "agent": "b"})
    assert out["target_agent"] == "a"
    ok("normalize_target_agent（别名归一）")


def test_extract_json_object():
    text = '思考中...\n{"type":"simple","target_agent":"dfecrab"}\n以上'
    parsed = extract_json_object(text)
    assert parsed["type"] == "simple" and parsed["target_agent"] == "dfecrab"

    # 别名补写
    assert extract_json_object('{"target":"x"}')["target_agent"] == "x"
    # 单引号 / 中文标点 容错
    assert extract_json_object("{'type': 'simple'}")["type"] == "simple"
    assert extract_json_object('{"type"："simple"}')["type"] == "simple"
    # 取最后一段 {...}
    assert extract_json_object('{"a":1} 噪声 {"b":2}')["b"] == 2
    # 无 JSON
    assert extract_json_object("没有 JSON") is None
    assert extract_json_object("") is None
    # 修复后：末尾为嵌套对象可正确解析（旧实现只取最后一个 { → 返回 None，会丢弃该次决策）
    nested = extract_json_object('{"a":{"b":1}}')
    assert nested == {"a": {"b": 1}}, nested

    # 典型决策场景：JSON 后带说明文字 + 嵌套 data
    text2 = '决定如下：{"type":"complex","target_agent":"dfecrab","data":{"agents":["a","b"]}}\n以上'
    parsed2 = extract_json_object(text2)
    assert parsed2["type"] == "complex"
    assert parsed2["data"]["agents"] == ["a", "b"]

    # 右边界仍取最后一个 }，前面的噪声对象不会被误取
    assert extract_json_object('{"noise":1} 决定 {"type":"simple"}')["type"] == "simple"
    # 括号不闭合 / 无 } → None
    assert extract_json_object('{"a":1') is None
    ok("extract_json_object（多策略容错 + 嵌套对象修复）")


def test_extract_json_fragment():
    text = '前缀 {"other":1} 中间 决定：{"type":"complex","target_agent":"a"} 结尾'
    parsed = extract_json_fragment(text)
    assert parsed is not None and parsed["type"] == "complex"
    # 仅当含 type / target_agent / agent 之一才认
    assert extract_json_fragment('{"foo":1}') is None
    assert extract_json_fragment('{"agent":"b"}')["target_agent"] == "b"
    assert extract_json_fragment("") is None
    ok("extract_json_fragment（宽松扫描）")


def test_truncate_system_prompt():
    short = "abc"
    assert truncate_system_prompt(short, 10) == short
    long_text = "A" * 5000
    out = truncate_system_prompt(long_text, 2000)
    assert len(out) < len(long_text)
    assert "Agent列表中间省略" in out
    assert out.startswith("A" * 100)
    assert truncate_system_prompt("", 10) == ""
    ok("truncate_system_prompt（头 70% + 尾 30%）")


def main():
    print("=" * 64)
    print("对话意图工具单测")
    print("=" * 64)
    try:
        test_looks_like_alert_json()
        test_is_alert_signal_json()
        test_normalize_target_agent()
        test_extract_json_object()
        test_extract_json_fragment()
        test_truncate_system_prompt()
        print(f"\n🎉 全部通过（{len(_PASSED)} 组）")
        return True
    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
