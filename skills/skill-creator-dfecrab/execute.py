"""
Skill Creator - DFEcrab
快速创建符合 OpenClaw 标准的技能
"""

import os
import re
from pathlib import Path
from datetime import datetime


def create_skill(
    skill_name: str,
    description: str,
    author: str = "DFEcrab",
    triggers: list = None,
    use_src: bool = False
) -> str:
    """
    创建一个新的技能

    Args:
        skill_name: 技能名称（目录名）
        description: 技能描述
        author: 作者名
        triggers: 触发关键词列表
        use_src: 是否使用 src/ 目录结构（复杂技能）

    Returns:
        创建结果信息
    """
    # 规范化技能名称
    skill_name = skill_name.strip().lower().replace(" ", "-")
    skill_name = re.sub(r'[^a-z0-9-]', '', skill_name)

    # 获取技能目录路径
    skills_dir = Path(__file__).parent.parent
    skill_dir = skills_dir / skill_name

    # 检查是否已存在
    if skill_dir.exists():
        return f"❌ 技能已存在: {skill_name}"

    # 创建目录
    skill_dir.mkdir(exist_ok=True)

    # 生成 SKILL.md
    skill_md_content = f"""---
name: {skill_name}
description: {description}
version: "1.0.0"
author: {author}
triggers:"""

    if triggers:
        for trigger in triggers:
            skill_md_content += f'\n  - {trigger}'
    else:
        skill_md_content += f'\n  - {skill_name}'
        skill_md_content += f'\n  - {description.split("，")[0] if "，" in description else description.split(".")[0]}'

    skill_md_content += """
---

# {skill_name}

{description}

## 使用方法

```
[使用示例]
```

## 功能

- [功能1]
- [功能2]
""".format(skill_name=skill_name.replace("-", " ").title(), description=description)

    (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

    # 生成 execute.py 或 src/ 目录
    if use_src:
        # 创建 src/ 目录结构
        src_dir = skill_dir / "src"
        src_dir.mkdir(exist_ok=True)

        # 创建 __init__.py
        (src_dir / "__init__.py").write_text(
            f'"""{skill_name} 模块"""\n\nfrom .main import execute\n',
            encoding="utf-8"
        )

        # 创建 main.py
        main_py_content = f'''"""
{skill_name} 主执行文件
"""

from agentscope.service import ServiceToolkit


def execute(
    toolkit: ServiceToolkit = None,
    **kwargs
) -> str:
    """
    执行 {skill_name} 的主要功能

    Args:
        toolkit: ServiceToolkit 实例
        **kwargs: 其他参数

    Returns:
        执行结果
    """
    # TODO: 实现你的技能逻辑
    return "Hello from {skill_name}!"
'''

        (src_dir / "main.py").write_text(main_py_content, encoding="utf-8")
    else:
        # 创建简单的 execute.py
        execute_py_content = f'''"""
{skill_name} 执行文件
"""

from agentscope.service import ServiceToolkit


def execute(
    toolkit: ServiceToolkit = None,
    **kwargs
) -> str:
    """
    执行 {skill_name}

    Args:
        toolkit: ServiceToolkit 实例
        **kwargs: 其他参数

    Returns:
        执行结果
    """
    # TODO: 实现你的技能逻辑
    return "Hello from {skill_name}!"
'''

        (skill_dir / "execute.py").write_text(execute_py_content, encoding="utf-8")

    # 创建 README.md
    readme_content = f"""# {skill_name.replace("-", " ").title()}

{description}

## 安装

已安装到 DFEcrab 技能目录。

## 使用

```bash
# 列出技能
python3 dfecrab_v2.py skills list

# 测试技能
python3 -c "import sys; sys.path.insert(0, 'skills/{skill_name}'); from execute import execute; print(execute())"
```

## 开发

编辑 `skills/{skill_name}/execute.py` 来实现你的技能逻辑。
"""

    (skill_dir / "README.md").write_text(readme_content, encoding="utf-8")

    return f"✅ 技能创建成功: {skill_name}\n" \
           f"   📁 位置: {skill_dir}\n" \
           f"   📝 请编辑 {'src/main.py' if use_src else 'execute.py'} 来实现技能逻辑"


def execute(toolkit=None, **kwargs) -> str:
    """
    技能创建主入口

    支持的参数:
        name: 技能名称
        description: 技能描述
        author: 作者名
        triggers: 触发关键词（逗号分隔）
        use_src: 是否使用 src/ 目录（true/false）
    """
    name = kwargs.get("name") or kwargs.get("skill_name")
    description = kwargs.get("description")
    author = kwargs.get("author", "DFEcrab")
    triggers_str = kwargs.get("triggers", "")
    use_src = str(kwargs.get("use_src", "false")).lower() == "true"

    if not name:
        return "❌ 请提供技能名称\n\n用法: create_skill(name='技能名', description='描述')"

    if not description:
        return "❌ 请提供技能描述"

    # 处理触发关键词
    triggers = None
    if triggers_str:
        triggers = [t.strip() for t in triggers_str.split(",") if t.strip()]

    return create_skill(
        skill_name=name,
        description=description,
        author=author,
        triggers=triggers,
        use_src=use_src
    )


# 测试代码
if __name__ == "__main__":
    result = execute(
        name="test-skill",
        description="这是一个测试技能",
        triggers=["测试", "test"],
        use_src=False
    )
    print(result)
