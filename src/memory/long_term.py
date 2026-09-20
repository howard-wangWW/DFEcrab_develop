"""
记忆管理器 - 统一管理短期记忆、长期记忆和全局共享记忆

架构：
1. 全局共享记忆 (data/shared_memory/) - 所有Agent共享读取
2. 短期记忆 (内存) - Session内多次交互，Session结束清除
3. 长期记忆 (agents/{id}/memory.json) - 跨Session经验积累
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 项目根目录（使用 resolve() 确保绝对路径）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class MemoryManager:
    """记忆管理器"""
    
    def __init__(self, agent_id: Optional[str] = None, user_id: Optional[str] = None):
        """
        初始化记忆管理器
        
        Args:
            agent_id: Agent ID，如果为None则只访问全局共享记忆
            user_id: 用户 ID，提供后记忆按用户隔离存储在
                    data/memory/users/{user_id}/agents/{agent_id}/；
                    为 None 时保持旧路径 agents/{agent_id}/（兼容内部调用）
        """
        self.agent_id = agent_id
        self.user_id = user_id
        if agent_id and user_id:
            # 按用户隔离：data/memory/users/{user_id}/agents/{agent_id}/
            self.agent_dir = PROJECT_ROOT / "data" / "memory" / "users" / user_id / "agents" / agent_id
        else:
            # 兼容旧调用（无 user_id）：agents/{agent_id}/
            self.agent_dir = PROJECT_ROOT / "agents" / agent_id if agent_id else None
        
        # 短期记忆（内存中，session级别）
        self.short_term_memory: Dict[str, List[Dict]] = {}
        
        # 长期记忆（从磁盘加载）
        self.long_term_memory: Dict = self._load_long_term_memory()
        
        # 全局共享记忆（从磁盘加载）
        self.shared_memory: Dict = self._load_shared_memory()
        
        logger.info(f"🧠 记忆管理器初始化完成: {agent_id or '全局模式'}")
    
    # ==================== 全局共享记忆 ====================
    
    def _load_shared_memory(self) -> Dict:
        """加载全局共享记忆（已停用）

        data/shared_memory/knowledge 电网知识库已移除（与新知识库系统冲突），
        统一返回空字典；get_shared_knowledge / get_grid_context 自动降级为空。
        """
        logger.info("ℹ️ 全局共享知识库已停用（data/shared_memory/knowledge 已移除），shared_memory 置空")
        return {}
    
    def get_shared_knowledge(self, category: Optional[str] = None) -> Dict:
        """
        获取全局共享知识
        
        Args:
            category: 分类名称，如 "电网基础知识", "常用术语" 等
                     如果为None，返回全部
        
        Returns:
            共享知识字典
        """
        if category:
            return self.shared_memory.get(category, {})
        return self.shared_memory
    
    def get_grid_context(self) -> str:
        """
        获取电网背景知识上下文（用于prompt）
        
        Returns:
            格式化的知识文本
        """
        context_parts = []
        
        # 设备类型
        if "电网基础知识" in self.shared_memory:
            devices = self.shared_memory["电网基础知识"].get("设备类型", {})
            if devices:
                context_parts.append("## 电网设备类型")
                for device_name, device_info in devices.items():
                    context_parts.append(f"- **{device_name}**: {device_info.get('description', '')}")
        
        # 告警规则
        if "电网基础知识" in self.shared_memory:
            alerts = self.shared_memory["电网基础知识"].get("告警规则", {})
            if alerts:
                context_parts.append("\n## 告警规则")
                for alert_type, rules in alerts.items():
                    if isinstance(rules, dict):
                        for level, desc in rules.items():
                            context_parts.append(f"- {alert_type}/{level}: {desc}")
        
        # 常用术语
        if "常用术语" in self.shared_memory:
            terms = self.shared_memory["常用术语"]
            if terms:
                context_parts.append("\n## 常用术语")
                for term, desc in terms.items():
                    context_parts.append(f"- **{term}**: {desc}")
        
        return "\n".join(context_parts) if context_parts else ""
    
    # ==================== 短期记忆（Session级别） ====================
    
    def add_to_short_term(self, session_id: str, entry: Dict):
        """
        添加短期记忆（session内交互）
        
        Args:
            session_id: 会话ID
            entry: 记忆条目，包含 role, content, timestamp 等
        """
        if session_id not in self.short_term_memory:
            self.short_term_memory[session_id] = []
        
        self.short_term_memory[session_id].append({
            **entry,
            "timestamp": datetime.now().isoformat()
        })
        
        # 限制短期记忆长度（避免过长导致效能下降）
        max_length = 20  # 每个session最多保留20条交互
        if len(self.short_term_memory[session_id]) > max_length:
            self.short_term_memory[session_id] = self.short_term_memory[session_id][-max_length:]
            logger.debug(f"⚠️  短期记忆截断: {session_id} (保留最近{max_length}条)")
    
    def get_short_term(self, session_id: str) -> List[Dict]:
        """
        获取短期记忆（session内交互历史）
        
        Args:
            session_id: 会话ID
        
        Returns:
            交互历史列表
        """
        return self.short_term_memory.get(session_id, [])
    
    def get_short_term_context(self, session_id: str, max_turns: int = 5) -> str:
        """
        获取短期记忆上下文（用于prompt）
        
        Args:
            session_id: 会话ID
            max_turns: 最大轮数（默认5轮，10条消息）
        
        Returns:
            格式化的对话上下文
        """
        history = self.short_term_memory.get(session_id, [])
        
        if not history:
            return ""
        
        # 只取最近的交互
        recent = history[-max_turns * 2:]  # 每轮2条（用户+AI）
        
        context_parts = [f"## 当前会话历史（最近{max_turns}轮）"]
        for entry in recent:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            context_parts.append(f"{role}: {content}")
        
        return "\n".join(context_parts)
    
    def clear_short_term(self, session_id: str):
        """清除指定session的短期记忆"""
        if session_id in self.short_term_memory:
            del self.short_term_memory[session_id]
            logger.info(f"🧹 已清除短期记忆: {session_id}")
    
    def clear_all_short_term(self):
        """清除所有短期记忆"""
        count = len(self.short_term_memory)
        self.short_term_memory.clear()
        logger.info(f"🧹 已清除所有短期记忆 ({count} 个sessions)")
    
    # ==================== 长期记忆 ====================
    
    def _load_long_term_memory(self) -> Dict:
        """加载长期记忆"""
        if not self.agent_dir:
            return {}
        
        memory_file = self.agent_dir / "memory.json"
        
        if memory_file.exists():
            try:
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"✅ 长期记忆已加载: {memory_file}")
                return data
            except Exception as e:
                logger.error(f"❌ 加载长期记忆失败: {e}")
        
        # 返回默认结构
        return self._default_memory_structure()
    
    def _default_memory_structure(self) -> Dict:
        """默认记忆结构 - V3.0 简化版"""
        return {
            "version": "3.0",
            "agent_id": self.agent_id or "unknown",
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "short_term": {
                "session_context": [],
                "max_turns": 20,
                "last_session": None
            },
            "long_term": {
                "facts": [],
                "patterns": [],
                "lessons": []
            },
            "context": {}
        }
    
    def add_to_long_term(self, category: str, content: str, tags: Optional[List[str]] = None):
        """
        添加长期记忆 - V3.0 简化版

        Args:
            category: 分类 - "facts"（事实）, "patterns"（成功模式）, "lessons"（经验教训）
            content: 记忆内容
            tags: 标签列表（可选）
        """
        if not self.agent_dir:
            logger.warning("⚠️  无法添加长期记忆：未指定agent_id")
            return

        # 支持新格式 (V3.0) 和旧格式
        long_term = self.long_term_memory.get("long_term", {})
        if not long_term:
            # 尝试旧格式
            long_term = self.long_term_memory.get("long_term_memory", {})

        # 分类映射（新格式 -> 旧格式兼容）
        category_map = {
            "facts": "facts",
            "patterns": "patterns",
            "lessons": "lessons",
            # 旧格式兼容
            "professional_knowledge": "facts",
            "successful_patterns": "patterns",
            "lessons_learned": "lessons"
        }

        target_category = category_map.get(category, category)

        if target_category not in ["facts", "patterns", "lessons"]:
            logger.warning(f"⚠️  未知的长期记忆分类: {category}")
            return

        if target_category not in long_term:
            long_term[target_category] = []

        # 添加记忆
        long_term[target_category].append({
            "content": content,
            "tags": tags or [],
            "added_at": datetime.now().isoformat()
        })

        # 更新元数据
        self.long_term_memory["last_updated"] = datetime.now().isoformat()
        self.long_term_memory["long_term"] = long_term

        # 持久化到磁盘
        self._save_long_term_memory()

        logger.info(f"📝 已添加长期记忆: {target_category} ({len(tags or [])} 个标签)")
    
    def get_long_term(self, category: Optional[str] = None) -> Dict:
        """
        获取长期记忆 - V3.0 简化版

        Args:
            category: 分类名称，如果为None返回全部

        Returns:
            长期记忆字典
        """
        # 支持新格式 (V3.0) 和旧格式
        long_term = self.long_term_memory.get("long_term", {})
        if not long_term:
            long_term = self.long_term_memory.get("long_term_memory", {})

        if category:
            return long_term.get(category, [])
        return long_term

    def get_long_term_context(self) -> str:
        """
        获取长期记忆上下文（用于prompt） - V3.0 简化版

        Returns:
            格式化的长期记忆文本
        """
        long_term = self.get_long_term()

        context_parts = []

        # 事实
        facts = long_term.get("facts", [])
        if facts:
            context_parts.append("## 重要事实")
            for item in facts[-10:]:
                context_parts.append(f"- {item['content']}")

        # 成功模式
        patterns = long_term.get("patterns", [])
        if patterns:
            context_parts.append("\n## 成功经验")
            for item in patterns[-5:]:
                context_parts.append(f"- {item['content']}")

        # 经验教训
        lessons = long_term.get("lessons", [])
        if lessons:
            context_parts.append("\n## 注意事项")
            for item in lessons[-5:]:
                context_parts.append(f"- ⚠️ {item['content']}")

        return "\n".join(context_parts) if context_parts else ""
    
    def _save_long_term_memory(self):
        """保存长期记忆到磁盘"""
        if not self.agent_dir:
            return
        
        memory_file = self.agent_dir / "memory.json"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(self.long_term_memory, f, indent=2, ensure_ascii=False)
            logger.debug(f"💾 长期记忆已保存: {memory_file}")
        except Exception as e:
            logger.error(f"❌ 保存长期记忆失败: {e}")
    
    # ==================== 记忆检索 ====================
    
    def search_memory(self, query: str, scope: str = "all", limit: int = 5) -> List[Dict]:
        """
        搜索记忆（简化版，基于关键词匹配）
        
        Args:
            query: 查询关键词
            scope: 搜索范围 - "shared"（全局）, "long_term"（长期）, "all"（全部）
            limit: 返回结果数量限制
        
        Returns:
            匹配的记忆列表
        """
        results = []
        query_lower = query.lower()
        
        # 搜索全局共享记忆
        if scope in ["shared", "all"]:
            results.extend(self._search_in_dict(
                self.shared_memory, 
                query_lower,
                source="shared"
            )[:limit])
        
        # 搜索长期记忆
        if scope in ["long_term", "all"]:
            long_term = self.long_term_memory.get("long_term_memory", {})
            results.extend(self._search_in_dict(
                long_term,
                query_lower,
                source="long_term"
            )[:limit])
        
        return results[:limit]
    
    def _search_in_dict(self, data: Dict, query: str, source: str) -> List[Dict]:
        """在字典中搜索关键词"""
        results = []
        
        def search_recursive(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    if query in str(key).lower() or query in str(value).lower():
                        results.append({
                            "source": source,
                            "path": new_path,
                            "content": str(value)[:200]
                        })
                    search_recursive(value, new_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    search_recursive(item, f"{path}[{i}]")
        
        search_recursive(data)
        return results
    
    # ==================== 统计信息 ====================
    
    def get_memory_stats(self) -> Dict:
        """获取记忆统计信息 - V3.0 简化版"""
        long_term = self.get_long_term()

        return {
            "agent_id": self.agent_id,
            "version": self.long_term_memory.get("version", "unknown"),
            "short_term_sessions": len(self.short_term_memory),
            "short_term_entries": sum(len(v) for v in self.short_term_memory.values()),
            "long_term_facts": len(long_term.get("facts", [])),
            "long_term_patterns": len(long_term.get("patterns", [])),
            "long_term_lessons": len(long_term.get("lessons", [])),
            "shared_memory_loaded": bool(self.shared_memory)
        }
