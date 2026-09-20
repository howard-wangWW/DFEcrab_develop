"""Agent Group - 智能体组管理"""
from typing import Dict, Any, List


class AgentGroup:
    """Agent 组 - 管理任务相关的智能体"""
    
    def __init__(self, task_id: str, task_type, config: Dict[str, Any]):
        self.task_id = task_id
        self.task_type = task_type
        self.config = config
        self.members: List[Dict[str, Any]] = config.get("members", [])
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value if hasattr(self.task_type, 'value') else str(self.task_type),
            "config": self.config,
            "members": self.members,
        }
    
    def get_member(self, agent_id: str) -> Dict[str, Any]:
        """获取指定成员"""
        for member in self.members:
            if member.get("agent_id") == agent_id:
                return member
        return {}
    
    def add_member(self, agent_id: str, role: str = "worker") -> None:
        """添加成员"""
        self.members.append({
            "agent_id": agent_id,
            "role": role,
        })
    
    def remove_member(self, agent_id: str) -> bool:
        """移除成员"""
        for i, member in enumerate(self.members):
            if member.get("agent_id") == agent_id:
                self.members.pop(i)
                return True
        return False
