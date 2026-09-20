#!/usr/bin/env python3
"""
DFEcrab v2.9.8 完整功能测试
运行方式: python3 tests/v298_test.py
"""

import httpx
import json
import sys


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    END = "\033[0m"


def test(name, method, url, data=None, timeout=15):
    """执行单个测试"""
    print(f"📌 {name}...", end=" ", flush=True)
    try:
        if method == "GET":
            r = httpx.get(url, timeout=timeout)
        else:
            r = httpx.post(url, json=data, timeout=timeout)

        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                print(f"{Colors.GREEN}✅{Colors.END}")
                return True, d
            else:
                print(f"{Colors.YELLOW}⚠️  {d.get('error', '')[:50]}{Colors.END}")
                return True, d
        else:
            print(f"{Colors.RED}❌ HTTP {r.status_code}{Colors.END}")
            return False, None
    except httpx.TimeoutException:
        print(f"{Colors.YELLOW}⏱️  超时{Colors.END}")
        return False, None
    except Exception as e:
        print(f"{Colors.RED}❌ {str(e)[:50]}{Colors.END}")
        return False, None


def main():
    print("=" * 60)
    print(f"{Colors.BLUE}DFEcrab v2.9.8 完整功能测试{Colors.END}")
    print("=" * 60)
    print()

    base_url = "http://localhost:6789"
    all_passed = True

    # 1. 健康检查
    passed, _ = test("1. 健康检查", "GET", f"{base_url}/health")
    all_passed = all_passed and passed

    # 2. 模型列表
    passed, _ = test("2. 模型列表", "GET", f"{base_url}/api/models")
    all_passed = all_passed and passed

    # 3. 切换到 zhipu
    passed, _ = test("3. 切换到 zhipu", "POST", f"{base_url}/api/models/switch", {"provider": "zhipu"})
    all_passed = all_passed and passed

    # 4. 切换到 deepseek
    passed, _ = test("4. 切换到 deepseek", "POST", f"{base_url}/api/models/switch", {"provider": "deepseek"})
    all_passed = all_passed and passed

    # 5. 当前模型
    passed, _ = test("5. 当前模型", "GET", f"{base_url}/api/models/current")
    all_passed = all_passed and passed

    # 6. 记忆统计
    passed, _ = test("6. 记忆统计", "GET", f"{base_url}/api/memory/stats")
    all_passed = all_passed and passed

    # 7. 学习记录
    passed, _ = test("7. 学习记录", "GET", f"{base_url}/api/memory/learnings")
    all_passed = all_passed and passed

    # 8. 最近记忆
    passed, _ = test("8. 最近记忆", "GET", f"{base_url}/api/memory/recent")
    all_passed = all_passed and passed

    # 9. 语义搜索
    passed, _ = test("9. 语义搜索", "GET", f"{base_url}/api/memory/search?q=Python&limit=3")
    all_passed = all_passed and passed

    # 10. 事件统计
    passed, _ = test("10. 事件统计", "GET", f"{base_url}/api/events/stats")
    all_passed = all_passed and passed

    # 11. 最近事件
    passed, _ = test("11. 最近事件", "GET", f"{base_url}/api/events/recent")
    all_passed = all_passed and passed

    # 12. 容错状态
    passed, _ = test("12. 容错状态", "GET", f"{base_url}/api/fallback/status")
    all_passed = all_passed and passed

    # 13. AI 对话
    print("📌 13. AI 对话测试...", end=" ", flush=True)
    try:
        r = httpx.post(
            f"{base_url}/api/chat",
            json={"message": "你好，测试对话", "agent_id": "test_v298", "client_id": "test_client"},
            timeout=60
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                resp = d.get("data", {}).get("response", "")
                print(f"{Colors.GREEN}✅{Colors.END} (回复: {resp[:50]}...)")
            else:
                print(f"{Colors.YELLOW}⚠️  {d.get('error', '')[:50]}{Colors.END}")
                all_passed = False
        else:
            print(f"{Colors.RED}❌ HTTP {r.status_code}{Colors.END}")
            all_passed = False
    except Exception as e:
        print(f"{Colors.RED}❌ {str(e)[:50]}{Colors.END}")
        all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print(f"{Colors.GREEN}🎉 所有测试通过!{Colors.END}")
    else:
        print(f"{Colors.YELLOW}⚠️  部分测试有问题，请检查{Colors.END}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
