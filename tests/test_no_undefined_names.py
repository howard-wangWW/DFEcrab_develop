"""未定义全局名扫描（防"丢失 import"类故障）

背景：源码曾被外部写入截断，恢复时丢失过头部 `import`（如 orchestration.py 少了
`import json`）。这类问题 `py_compile` / `compile()` 完全查不出来，只在运行时抛
`NameError`，且通常被 except 吞掉后只留一条 warning —— 生产上表现为
"技能读不出来 / MCP 读不出来 / 数据为 0" 之类的静默功能缺失。

检查方式：AST 收集模块内**所有被绑定的名字**（import / 赋值 / def / class /
参数 / 推导式目标 / except as / with as / global），再找所有 `Name` 读取；
凡"被读取但全模块从未绑定且不是内建"的名字，即必定 NameError。

运行：
    python tests/test_no_undefined_names.py    # 期望 exit 0
"""

import ast
import builtins
import glob
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SRC = PROJECT_ROOT / "src"
# 内建 + 模块级隐式注入（由导入系统提供，不在 dir(builtins) 里）
BUILTIN_NAMES = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__path__", "__cached__", "__debug__",
}

#: 允许的例外（确有运行时动态注入的名字；带文件前缀精确匹配避免掩盖真问题）
ALLOWLIST = {
    # 例：("src/gateway/grpc_server.py", "some_injected_name"),
}

_PASSED = []


def ok(name):
    _PASSED.append(name)
    print(f"  ✅ {name}")


def _iter_modules():
    for p in sorted(glob.glob(str(SRC / "**" / "*.py"), recursive=True)):
        if "__pycache__" in p:
            continue
        yield Path(p)


def _has_star_import(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return True
    return False


def _bound_names(tree) -> set:
    """收集模块内所有被绑定的名字（不求精确作用域，只求"是否出现过")"""
    names = set()

    def add_target(node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for el in node.elts:
                add_target(el)
        elif isinstance(node, ast.Starred):
            add_target(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    names.add(a.asname or a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                            + ([a.vararg] if a.vararg else [])
                            + ([a.kwarg] if a.kwarg else [])):
                    names.add(arg.arg)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                        + ([a.vararg] if a.vararg else [])
                        + ([a.kwarg] if a.kwarg else [])):
                names.add(arg.arg)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                add_target(t)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            add_target(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            add_target(node.target)
        elif isinstance(node, ast.comprehension):
            add_target(node.target)
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None:
                add_target(node.optional_vars)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.MatchAs):
            if node.name:
                names.add(node.name)
        elif isinstance(node, ast.MatchStar):
            if node.name:
                names.add(node.name)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                names.add(node.rest)
    return names


def _undefined_names(path: Path):
    src = io.open(path, encoding="utf-8", errors="replace").read()
    tree = ast.parse(src, filename=str(path))
    if _has_star_import(tree):
        return None  # 有 import * 无法静态判定，跳过
    bound = _bound_names(tree)
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
            if name in bound or name in BUILTIN_NAMES:
                continue
            if (rel, name) in ALLOWLIST:
                continue
            bad.append((node.lineno, name))
    return sorted(set(bad))


def test_no_undefined_names():
    checked, broken, skipped = 0, [], []
    for path in _iter_modules():
        result = _undefined_names(path)
        if result is None:
            skipped.append(path.relative_to(PROJECT_ROOT).as_posix())
            continue
        checked += 1
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for lineno, name in result:
            broken.append(f"{rel}:{lineno} 使用了未定义的名字 `{name}`（多半是丢了 import）")
    assert not broken, "存在未定义名字（运行时会 NameError，且常被 except 静默吞掉）:\n  " + "\n  ".join(broken)
    extra = f"，跳过 {len(skipped)} 个含 `import *` 的文件" if skipped else ""
    ok(f"全部源码无未定义全局名（扫描 {checked} 个模块{extra}）")


def main():
    print("=" * 64)
    print("未定义全局名扫描（丢失 import 守卫）")
    print("=" * 64)
    try:
        test_no_undefined_names()
        print(f"\n🎉 全部通过（{len(_PASSED)} 组）")
        return True
    except AssertionError as e:
        print(f"\n❌ 检查失败:\n{e}")
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
