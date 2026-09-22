"""网关路由快照测试 —— grpc_server.py 拆分期间的"安全网"

作用：重构（抽模块、声明式路由表）过程中，**路由集合必须一字不差**。
任何漏注册/多注册/改路径都会被本测试立刻拦住。

路由来源（按优先级自动探测，兼容拆分前后）：
  1. `src/gateway/routes.py` 的 `ROUTES` 声明表（Phase 2 之后存在）
  2. 否则 AST 解析 `src/gateway/grpc_server.py` 里的 `RouteRule(...)` 调用（拆分前）
  3. 叠加 plan_router 提供的路由（AST 解析其返回字典的 key）
  4. 叠加任务域 `src/task/api_routes.get_task_routes()`

运行：
    python tests/test_gateway_routes.py     # 期望 exit 0
"""

import ast
import io
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GRPC_SERVER = PROJECT_ROOT / "src" / "gateway" / "grpc_server.py"
ROUTES_MODULE = PROJECT_ROOT / "src" / "gateway" / "routes.py"
PLAN_ROUTER = PROJECT_ROOT / "src" / "gateway" / "plan_router.py"

# ──────────────────────────────────────────────────────────────
# 快照（拆分前实测：86 条网关内联路由 + 3 条 plan_router 补充 + 20 条任务路由）
# ──────────────────────────────────────────────────────────────

GOLDEN_BUILTIN = {
    ("GET", "/health"),
    ("POST", "/api/v2/chat"),
    ("POST", "/api/v2/chat/stream"),
    ("GET", "/api/v2/workers"),
    ("GET", "/api/v2/sessions"),
    ("POST", "/api/v2/sessions"),
    ("GET", "/api/v2/sessions/{session_id}"),
    ("GET", "/api/v2/sessions/{session_id}/messages"),
    ("GET", "/api/v2/sessions/{session_id}/usage"),
    ("GET", "/api/v2/usage/stats"),
    ("DELETE", "/api/v2/sessions/deleteSession/{session_id}"),
    ("GET", "/api/users"),
    ("POST", "/api/users"),
    ("PUT", "/api/users/{user_id}"),
    ("DELETE", "/api/users/{user_id}"),
    ("GET", "/api/agents"),
    ("POST", "/api/agents"),
    ("GET", "/api/agents/{agent_id}"),
    ("PUT", "/api/agents/{agent_id}"),
    ("DELETE", "/api/agents/{agent_id}"),
    ("PUT", "/api/agents/{agent_id}/default"),
    ("DELETE", "/api/agents/{agent_id}/default"),
    ("GET", "/api/services"),
    ("GET", "/api/invariants"),
    ("GET", "/api/skills"),
    ("POST", "/api/skills/reload"),
    ("GET", "/api/skills/search"),
    ("GET", "/api/mcp/servers"),
    ("POST", "/api/mcp/servers"),
    ("POST", "/api/mcp/servers/test"),
    ("POST", "/api/mcp/servers/{name}/toggle"),
    ("POST", "/api/mcp/servers/{name}/sync"),
    ("POST", "/api/mcp/servers/{name}/binding"),
    ("DELETE", "/api/mcp/servers/{name}"),
    ("GET", "/api/agents/{agent_id}/mcp"),
    ("POST", "/api/agents/{agent_id}/mcp"),
    ("PUT", "/api/agents/{agent_id}/mcp"),
    ("GET", "/mcp-admin"),
    ("GET", "/api/models"),
    ("GET", "/api/models/current"),
    ("POST", "/api/models"),
    ("POST", "/api/models/switch"),
    ("PUT", "/api/models/{config_name}"),
    ("DELETE", "/api/models/{config_name}"),
    ("POST", "/api/models/{config_name}/toggle"),
    ("POST", "/api/models/{config_name}/discover"),
    ("GET", "/api/fallback/status"),
    ("GET", "/api/memory/stats"),
    ("GET", "/api/memory/recent"),
    ("GET", "/api/memory/search"),
    ("GET", "/api/memory/files"),
    ("GET", "/api/memory/storage"),
    ("GET", "/api/memory/index_health"),
    ("GET", "/api/memory/agents"),
    ("GET", "/api/memory/agents/{agent_id}"),
    ("GET", "/api/memory/users"),
    ("POST", "/api/memory/users/{user_id}"),
    ("PUT", "/api/memory/users/{user_id}/{mem_id}"),
    ("DELETE", "/api/memory/users/{user_id}/{mem_id}"),
    ("GET", "/api/files"),
    ("POST", "/api/files"),
    ("GET", "/api/files/{file_id}/download"),
    ("DELETE", "/api/files/{file_id}"),
    ("GET", "/api/stats/daily"),
    ("GET", "/api/stats/mcp"),
    ("GET", "/api/stats/tokens"),
    ("GET", "/api/stats/trend"),
    ("GET", "/api/stats/overview"),
    ("POST", "/api/images/generate"),
    ("GET", "/api/images/providers"),
    ("GET", "/api/images"),
    ("GET", "/api/images/gallery"),
    ("GET", "/api/images/{image_id}"),
    ("DELETE", "/api/images/{image_id}"),
    ("GET", "/api/events/search"),
    ("GET", "/api/events/recent"),
    ("GET", "/api/events/stats"),
    ("POST", "/api/events/add"),
    ("GET", "/api/plan/current"),
    ("GET", "/api/plan/list"),
    ("POST", "/api/plan/next"),
    ("POST", "/api/plan/skip"),
    ("POST", "/api/plan/cancel"),
    ("GET", "/api/reflections"),
    ("GET", "/api/reflections/{reflection_id}"),
    ("POST", "/api/reflections/{reflection_id}/implement"),
}

