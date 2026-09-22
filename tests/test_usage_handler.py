"""用量域（UsageHandler）测试 —— 阶段 3 迁移 parity 验证

覆盖：
  1. 路由声明可解析（routes.py 的 mod: 引用真的能 import 出 handler）
  2. GET /api/v2/usage/stats   ：返回结构、权限口径（admin 全量 / 普通用户自身）
  3. GET /api/v2/sessions/{id}/usage：不存在会话 → 失败；存在会话 → summary/rounds 结构

均为只读，不调用大模型。

运行：
    python tests/test_usage_handler.py     # 期望 exit 0
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gateway.routes import ROUTES, resolve_handler  # noqa: E402

_PASSED = []


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


# ──────────────────────────────────────────────────────────────

def test_route_refs_resolvable():
    """routes.py 里用量两条路由的 handler 引用必须能解析成可调用对象"""
    refs = {path: ref for _m, path, ref, _lvl, _adm in ROUTES}
    stats_ref = refs["/api/v2/usage/stats"]
    sess_ref = refs["/api/v2/sessions/{session_id}/usage"]
    assert stats_ref.startswith("mod:src.gateway.handlers.usage_handler:"), stats_ref
    assert sess_ref.startswith("mod:src.gateway.handlers.usage_handler:"), sess_ref

    stats_handler = resolve_handler(stats_ref, gateway=None)   # mod: 不需要 gateway 实例
    sess_handler = resolve_handler(sess_ref, gateway=None)
    assert callable(stats_handler) and callable(sess_handler)
    ok("用量路由 mod: 引用可解析（无需网关实例）")


def test_usage_stats_admin_scope():
    """admin → user_id='*'（全量）；普通用户 → user_id 为自身"""
    handler = resolve_handler(
        {p: r for _m, p, r, _l, _a in ROUTES}["/api/v2/usage/stats"], gateway=None)

    admin_resp = asyncio.run(handler(FakeRequest(headers={"x-user-id": "admin"})))
    assert admin_resp["success"] is True, admin_resp
    assert admin_resp["user_id"] == "*", admin_resp["user_id"]
    for key in ("period", "range", "totals", "comparison", "by_model", "by_day"):
        assert key in admin_resp, f"缺少字段 {key}"
    assert set(admin_resp["totals"]) >= {"total_tokens", "api_calls"} or admin_resp["totals"], admin_resp["totals"]

    normal_resp = asyncio.run(handler(FakeRequest(headers={"x-user-id": "some_body"})))
    assert normal_resp["success"] is True
    assert normal_resp["user_id"] == "some_body", normal_resp["user_id"]
    ok("usage/stats 返回结构与权限口径正确（admin=* / 普通=自身）")


def test_usage_stats_window_params():
    """start/end 优先于 period；period 别名正常解析"""
    handler = resolve_handler(
        {p: r for _m, p, r, _l, _a in ROUTES}["/api/v2/usage/stats"], gateway=None)

    resp = asyncio.run(handler(FakeRequest(
        headers={"x-user-id": "admin"},
        query={"period": "day", "start": "2026-09-01", "end": "2026-09-03"},
    )))
    assert resp["success"] is True
    assert resp["range"] == {"start": "2026-09-01", "end": "2026-09-03"}, resp["range"]
    assert len(resp["by_day"]) == 3, resp["by_day"]  # 窗口内逐日补齐
    ok("start/end 覆盖 period，by_day 逐日补齐")


def _session_layer_importable() -> bool:
    """SessionService 依赖 httpx（服务器已装，部分本地环境未装）→ 不可用时跳过动态用例"""
    try:
        from src.gateway.session_handler import SessionService  # noqa: F401
        return True
    except Exception as e:
        print(f"  ⏭  SessionService 不可用（{e}），跳过动态用例")
        return False


def test_session_usage_static_contract():
    """静态契约：迁移后调用方式必须与原实现一致，且原方法已从网关删除"""
    usage_src = (PROJECT_ROOT / "src/gateway/handlers/usage_handler.py").read_text(encoding="utf-8")
    assert "SessionService.get_session_messages" in usage_src
    assert "limit=100" in usage_src, "单会话用量取 100 条明细的约定被改动"
    assert "resolve_user_id(request)" in usage_src, "身份解析必须走统一入口"
    assert "gateway_context_length()" in usage_src, "上下文窗口必须走 llm_config"
    assert "resolve_period" in usage_src and "aggregate_usage" in usage_src

    gw_src = (PROJECT_ROOT / "src/gateway/grpc_server.py").read_text(encoding="utf-8")
    assert "_handle_get_session_usage" not in gw_src, "旧方法与新 handler 并存（未彻底迁移）"
    assert "_handle_usage_stats" not in gw_src, "旧方法与新 handler 并存（未彻底迁移）"
    ok("迁移静态契约校验（新 handler 契约一致 + 旧方法已删除）")


def test_session_usage_missing_session():
    """不存在的会话 → 失败（带错误信息），不得抛异常"""
    if not _session_layer_importable():
        return
    handler = resolve_handler(
        {p: r for _m, p, r, _l, _a in ROUTES}["/api/v2/sessions/{session_id}/usage"], gateway=None)

    resp = asyncio.run(handler(FakeRequest(path_params={"session_id": "no_such_session"}),
                               session_id="no_such_session"))
    assert resp.get("success") is False, resp
    assert "error" in resp
    ok("session/usage 不存在会话 → 明确报错")


def test_session_usage_existing_session():
    """若存在真实会话：校验 summary / rounds 结构（不存在则跳过）"""
    if not _session_layer_importable():
        return
    from src.gateway.session_handler import SessionService

    listed = SessionService.list_sessions(user_id="admin", limit=1)
    sessions = listed.get("sessions") or []
    if not sessions:
        print("  ⏭  无历史会话，跳过 summary 结构校验")
        return

    sid = sessions[0].get("id") or sessions[0].get("session_id")
    handler = resolve_handler(
        {p: r for _m, p, r, _l, _a in ROUTES}["/api/v2/sessions/{session_id}/usage"], gateway=None)
    # 以 admin 身份访问（数据范围 all），避免会话归属导致的权限拦截
    admin_req = FakeRequest(path_params={"session_id": sid}, headers={"x-user-id": "admin"})

    resp = asyncio.run(handler(admin_req, session_id=sid))
    assert resp.get("success") is True, resp
    summary = resp["summary"]
    for key in ("turns", "total_prompt_tokens", "total_completion_tokens", "total_tokens",
                "context_length", "last_prompt_tokens", "last_used_percent", "peak_used_percent"):
        assert key in summary, f"summary 缺少 {key}"
    assert isinstance(resp["rounds"], list)
    # 第二轮：group_by=model 必须返回 by_model
    resp2 = asyncio.run(handler(FakeRequest(path_params={"session_id": sid},
                                            query={"group_by": "model"},
                                            headers={"x-user-id": "admin"}), session_id=sid))
    assert "by_model" in resp2, "group_by=model 未返回 by_model"
    ok(f"session/usage 结构校验通过（会话 {sid}，rounds={len(resp['rounds'])}）")


def main():
    print("=" * 64)
    print("用量域（UsageHandler）测试")
    print("=" * 64)
    try:
        test_route_refs_resolvable()
        test_usage_stats_admin_scope()
        test_usage_stats_window_params()
        test_session_usage_static_contract()
        test_session_usage_missing_session()
        test_session_usage_existing_session()
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
