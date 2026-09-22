"""阶段 3 迁移 parity 测试：用户 / Worker / 反思 / 系统 四个域

校验点：
  1. routes.py 的 9 条迁移路由引用可解析（mod: 惰性导入成功）
  2. 各 handler 无网关实例即可工作（依赖经 lifecycle.zookeeper 模块级注册表注入）
  3. 原方法已从 grpc_server.py 删除（不残留双实现）

运行：
    python tests/test_gateway_handlers.py     # 期望 exit 0
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gateway.routes import ROUTES, resolve_handler  # noqa: E402

_PASSED = []
_REFS = {path: ref for _m, path, ref, _l, _a in ROUTES}


def ok(name):
    _PASSED.append(name)
    print(f"  ✅ {name}")


class FakeRequest:
    def __init__(self, body=None, query=None, path_params=None, headers=None):
        self.body = json.dumps(body).encode("utf-8") if body is not None else b""
        self._json = body or {}
        self.query_params = query or {}
        self.path_params = path_params or {}
        self.headers = headers or {}

    async def json(self):
        return self._json


MIGRATED = {
    "/api/users": "user_handler",
    "/api/users/{user_id}": "user_handler",
    "/api/v2/workers": "worker_handler",
    "/api/services": "worker_handler",
    "/api/invariants": "worker_handler",
    "/api/reflections": "reflection_handler",
    "/api/reflections/{reflection_id}": "reflection_handler",
}


def test_refs_resolvable():
    for path, module in MIGRATED.items():
        ref = _REFS[path]
        assert ref.startswith(f"mod:src.gateway.handlers.{module}:"), f"{path} 仍指向 {ref}"
        assert callable(resolve_handler(ref, gateway=None)), path
    ok(f"{len(MIGRATED)} 条迁移路由引用可解析（无需网关实例）")


def test_old_methods_removed():
    """迁移后：旧实现不得残留在网关主体；关键装配语句必须存在于 gateway 包内"""
    gw = (PROJECT_ROOT / "src/gateway/grpc_server.py").read_text(encoding="utf-8")
    for name in ("_handle_list_users", "_handle_create_user", "_handle_update_user",
                 "_handle_delete_user", "_handle_list_workers", "_handle_list_services",
                 "_handle_check_invariants", "_handle_list_reflections",
                 "_handle_get_reflection", "_handle_implement_improvements",
                 "_discover_worker_service", "_call_worker_grpc"):
        assert name not in gw, f"旧方法仍残留在 grpc_server: {name}"

    # 装配语句随 initialize 迁入 lifecycle/bootstrap.py，故按"包内"校验
    import glob
    import io as _io
    pkg = "\n".join(
        _io.open(p, encoding="utf-8").read()
        for p in glob.glob(str(PROJECT_ROOT / "src" / "gateway" / "**" / "*.py"), recursive=True)
    )
    assert "set_discovery(self._zk_discovery)" in pkg, "ZK 注册表未注入（bootstrap 缺失？）"
    assert (PROJECT_ROOT / "src" / "gateway" / "lifecycle" / "bootstrap.py").exists(), \
        "lifecycle/bootstrap.py 未部署"
    assert "return zk_instance_agent_id(inst)" in gw, "_zk_instance_agent_id 未改为委托"
    ok("旧方法已清除 + ZK 注册表已注入 + 实例解析已委托（按包内校验）")


def test_worker_handler():
    handler = resolve_handler(_REFS["/api/v2/workers"], gateway=None)
    resp = asyncio.run(handler(FakeRequest()))
    # 未注入 discovery（未启动网关）→ 明确报错，而不是抛异常
    assert resp.get("success") is False and "Zookeeper" in resp.get("error", ""), resp

    # 注入一个假 discovery，验证分组与 agent_id 解析
    from src.gateway.lifecycle.zookeeper import set_discovery
    from src.gateway.handlers.worker_handler import WorkerHandler

    class _FakeDiscovery:
        def discover_service(self, service_type):
            return [
                {"host": "10.0.0.1", "port": 9001, "service_id": "dfecrab_agent_1",
                 "metadata": {"agent_id": "dfecrab", "version": "1.0"}},
                {"host": "10.0.0.2", "port": 9002, "service_id": "dfecrab_agent_2",
                 "metadata": {"agent_id": "dfecrab", "version": "1.0"}},
                {"host": "10.0.0.3", "port": 9003, "service_id": "other_agent_9",
                 "metadata": {}},
            ]

    set_discovery(_FakeDiscovery())
    try:
        resp = asyncio.run(WorkerHandler.list_workers(FakeRequest()))
        assert resp["success"] is True, resp
        assert resp["total"] == 3 and resp["unique_agents"] == 2, resp
        assert set(resp["grouped"]) == {"dfecrab", "other"}, resp["grouped"]
        # 无 metadata 时按 service_id 前缀解析
        assert any(w["agent_id"] == "other" for w in resp["workers"])
    finally:
        set_discovery(None)
    ok("WorkerHandler：未注入报错 + 注入后分组/解析正确")


def test_system_handler():
    services = asyncio.run(resolve_handler(_REFS["/api/services"], gateway=None)(FakeRequest()))
    assert services.get("services") == [], services
    inv = asyncio.run(resolve_handler(_REFS["/api/invariants"], gateway=None)(FakeRequest()))
    assert "invariants" in inv, inv
    ok("WorkerHandler：services 空占位 + invariants 结构保留")


def test_reflection_handler():
    get_handler = resolve_handler(_REFS["/api/reflections/{reflection_id}"], gateway=None)
    resp = asyncio.run(get_handler(FakeRequest(path_params={"reflection_id": "no_such_id"}),
                                   reflection_id="no_such_id"))
    assert resp.get("success") is False and "反思报告不存在" in resp.get("error", ""), resp

    impl_handler = resolve_handler(
        {p: r for _m, p, r, _l, _a in ROUTES}["/api/reflections/{reflection_id}/implement"], gateway=None)
    resp2 = asyncio.run(impl_handler(FakeRequest(path_params={"reflection_id": "no_such_id"}),
                                    reflection_id="no_such_id"))
    assert resp2.get("success") is False, resp2

    # 列表：无论 reflector 是否可用，都必须返回 dict 且不抛异常
    list_handler = resolve_handler(_REFS["/api/reflections"], gateway=None)
    resp3 = asyncio.run(list_handler(FakeRequest(query={"limit": "5"})))
    assert isinstance(resp3, dict) and "success" in resp3, resp3
    ok("ReflectionHandler：不存在→明确报错，列表接口健壮")


def test_user_handler():
    handler = resolve_handler(_REFS["/api/users"], gateway=None)
    resp = asyncio.run(handler(FakeRequest()))
    # UserService 可用时返回账号映射；不可用时返回 success=false，不得抛异常
    assert isinstance(resp, dict) and "success" in resp, resp
    ok("UserHandler：列表接口可调用（结构/异常均受控）")


def main():
    print("=" * 64)
    print("阶段 3 迁移 parity 测试（users / workers / reflections / services）")
    print("=" * 64)
    try:
        test_refs_resolvable()
        test_old_methods_removed()
        test_worker_handler()
        test_system_handler()
        test_reflection_handler()
        test_user_handler()
        print(f"\n🎉 全部通过（{len(_PASSED)} 组）")
        return True
    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
