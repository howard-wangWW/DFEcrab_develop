"""拆分安全网（路径与依赖方向）

拆分/搬迁代码时最容易引入、又最难察觉的两类问题：

  1. **PROJECT_ROOT 层数写错**（如 `parents[2]` 指到 `src/` 而不是项目根）
     → 读不到 `agents/`、`config/` 等目录，表现为"技能不加载""system_prompt 丢失"，
     且不报错、只静默返回空。本测试逐个模块校验换算结果。
  2. **反向依赖**（域模块 import `src.gateway.grpc_server`）
     → 形成环、拆分失效。本测试禁止 chat/handlers/lifecycle 包反向依赖。

运行：
    python tests/test_module_paths.py     # 期望 exit 0
"""

import glob
import io
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SRC = PROJECT_ROOT / "src"
_PASSED = []


def ok(name):
    _PASSED.append(name)
    print(f"  ✅ {name}")


def _iter_modules():
    for p in sorted(glob.glob(str(SRC / "**" / "*.py"), recursive=True)):
        if "__pycache__" in p:
            continue
        yield Path(p)


def _is_project_root(p: Path) -> bool:
    """判定是否为项目根：同时存在 config/、src/、agents/ 三个目录"""
    try:
        return all((p / d).is_dir() for d in ("config", "src", "agents"))
    except Exception:
        return False


def test_project_root_declarations():
    """所有由 `__file__` 推导的根常量都必须指向真正的项目根。

    覆盖两种写法（口径换算：`parent`×N 等价于 `parents[N-1]`）：
        X = Path(__file__).resolve().parents[K]
        X = Path(__file__).resolve().parent.parent...
    变量名不限于 PROJECT_ROOT（如 _ROOT / _PROJECT_ROOT / CONFIG_PATH / _SESSION_DIR）。

    为什么重要：层数写错会让代码静默读到空目录（技能不加载 / 数据写错位置），
    历史上已因此出现过"有技能却提示未配置技能"的故障。
    """
    pat = re.compile(
        r"^([A-Z_][A-Z0-9_]*)\s*=\s*Path\(__file__\)\.resolve\(\)\.(parents\[(\d+)\]|(parent(?:\.parent)*))",
        re.M,
    )
    checked, broken = 0, []
    for path in _iter_modules():
        src = io.open(path, encoding="utf-8", errors="replace").read()
        for m in pat.finditer(src):
            name = m.group(1)
            # 口径换算：parents[N] → N；parent×N → N-1
            depth = int(m.group(3)) if m.group(3) is not None else m.group(4).count("parent") - 1
            calc = path.resolve().parents[depth]
            checked += 1
            if _is_project_root(calc):
                continue
            correct = None
            for d in range(0, 7):
                if _is_project_root(path.resolve().parents[d]):
                    correct = d
                    break
            rel = path.relative_to(PROJECT_ROOT)
            broken.append(f"{rel}: {name} → parents[{depth}] = {calc}（正确应为 parents[{correct}]）")
    assert not broken, "根目录常量层数错误（会导致读不到 agents/config 目录）:\n  " + "\n  ".join(broken)
    ok(f"根目录常量全部正确（{checked} 处，含 parents[N] 与 parent 链两种写法）")


def test_no_hardcoded_project_root():
    """禁止硬编码绝对路径当 PROJECT_ROOT（换机器即失效）"""
    pat = re.compile(r"PROJECT_ROOT\s*=\s*Path\((['\"])(/[^'\"]*|[A-Za-z]:[^'\"]*)\1\)")
    bad = []
    for path in _iter_modules():
        src = io.open(path, encoding="utf-8", errors="replace").read()
        for m in pat.finditer(src):
            bad.append(f"{path.relative_to(PROJECT_ROOT)}: {m.group(0).strip()}")
    assert not bad, "存在硬编码 PROJECT_ROOT:\n  " + "\n  ".join(bad)
    ok("无硬编码 PROJECT_ROOT")


def test_no_reverse_dependency_on_grpc_server():
    """域模块（chat / handlers / lifecycle）不得 import grpc_server（依赖必须单向）"""
    forbidden = re.compile(r"(from\s+src\.gateway\.grpc_server\s+import|import\s+src\.gateway\.grpc_server)")
    bad = []
    for sub in ("chat", "handlers", "lifecycle"):
        for p in sorted(glob.glob(str(SRC / "gateway" / sub / "**" / "*.py"), recursive=True)):
            if "__pycache__" in p:
                continue
            src = io.open(p, encoding="utf-8", errors="replace").read()
            for m in forbidden.finditer(src):
                bad.append(f"{Path(p).relative_to(PROJECT_ROOT)}: {m.group(0)}")
    assert not bad, "域模块出现对 grpc_server 的反向依赖（会形成环）:\n  " + "\n  ".join(bad)
    ok("chat / handlers / lifecycle 包无反向依赖 grpc_server")


def test_gateway_files_no_null_bytes():
    """源码不得含空字节（历史上出现过写入污染，导致 import 期 SyntaxError）"""
    bad = []
    for path in _iter_modules():
        raw = open(path, "rb").read()
        if b"\x00" in raw:
            bad.append(str(path.relative_to(PROJECT_ROOT)))
    assert not bad, "以下文件含空字节，需要修复:\n  " + "\n  ".join(bad)
    ok("全部源码无空字节")


def main():
    print("=" * 64)
    print("拆分安全网：路径与依赖方向")
    print("=" * 64)
    try:
        test_project_root_declarations()
        test_no_hardcoded_project_root()
        test_no_reverse_dependency_on_grpc_server()
        test_gateway_files_no_null_bytes()
        print(f"\n🎉 全部通过（{len(_PASSED)} 组）")
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
