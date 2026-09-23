"""skill - 按需加载技能说明（对齐 LibreChat 的 skill 工具）

本文件由安装脚本从 execute.py.tpl 渲染生成：
  "Path to the file. For skill files: \\\"{skillName}/{path}\\\" (e.g. \\\"pdf-analyzer/src/utils.py\\\"). For code execution output: the path as returned by the execution tool."  → 工具描述（优先取自上游真实文案）
  "技能名称，取自已挂载技能清单中的 name（如 blackxml-mcp）" → 参数描述
本目录不放置 SKILL.md，因此它只以「工具」身份存在，不会出现在技能清单里。
"""

import re
from pathlib import Path
from typing import Any, Dict

SKILL_METADATA = {
    "name": "skill",
    "description": "Path to the file. For skill files: \\\"{skillName}/{path}\\\" (e.g. \\\"pdf-analyzer/src/utils.py\\\"). For code execution output: the path as returned by the execution tool.",
    "parameters": {
        "type": "object",
        "properties": {
            "skillName": {
                "type": "string",
                "description": "技能名称，取自已挂载技能清单中的 name（如 blackxml-mcp）",
            }
        },
        "required": ["skillName"],
    },
}

_SKILLS_DIR = Path(__file__).resolve().parent.parent
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _read_frontmatter(text: str) -> Dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([\w-]+)\s*:\s*(.*)$", line.rstrip())
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return out


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "yes", "1")


def execute(skillName: str = "") -> Any:
    """加载指定技能的 SKILL.md 正文。

    Args:
        skillName: 技能名称（取自已挂载技能清单）

    Returns:
        ServiceResponse（成功时为技能正文）
    """
    from src.agentscope_compat import ServiceResponse, ServiceExecStatus

    name = (skillName or "").strip()
    if not name:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content="skillName 不能为空；可用技能见 system prompt 中的「已挂载技能清单」。",
        )
    # 防目录穿越：只接受单层目录名
    if name != Path(name).name or name.startswith("."):
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"非法技能名: {name}")

    skill_md = _SKILLS_DIR / name / "SKILL.md"
    if not skill_md.is_file():
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"技能不存在: {name}")

    try:
        text = skill_md.read_text(encoding="utf-8")
    except Exception as exc:
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"读取技能失败: {exc}")

    frontmatter = _read_frontmatter(text)
    if _is_true(frontmatter.get("disable-model-invocation", frontmatter.get("disableModelInvocation"))):
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"技能 {name} 禁止模型调用（disable-model-invocation）。",
        )

    body = _FRONTMATTER_RE.sub("", text, count=1).strip()
    if not body:
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"技能 {name} 无正文内容。")
    return ServiceResponse(status=ServiceExecStatus.SUCCESS, content=body)