#: plan_router 补充的独立路由（与 PlanHandler 重复的会被去重跳过）
GOLDEN_PLAN_ROUTER_UNIQUE = {
    ("GET", "/api/plan/progress"),
    ("GET", "/api/plan/steps"),
    ("POST", "/api/plan/step/execute"),
}

GOLDEN_TASK = {
    ("POST", "/api/v2/tasks"),
    ("GET", "/api/v2/tasks"),
    ("GET", "/api/v2/tasks/{task_id}"),
    ("DELETE", "/api/v2/tasks/{task_id}"),
    ("POST", "/api/v2/tasks/preview"),
    ("POST", "/api/v2/tasks/{task_id}/convert"),
    ("POST", "/api/v2/tasks/{task_id}/approve"),
    ("POST", "/api/v2/tasks/{task_id}/pause"),
    ("POST", "/api/v2/tasks/{task_id}/resume"),
    ("POST", "/api/v2/tasks/{task_id}/trigger"),
    ("POST", "/api/v2/tasks/{task_id}/execute"),
    ("GET", "/api/v2/tasks/{task_id}/progress"),
    ("GET", "/api/v2/tasks/{task_id}/audit"),
    ("GET", "/api/v2/tasks/{task_id}/dashboard"),
    ("GET", "/api/tasks/heartbeats"),
    ("GET", "/api/tasks/scheduled"),
    ("GET", "/api/tasks/stats"),
    ("GET", "/api/tasks/todos"),
    ("POST", "/api/tasks/todos"),
    ("POST", "/api/tasks/todos/{task_id}/complete"),
}


# ──────────────────────────────────────────────────────────────
# 采集
# ──────────────────────────────────────────────────────────────

_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}


def _method_attr(node) -> str:
    """从 `HTTPMethod.GET` 或字符串 `"GET"` 节点取 'GET'"""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _HTTP_METHODS:
        return node.value
    return ""


def _routes_from_route_rule_calls(path: Path):
    """AST 采集 `RouteRule(HTTPMethod.X, "path", ...)` 形式的路由（拆分前的写法）"""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "RouteRule":
            if len(node.args) >= 2:
                method = _method_attr(node.args[0])
                p = node.args[1]
                if method and isinstance(p, ast.Constant) and isinstance(p.value, str):
                    found.add((method, p.value))
    return found


