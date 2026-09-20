#!/usr/bin/env python3
"""
DFEcrab 测试套件
整合主要功能测试
"""

import httpx
import json
import sys


def test_api(name, method, url, data=None, timeout=15):
    """执行 API 测试"""
    print(f"📌 {name}...", end=" ", flush=True)
    try:
        if method == "GET":
            r = httpx.get(url, timeout=timeout)
        else:
            r = httpx.post(url, json=data, timeout=timeout)

        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                print("✅")
                return True
            else:
                print(f"⚠️  {d.get('error', '')[:50]}")
                return True
        else:
            print(f"❌ HTTP {r.status_code}")
            return False
    except httpx.TimeoutException:
        print("⏱️  超时")
        return False
    except Exception as e:
        print(f"❌ {str(e)[:50]}")
        return False


def test_models():
    """测试模型管理"""
    print("\n=== 模型管理 ===")
    base_url = "http://localhost:6789"

    test_api("模型列表", "GET", f"{base_url}/api/models")
    test_api("切换到 zhipu", "POST", f"{base_url}/api/models/switch", {"provider": "zhipu"})
    test_api("切换到 deepseek", "POST", f"{base_url}/api/models/switch", {"provider": "deepseek"})
    test_api("当前模型", "GET", f"{base_url}/api/models/current")


def test_memory():
    """测试记忆系统"""
    print("\n=== 记忆系统 ===")
    base_url = "http://localhost:6789"

    test_api("记忆统计", "GET", f"{base_url}/api/memory/stats")
    test_api("学习记录", "GET", f"{base_url}/api/memory/learnings")
    test_api("最近记忆", "GET", f"{base_url}/api/memory/recent")
    test_api("语义搜索", "GET", f"{base_url}/api/memory/search?q=测试&limit=3")


def test_events():
    """测试事件索引"""
    print("\n=== 事件索引 ===")
    base_url = "http://localhost:6789"

    test_api("事件统计", "GET", f"{base_url}/api/events/stats")
    test_api("最近事件", "GET", f"{base_url}/api/events/recent")


def test_fallback():
    """测试容错机制"""
    print("\n=== 容错机制 ===")
    base_url = "http://localhost:6789"

    test_api("容错状态", "GET", f"{base_url}/api/fallback/status")


def test_chat():
    """测试对话功能"""
    print("\n=== 对话功能 ===")
    base_url = "http://localhost:6789"

    print("📌 AI 对话测试...", end=" ", flush=True)
    try:
        r = httpx.post(
            f"{base_url}/api/chat",
            json={"message": "你好", "agent_id": "dfecrab", "client_id": "test_suite"},
            timeout=60
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                resp = d.get("data", {}).get("response", "")
                print(f"✅ (回复: {resp[:50]}...)")
                return True
            else:
                print(f"⚠️  {d.get('error', '')[:50]}")
                return True
        else:
            print(f"❌ HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ {str(e)[:50]}")
        return False


def main():
    print("=" * 60)
    print("DFEcrab 集成测试套件")
    print("=" * 60)

    test_models()
    test_memory()
    test_events()
    test_fallback()
    test_chat()

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
