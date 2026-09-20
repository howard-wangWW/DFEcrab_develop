"""
Skill Validator - 技能格式审查工具
检查技能是否符合 OpenClaw 标准
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple


def parse_yaml_frontmatter(content: str) -> Tuple[Dict[str, any], str]:
    """
    解析 YAML frontmatter

    Args:
        content: 文件内容

    Returns:
        (metadata_dict, body_content)
    """
    if not content.startswith('---'):
        return {}, content

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content

    try:
        import yaml
        metadata = yaml.safe_load(parts[1]) or {}
        body = parts[2]
        return metadata, body
    except ImportError:
        # 如果没有 yaml 库，尝试简单的解析
        yaml_lines = parts[1].strip().split('\n')
        metadata = {}
        for line in yaml_lines:
            match = re.match(r'(\w+):\s*(.+)', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()
                # 处理列表
                if value.startswith('- '):
                    value = [item.strip().lstrip('- ').strip() for item in yaml_lines[yaml_lines.index(line):]]
                metadata[key] = value
        return metadata, parts[2]
    except Exception:
        return {}, content


def validate_skill_directory(skill_dir: Path) -> Tuple[bool, List[str]]:
    """
    验证技能目录是否符合 OpenClaw 标准

    Args:
        skill_dir: 技能目录路径

    Returns:
        (is_valid, error_messages)
    """
    errors = []

    # 检查目录是否存在
    if not skill_dir.exists():
        errors.append(f"❌ 目录不存在: {skill_dir}")
        return False, errors

    # 检查 SKILL.md 文件
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append("❌ 缺少必需文件: SKILL.md")
        return False, errors

    # 读取 SKILL.md 内容
    content = skill_md.read_text(encoding="utf-8")

    # 解析 frontmatter
    metadata, body = parse_yaml_frontmatter(content)

    if not metadata:
        errors.append("❌ SKILL.md 缺少 YAML frontmatter（需要用 --- 包裹）")
        return False, errors

    # 检查必需字段
    required_fields = ["name", "description", "version", "author", "triggers"]

    for field in required_fields:
        if field not in metadata:
            errors.append(f"❌ 缺少必需字段: {field}")
        elif not metadata[field]:
            errors.append(f"❌ 字段 {field} 不能为空")

    # 检查 name 格式（只允许小写字母、数字和连字符）
    if "name" in metadata:
        name = metadata["name"]
        if not re.match(r'^[a-z0-9-]+$', name):
            errors.append(f"❌ name 格式错误: '{name}' 应只包含小写字母、数字和连字符")

    # 检查 version 格式
    if "version" in metadata:
        version = str(metadata["version"])
        if not re.match(r'^\d+\.\d+\.\d+', version):
            errors.append(f"⚠️ version 格式建议使用语义化版本 (如: 1.0.0)")

    # 检查 triggers
    if "triggers" in metadata:
        triggers = metadata["triggers"]
        if not isinstance(triggers, list):
            errors.append(f"❌ triggers 必须是列表类型")
        elif len(triggers) == 0:
            errors.append(f"❌ triggers 列表不能为空")

    # 检查执行文件
    execute_py = skill_dir / "execute.py"
    src_main = skill_dir / "src" / "main.py"

    if not execute_py.exists() and not src_main.exists():
        errors.append("❌ 缺少执行文件: 需要有 execute.py 或 src/main.py")

    # 检查非标准字段（警告）
    non_standard_fields = set(metadata.keys()) - {
        "name", "description", "version", "author", "triggers",
        "emoji", "requires", "parameters", "examples", "tags"
    }
    if non_standard_fields:
        errors.append(f"⚠️ 非标准字段: {', '.join(non_standard_fields)}")

    return len(errors) == 0, errors


def validate_skill_file(skill_file: Path) -> Tuple[bool, List[str]]:
    """
    验证单个技能文件（不支持，仅返回错误）

    Args:
        skill_file: 技能文件路径

    Returns:
        (is_valid, error_messages)
    """
    return False, ["❌ DFEcrab 不再支持单文件技能，请使用目录格式"]


def execute(toolkit=None, **kwargs) -> str:
    """
    技能验证主入口

    支持的参数:
        path: 技能目录路径
        name: 技能名称（在 skills/ 目录下）
        fix: 是否自动修复简单问题 (true/false)
    """
    skills_dir = Path(__file__).parent.parent

    path = kwargs.get("path")
    name = kwargs.get("name")
    fix = str(kwargs.get("fix", "false")).lower() == "true"

    # 确定要验证的路径
    if path:
        skill_path = Path(path)
    elif name:
        skill_path = skills_dir / name
    else:
        # 验证所有技能
        results = []
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("__"):
                continue
            is_valid, errors = validate_skill_directory(skill_dir)
            if is_valid:
                results.append(f"✅ {skill_dir.name} - 格式正确")
            else:
                results.append(f"❌ {skill_dir.name} - {len(errors)} 个问题")
                results.extend([f"   {e}" for e in errors])
        return "\n".join(results)

    # 验证单个技能
    if skill_path.is_file():
        is_valid, errors = validate_skill_file(skill_path)
    else:
        is_valid, errors = validate_skill_directory(skill_path)

    if is_valid:
        return f"✅ 技能验证通过: {skill_path.name}"
    else:
        return "❌ 技能验证失败:\n" + "\n".join(errors)


# 检查技能是否可以安装（供 skill_manager 使用）
def can_install(skill_dir: Path) -> bool:
    """
    检查技能是否符合安装标准

    Args:
        skill_dir: 技能目录路径

    Returns:
        是否可以安装
    """
    is_valid, errors = validate_skill_directory(skill_dir)
    return is_valid


# 测试代码
if __name__ == "__main__":
    skills_dir = Path(__file__).parent.parent

    print("=== 验证所有技能 ===\n")

    invalid_count = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("__"):
            continue

        is_valid, errors = validate_skill_directory(skill_dir)

        if is_valid:
            print(f"✅ {skill_dir.name}")
        else:
            print(f"❌ {skill_dir.name}")
            for error in errors:
                print(f"   {error}")
            invalid_count += 1

    print(f"\n总计: {len(list(skills_dir.iterdir())) - 1} 个技能, {invalid_count} 个不符合标准")