def _routes_from_routes_module():
    """Phase 2 之后：读声明表 ROUTES（(method, path, ref, level, admin_only) 元组列表）"""
    if not ROUTES_MODULE.exists():
        return None
    tree = ast.parse(io.open(ROUTES_MODULE, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple) and len(node.elts) >= 3:
            method = _method_attr(node.elts[0])
            p = node.elts[1]
            if method and isinstance(p, ast.Constant) and isinstance(p.value, str) and p.value.startswith("/"):
                found.add((method, p.value))
    return found


def _routes_from_plan_router():
    """AST 采集 plan_router.get_plan_routes() 返回字典的字符串 key"""
    if not PLAN_ROUTER.exists():
        return set()
    tree = ast.parse(io.open(PLAN_ROUTER, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_plan_routes":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    m = re.match(r"^(GET|POST|PUT|DELETE|PATCH) (/\S+)$", sub.value)
                    if m:
                        found.add((m.group(1), m.group(2)))
    return found


def collect_routes():
    """返回 (全部路由集合, 来源说明)"""
    builtin = _routes_from_routes_module()
    if builtin is None:
        builtin = _routes_from_route_rule_calls(GRPC_SERVER)
    plan_router = _routes_from_plan_router()
    # plan_router 中与内置路由重复的会被注册器去重跳过
    plan_unique = {r for r in plan_router if r not in builtin}

    from src.task.api_routes import get_task_routes
    task = set()
    for spec in get_task_routes():
        method, path = spec.split(" ", 1)
        task.add((method, path))

    return builtin | plan_unique | task, {"builtin": len(builtin), "plan_unique": len(plan_unique), "task": len(task)}


# ──────────────────────────────────────────────────────────────
# 测试
# ──────────────────────────────────────────────────────────────

def test_route_snapshot():
    routes, by_source = collect_routes()
    golden = GOLDEN_BUILTIN | GOLDEN_PLAN_ROUTER_UNIQUE | GOLDEN_TASK

    missing = sorted(golden - routes)
    extra = sorted(routes - golden)

    print(f"路由来源统计: {by_source}")
    print(f"采集到 {len(routes)} 条 / 快照基准 {len(golden)} 条")

    assert not missing, "以下路由丢失（拆分过程中被漏注册）:\n  " + "\n  ".join(f"{m} {p}" for m, p in missing)
    assert not extra, "出现快照之外的新路由（确认是否有意新增）:\n  " + "\n  ".join(f"{m} {p}" for m, p in extra)
    print("✅ 路由快照一致，无丢失、无新增")


def test_no_duplicate_routes():
    """同一来源内不得重复声明同一 method+path（跨来源重复由注册器去重，属预期行为）"""
    builtin = _routes_from_routes_module()
    if builtin is None:
        builtin = _routes_from_route_rule_calls(GRPC_SERVER)
    src = io.open(ROUTES_MODULE if ROUTES_MODULE.exists() else GRPC_SERVER, encoding="utf-8").read()
    if ROUTES_MODULE.exists():
        pairs = re.findall(r'\("(\w+)",\s*"(/[^"]+)"', src)
    else:
        pairs = re.findall(r'HTTPMethod\.(\w+),\s*"(/[^"]+)"', src)
    seen, dups = set(), []
    for item in pairs:
        if item in seen:
            dups.append(item)
        seen.add(item)
    assert not dups, "同文件内出现重复路由声明: " + ", ".join(f"{m} {p}" for m, p in dups)
    assert len(builtin) == len(GOLDEN_BUILTIN), f"内置路由数量异常: {len(builtin)} != {len(GOLDEN_BUILTIN)}"
    print("✅ 无同文件重复路由声明")


GATEWAY_PKG = PROJECT_ROOT / "src" / "gateway"


def _iter_gateway_py():
    """遍历 gateway 包内全部 .py（跳过 __pycache__）"""
    for f in sorted(GATEWAY_PKG.rglob("*.py")):
        if "__pycache__" in str(f):
            continue
        yield f


def _def_locations(name: str):
    """在 gateway 包内查找 `def <name>` 所在文件（用于缺失定位诊断）"""
    hits = []
    for f in _iter_gateway_py():
        try:
            src = io.open(f, encoding="utf-8").read()
        except Exception:
            continue
        if re.search(r"^\s*(async )?def %s\b" % re.escape(name), src, re.M):
            hits.append(str(f.relative_to(PROJECT_ROOT)).replace("\\", "/"))
    return hits


def _collect_gw_methods():
    """收集 `gw:` 可解析的方法名。

    拆分后部分域由 Mixin 承载（如 src/gateway/agent_domain.py:AgentDomainMixin、
    src/gateway/lifecycle/processes.py:ProcessLifecycleMixin），
    因此同时扫描 gateway 包下所有 `*Mixin` 类的方法。
    """
    methods = set()
    files = [GRPC_SERVER] + list(_iter_gateway_py())
    for f in files:
        try:
            tree = ast.parse(io.open(f, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if f != GRPC_SERVER and not node.name.endswith("Mixin"):
                continue
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(sub.name)
    return methods


def test_class_bases_deployed():
    """GatewayV2GRPC 声明的 Mixin 基类必须能在 gateway 包内找到（防"只部署了网关主体"）"""
    src = io.open(GRPC_SERVER, encoding="utf-8").read()
    m = re.search(r"^class GatewayV2GRPC\(([^)]*)\):", src, re.M)
    if not m:
        assert re.search(r"^class GatewayV2GRPC:", src, re.M), "未找到 GatewayV2GRPC 类声明"
        print("⚠️ 类无 Mixin 基类（拆分前版本），跳过")
        return

    bases = [b.strip() for b in m.group(1).split(",") if b.strip()]
    all_src = "\n".join(io.open(f, encoding="utf-8").read() for f in _iter_gateway_py())
    missing = [b for b in bases if not re.search(r"^class %s\b" % re.escape(b), all_src, re.M)]
    assert not missing, (
        "类声明引用的 Mixin 在 gateway 包内找不到定义: " + ", ".join(missing) +
        "\n👉 请确认已上传：src/gateway/agent_domain.py、src/gateway/lifecycle/processes.py"
    )
    print(f"✅ Mixin 基类均已部署: {', '.join(bases)}")


def test_gw_refs_exist():
    """`gw:` 引用的方法必须真实存在于 GatewayV2GRPC 或其 Mixin；缺失时给出定位诊断"""
    if not ROUTES_MODULE.exists():
        print("⚠️ 未启用声明表（拆分前），跳过 gw 引用检查")
        return
    methods = _collect_gw_methods()
    src = io.open(ROUTES_MODULE, encoding="utf-8").read()
    # 只扫描 ROUTES 声明块，避免文档字符串里的示例（如 "gw:<method>"）被误判
    block_start = src.find("ROUTES: List[")
    block_end = src.find("\n]", block_start)
    block = src[block_start:block_end] if block_start != -1 and block_end != -1 else src
    refs = re.findall(r'"gw:(\w+)"', block)
    missing = sorted(set(refs) - methods)

    if missing:
        lines = []
        for name in missing:
            where = _def_locations(name)
            lines.append("  • %-32s %s" % (name, ("定义在 " + ", ".join(where)) if where else "全包内均未找到定义"))
        raise AssertionError(
            "声明表引用了网关类中不存在的方法（GatewayV2GRPC 及其 Mixin），共 %d 个：\n%s\n"
            "👉 排查：\n"
            "   1) 若上面显示「定义在 src/gateway/agent_domain.py」→ 该 Mixin 文件未部署；\n"
            "   2) 若显示「全包内均未找到定义」→ 部署的 tests/test_gateway_routes.py 是旧版"
            "（不支持扫描 *Mixin），请用最新脚本覆盖。" % (len(missing), "\n".join(lines))
        )
    print(f"✅ gw: 引用全部存在（{len(set(refs))} 个方法）")


def main():
    print("=" * 64)
    print("网关路由快照测试（拆分安全网）")
    print("=" * 64)
    try:
        test_route_snapshot()
        test_no_duplicate_routes()
        test_class_bases_deployed()
        test_gw_refs_exist()
        print("\n🎉 全部通过")
        return True
    except AssertionError as e:
        print(f"\n❌ 失败: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
