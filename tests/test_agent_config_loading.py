"""Agent 配置加载与思考标签剥离单测（守护"丢失 import"类生产故障）

对应真实故障（2026-09-21 日志）：
    ⚠️ 读取 agent [code_writer] tools.json 失败: name 'json' is not defined
    → 技能读不出来（enabled_skills 恒为空）
原因：`orchestration.py` 从 grpc_server 迁出时丢了 `import json`（截断文件恢复），
     `py_compile` 查不出，异常被 except 吞成 warning。

本测试直接走真实链路（真实 agents/*/tools.json、真实 config.json），
任何 import 缺失 / 路径层数错误都会在这里直接失败。

运行：
    python tests/test_agent_config_loading.py    # 期望 exit 0
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gateway.chat import orchestration, pipeline  # noqa: E402
from src.gateway.chat.orchestration import ChatOrchestrationMixin  # noqa: E402
from src.gateway.chat.pipeline import normalize_structured_response  # noqa: E402
from src.gateway.lifecycle import bootstrap  # noqa: E402

_PASSED = []

#: 用于验证的智能体（项目内置，含 tools.json / config.json）
AGENT = "code_writer"


class _Harness(ChatOrchestrationMixin):
    """最小宿主：这些方法只依赖 PROJECT_ROOT 与标准库，可脱离网关实例化"""


def ok(name):
    _PASSED.append(name)
    print(f"  ✅ {name}")


def test_project_root_resolves_to_repo_root():
    root = orchestration.PROJECT_ROOT
    assert (root / "agents").is_dir(), f"agents/ 不存在于 {root}（根目录层数算错）"
    assert (root / "config").is_dir(), f"config/ 不存在于 {root}（根目录层数算错）"
    ok(f"orchestration.PROJECT_ROOT 指向项目根: {root.name}/")


def test_read_agent_skills():
    """核心守护：技能必须能读出来（原故障即此处恒返回 []）"""
    skills = _Harness()._get_agent_skills(AGENT)
    assert skills, f"读取 [{AGENT}] skills 为空 → tools.json 读取链断了（检查缺 import / 路径）"
    assert isinstance(skills, list)
    ok(f"读取 agent[{AGENT}] 技能成功: {skills}")


def test_read_agent_system_prompt():
    prompt = _Harness()._get_agent_system_prompt(AGENT)
    assert prompt and isinstance(prompt, str), f"读取 [{AGENT}] system_prompt 失败"
    ok(f"读取 agent[{AGENT}] system_prompt 成功（{len(prompt)} 字符）")


def test_pipeline_has_http_response():
    """pipeline 需要 HTTPResponse 才能返回非 500 的协议壳"""
    assert hasattr(pipeline, "HTTPResponse"), "pipeline 缺少 HTTPResponse（丢了 import）"
    resp = pipeline.HTTPResponse(200).json({"success": True})
    assert resp.status_code == 200
    ok("pipeline.HTTPResponse 可用（协议壳不误报 500）")


def test_normalize_structured_response_strips_think():
    """思考标签必须被剥离（原故障：_strip_think_tags 未定义 → 标签混入历史）"""
    plain = normalize_structured_response("<think>内部推理过程</think>最终答案")
    assert plain["content"] == "最终答案", plain
    assert "<think>" not in plain["content"]

    import json
    structured = normalize_structured_response(
        json.dumps({"answer_final": "<think>x</think>答案", "other": {"k": 1}},
                   ensure_ascii=False)
    )
    assert structured["content"] == "答案", structured
    assert structured["structured"] == {"k": 1}

    # 空值/纯文本路径
    assert normalize_structured_response(None)["content"] == ""
    assert normalize_structured_response("  ")["content"] == ""
    assert normalize_structured_response("普通文本")["content"] == "普通文本"
    ok("normalize_structured_response 正确剥离思考标签")


def test_grpc_server_still_exports_strip_think_tags():
    """兼容性：grpc_server 仍应从 pipeline 再导出 _strip_think_tags

    静态校验（AST）而非 import：grpc_server 依赖 httpx/grpc 等重型三方库，
    离线环境不可导入，但这不影响本项检查的确定性。
    """
    import ast
    import io

    src = io.open(PROJECT_ROOT / "src" / "gateway" / "grpc_server.py",
                  encoding="utf-8").read()
    tree = ast.parse(src)
    reexported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "src.gateway.chat.pipeline"
        and any(a.name == "_strip_think_tags" for a in node.names)
        for node in ast.walk(tree)
    )
    assert reexported, "grpc_server 未再导出 _strip_think_tags（历史调用方会 ImportError）"
    # 唯一实现必须位于 pipeline 且可用
    assert callable(pipeline._strip_think_tags)
    assert pipeline._strip_think_tags("<think>a</think>b") == "b"
    ok("grpc_server 再导出 _strip_think_tags 正常（唯一实现在 pipeline）")


def test_bootstrap_no_undefined_cfg():
    """bootstrap 不得再引用未定义的 _cfg（否则 ws 心跳配置静默失效）"""
    import ast
    import io

    tree = ast.parse(io.open(bootstrap.__file__, encoding="utf-8").read())
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                bound.add(a.asname or a.name)
        elif isinstance(node, (ast.Import, ast.Assign)):
            for a in getattr(node, "names", []) or []:
                bound.add((a.asname or a.name).split(".")[0])
    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert "_cfg" not in used, "bootstrap.py 仍在引用未定义的 _cfg"
    ok("bootstrap 无未定义 _cfg 引用")


def main():
    print("=" * 64)
    print("Agent 配置加载 / 思考标签剥离单测")
    print("=" * 64)
    try:
        test_project_root_resolves_to_repo_root()
        test_read_agent_skills()
        test_read_agent_system_prompt()
        test_pipeline_has_http_response()
        test_normalize_structured_response_strips_think()
        test_grpc_server_still_exports_strip_think_tags()
        test_bootstrap_no_undefined_cfg()
        print(f"\n🎉 全部通过（{len(_PASSED)} 组）")
        return True
    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
