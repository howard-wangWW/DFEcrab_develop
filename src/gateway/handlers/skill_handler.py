"""
技能系统处理器

处理技能相关的 HTTP 请求
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SkillHandler:
    """技能系统处理器"""

    # 技能分类与图标映射
    SKILL_CATEGORY_MAP = {
        "dm_query":                {"icon": "🗄️", "category": "数据库", "iconBg": "linear-gradient(135deg, #FF9800, #F57C00)"},
        "dm_meta":                 {"icon": "📋", "category": "数据库", "iconBg": "linear-gradient(135deg, #FF9800, #F57C00)"},
        "dm_test":                 {"icon": "🧪", "category": "数据库", "iconBg": "linear-gradient(135deg, #FF9800, #F57C00)"},
        "load_analysis":           {"icon": "📊", "category": "数据分析", "iconBg": "linear-gradient(135deg, #10b981, #059669)"},
        "calculate":               {"icon": "🧮", "category": "数据分析", "iconBg": "linear-gradient(135deg, #10b981, #059669)"},
        "power_transfer_strategy": {"icon": "⚡", "category": "数据分析", "iconBg": "linear-gradient(135deg, #10b981, #059669)"},
        "summarize":               {"icon": "📝", "category": "内容处理", "iconBg": "linear-gradient(135deg, #06b6d4, #0891b2)"},
        "nano-pdf":                {"icon": "📄", "category": "内容处理", "iconBg": "linear-gradient(135deg, #06b6d4, #0891b2)"},
        "pdf-reader":              {"icon": "📕", "category": "内容处理", "iconBg": "linear-gradient(135deg, #06b6d4, #0891b2)"},
        "pdf-to-kb":               {"icon": "🧠", "category": "内容处理", "iconBg": "linear-gradient(135deg, #06b6d4, #0891b2)"},
        "pdf-tools":               {"icon": "🔧", "category": "内容处理", "iconBg": "linear-gradient(135deg, #06b6d4, #0891b2)"},
        "excel-read":              {"icon": "📊", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "file_manager":            {"icon": "📁", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "file_read":               {"icon": "📃", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "list_dir":                {"icon": "📂", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "word_read":               {"icon": "📘", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "kdocs":                   {"icon": "☁️", "category": "文件处理", "iconBg": "linear-gradient(135deg, #f59e0b, #d97706)"},
        "web-fetch":               {"icon": "🌐", "category": "网络工具", "iconBg": "linear-gradient(135deg, #3b82f6, #1d4ed8)"},
        "planner":                 {"icon": "📋", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "project_memory":          {"icon": "💾", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "memory_maintenance":      {"icon": "🔄", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "find-skill":              {"icon": "🔍", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "clawhub":                 {"icon": "🦀", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "weather":                 {"icon": "🌤️", "category": "生活工具", "iconBg": "linear-gradient(135deg, #8b5cf6, #6d28d9)"},
        "video-frames":            {"icon": "🎬", "category": "媒体工具", "iconBg": "linear-gradient(135deg, #ec4899, #db2777)"},
        "get-time":                {"icon": "🕐", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "get-weekday":             {"icon": "📅", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "echo":                    {"icon": "🔊", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "download-install":        {"icon": "📥", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
        "hello":                   {"icon": "👋", "category": "系统工具", "iconBg": "linear-gradient(135deg, #64748b, #475569)"},
    }

    # 默认分类样式
    DEFAULT_SKILL_STYLE = {"icon": "🔧", "category": "其他", "iconBg": "linear-gradient(135deg, #9ca3af, #6b7280)"}

    @staticmethod
    def _get_project_root() -> Path:
        """获取项目根目录（向上搜索含 skills/ 的目录，部署结构变化也能自愈）"""
        current = Path(__file__).resolve().parent
        for parent in [current] + list(current.parents):
            if (parent / "skills").exists():
                return parent
        return current.parent

    @staticmethod
    def _parse_frontmatter(text: str) -> Dict[str, Any]:
        """从 SKILL.md 中解析 YAML frontmatter"""
        fm = {}
        match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
        if not match:
            return fm
        raw = match.group(1)
        for line in raw.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 简单解析 key: value（支持引号包裹的值）
            m = re.match(r'^(\w[\w-]*)\s*:\s*(.+)$', line)
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip('"').strip("'")
                fm[key] = val
        return fm

    @staticmethod
    def _collect_agent_skills() -> Dict[str, list]:
        """从所有 agent 的 tools.json 中收集每个技能被哪些 agent 使用
        
        Returns:
            {skill_id: [{"id": agent_id, "name": agent_name, "icon": agent_icon}, ...]}
        """
        project_root = SkillHandler._get_project_root()
        agents_dir = project_root / "agents"
        skill_to_agents: Dict[str, list] = {}

        if not agents_dir.exists():
            return skill_to_agents

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            config_path = agent_dir / "config.json"
            tools_path = agent_dir / "tools.json"
            if not tools_path.exists():
                continue

            # 读取 agent 元信息
            agent_id = agent_dir.name
            agent_name = agent_id
            agent_icon = "🤖"
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    agent_name = cfg.get("name", cfg.get("agent_id", agent_id))
                    agent_icon = cfg.get("icon", "🤖")
                    # 如果 name 为空则用 agent_id
                    if not agent_name:
                        agent_name = cfg.get("agent_id", agent_id)
                except Exception:
                    pass

            # 读取该 agent 启用的技能
            try:
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                enabled = tools.get("enabled_skills", [])
                for skill_id in enabled:
                    if skill_id not in skill_to_agents:
                        skill_to_agents[skill_id] = []
                    skill_to_agents[skill_id].append({
                        "id": agent_id,
                        "name": agent_name,
                        "icon": agent_icon
                    })
            except Exception:
                pass

        return skill_to_agents

    @staticmethod
    def _load_skill_detail(skill_id: str) -> Dict[str, Any]:
        """从 skills/ 目录加载单个技能的详细信息
        
        优先读取 _meta.json，然后读取 SKILL.md 的 frontmatter
        """
        project_root = SkillHandler._get_project_root()
        skill_dir = project_root / "skills" / skill_id
        detail: Dict[str, Any] = {}

        if not skill_dir.exists():
            return detail

        # 1. 尝试读取 _meta.json
        meta_path = skill_dir / "_meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                detail["version"] = meta.get("version", "1.0.0")
                detail["author"] = meta.get("author", "")
                if meta.get("description"):
                    detail["description"] = meta["description"]
                # 从 _meta.json 提取参数定义
                params = meta.get("parameters", {})
                if isinstance(params, dict) and "properties" in params:
                    required = params.get("required", [])
                    param_list = []
                    for pname, pdef in params.get("properties", {}).items():
                        param_list.append({
                            "name": pname,
                            "type": pdef.get("type", "string"),
                            "required": pname in required,
                            "description": pdef.get("description", "")
                        })
                    detail["parameters"] = param_list
            except Exception:
                pass

        # 2. 尝试读取 SKILL.md 的 frontmatter
        skill_md_path = skill_dir / "SKILL.md"
        if skill_md_path.exists():
            try:
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                fm = SkillHandler._parse_frontmatter(content)
                # frontmatter 中的字段优先级低于 _meta.json
                if fm.get("name") and not detail.get("name"):
                    detail["name"] = fm["name"]
                if fm.get("description") and not detail.get("description"):
                    detail["description"] = fm["description"]
                if fm.get("version") and not detail.get("version"):
                    detail["version"] = fm["version"]
                if fm.get("author") and not detail.get("author"):
                    detail["author"] = fm["author"]
                if fm.get("triggers") and not detail.get("triggers"):
                    # triggers 是 YAML 列表，简单按行分割
                    triggers_raw = fm["triggers"]
                    if isinstance(triggers_raw, str):
                        detail["triggers"] = [t.strip().strip('- ') for t in triggers_raw.split('\n') if t.strip()]
            except Exception:
                pass

        # 3. 如果没有 description，用技能 ID 生成
        if not detail.get("description"):
            # 尝试把 skill_id 转为可读名称
            readable = skill_id.replace("-", " ").replace("_", " ").title()
            detail["description"] = f"{readable} 技能"

        return detail

    @staticmethod
    async def list_skills(request: Optional[Any] = None) -> Dict[str, Any]:
        """列出所有技能（包含详细信息和使用智能体）

        现在同时从两个维度发现技能：
        - agents/: 已配置给智能体的技能 → status="active"
        - skills/: 所有已安装的技能目录 → 未被 agent 引用的标记为 status="available"
        """
        try:
            project_root = SkillHandler._get_project_root()
            logger.info(f"🛠️ [Skills] list_skills 被调用, project_root={project_root}, exists={project_root.exists()}")
            logger.info(f"🛠️ [Skills] agents_dir={project_root / 'agents'}, exists={(project_root / 'agents').exists()}")
            logger.info(f"🛠️ [Skills] skills_dir={project_root / 'skills'}, exists={(project_root / 'skills').exists()}")

            skill_to_agents = SkillHandler._collect_agent_skills()
            logger.info(f"🛠️ [Skills] _collect_agent_skills 返回 {len(skill_to_agents)} 个技能: {list(skill_to_agents.keys())}")

            if not skill_to_agents:
                project_root = SkillHandler._get_project_root()
                default_tools = project_root / "agents" / "dfecrab" / "tools.json"
                if default_tools.exists():
                    try:
                        with open(default_tools, 'r', encoding='utf-8') as f:
                            tools = json.load(f)
                        for sid in tools.get("enabled_skills", []):
                            if sid not in skill_to_agents:
                                skill_to_agents[sid] = []
                    except Exception:
                        pass

            skills_dir = project_root / "skills"
            all_skill_ids: set = set()
            if skills_dir.exists():
                for entry in skills_dir.iterdir():
                    if entry.is_dir() and not entry.name.startswith('.'):
                        all_skill_ids.add(entry.name)
            logger.info(f"🛠️ [Skills] skills/ 目录下技能数: {len(all_skill_ids)}")

            skills = []
            handled_ids = set()

            for skill_id, agents_using in skill_to_agents.items():
                style = SkillHandler.SKILL_CATEGORY_MAP.get(skill_id, SkillHandler.DEFAULT_SKILL_STYLE)
                detail = SkillHandler._load_skill_detail(skill_id)

                skill_data = {
                    "id": skill_id,
                    "name": detail.get("name", skill_id.replace("-", " ").replace("_", " ").title()),
                    "icon": style["icon"],
                    "iconBg": style["iconBg"],
                    "category": style["category"],
                    "status": "active",
                    "description": detail.get("description", ""),
                    "version": detail.get("version", "1.0.0"),
                    "author": detail.get("author", ""),
                    "agentsUsing": agents_using,
                }
                if detail.get("parameters"):
                    skill_data["parameters"] = detail["parameters"]
                if detail.get("triggers"):
                    skill_data["triggers"] = detail["triggers"]

                skills.append(skill_data)
                handled_ids.add(skill_id)

            for skill_id in sorted(all_skill_ids):
                if skill_id in handled_ids:
                    continue

                style = SkillHandler.SKILL_CATEGORY_MAP.get(skill_id, SkillHandler.DEFAULT_SKILL_STYLE)
                detail = SkillHandler._load_skill_detail(skill_id)

                skill_data = {
                    "id": skill_id,
                    "name": detail.get("name", skill_id.replace("-", " ").replace("_", " ").title()),
                    "icon": style["icon"],
                    "iconBg": style["iconBg"],
                    "category": style["category"],
                    "status": "available",
                    "description": detail.get("description", ""),
                    "version": detail.get("version", "1.0.0"),
                    "author": detail.get("author", ""),
                    "agentsUsing": [],
                }
                if detail.get("parameters"):
                    skill_data["parameters"] = detail["parameters"]
                if detail.get("triggers"):
                    skill_data["triggers"] = detail["triggers"]

                skills.append(skill_data)

            logger.info(f"🛠️ [Skills] 共返回 {len(skills)} 个技能")

            return {
                "success": True,
                "data": {
                    "skills": skills,
                    "total": len(skills)
                }
            }
        except Exception as e:
            logger.error(f"列出技能失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def reload(request: Optional[Any] = None) -> Dict[str, Any]:
        """重新加载技能（扫描 skills/ 目录刷新技能列表）

        技能系统采用无状态设计：list_skills 每次调用都实时扫描文件系统，
        因此 reload 主要起到健康检查 + 扫描验证的作用。
        """
        try:
            project_root = SkillHandler._get_project_root()
            skills_dir = project_root / "skills"

            if not skills_dir.exists():
                return {"success": False, "error": f"skills 目录不存在: {skills_dir}"}

            installed_skills = [
                entry.name for entry in skills_dir.iterdir()
                if entry.is_dir() and not entry.name.startswith('.')
            ]
            skill_to_agents = SkillHandler._collect_agent_skills()

            logger.info(
                f"🛠️ [Skills] reload 完成: 已安装 {len(installed_skills)} 个技能, "
                f"已配置给 agent 的 {len(skill_to_agents)} 个"
            )

            return {
                "success": True,
                "message": "技能已重新加载",
                "data": {
                    "installed_count": len(installed_skills),
                    "active_count": len(skill_to_agents),
                }
            }
        except Exception as e:
            logger.error(f"重新加载技能失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def search(request: Any) -> Dict[str, Any]:
        """搜索技能（通过 clawhub）"""
        try:
            query = request.query_params.get("q", "")

            from src.clawhub import search_skills as clawhub_search
            results = clawhub_search(query)

            return {
                "success": True,
                "data": {
                    "query": query,
                    "results": results
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
