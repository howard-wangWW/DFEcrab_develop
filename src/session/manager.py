"""
Session Manager - 会话管理器

职责：
1. 会话生命周期管理（创建、查询、关闭、删除）
2. 会话消息存储（用户消息、AI响应）
3. 自动摘要生成（首次对话时调用 LLM 生成会话摘要）
4. 会话历史传递（将最近消息传递给 Manager Agent）
5. 会话过期清理

架构：
用户请求 → Gateway 检查 session_id
          ├─ 有 session_id → 复用现有会话
          └─ 无 session_id → 创建新会话 → 调用 LLM 生成摘要
          
Manager Agent 接收：
  - message: 当前用户消息
  - session_id: 会话 ID
  - session_history: 最近 N 条消息（上下文）
  - session_summary: 会话摘要（如果有）
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4
from enum import Enum

from src.agent.agent_config import normalize_agent_id

logger = logging.getLogger(__name__)


class ClientType(Enum):
    """客户端类型"""
    API = "api"
    WEBSOCKET = "websocket"
    CLI = "cli"
    WEB = "web"


class SessionStatus(Enum):
    """会话状态"""
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"


class MessageStatus(str, Enum):
    """消息处理状态（参考 WorkBuddy / 龙虾 / Claude Code Manager）"""
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELED = "canceled"


class Message:
    """单条消息（成熟平台的标准结构）

    核心扩展字段：
    - id / parent_id:        稳定可引用的消息标识（前端气泡、跳转、分支对话）
    - status / error:        明确这条消息是成功 / 失败 / 进行中 —— 错误有独立结构，不再藏在 content 里
    - tokens / duration_ms:  Token 用量、端到端耗时，用于成本和性能观测
    - model / agent_id:      实际用了哪个模型、哪个 Agent 处理，用于可追溯
    - task_type / agents_used / execution_flow / tool_calls: 完整执行链路
    - audit_log_id / correlation_id: 跨系统追踪
    - rating:                用户点赞/点踩，用于 RLHF 信号
    - reasoning:             完整思考过程（Manager + Worker）
    - structured:            结构化输出字段（如 answer_final 之外的 other：recommendQuestions/Voice_File/DataType/conversation_id）
    """

    def __init__(
        self,
        role: str,
        content: str,
        id: Optional[str] = None,
        parent_id: Optional[str] = None,
        status: Optional[MessageStatus] = None,
        error: Optional[Dict[str, Any]] = None,
        tokens: Optional[Dict[str, int]] = None,
        duration_ms: Optional[int] = None,
        model: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
        agents_used: Optional[List[str]] = None,
        execution_flow: Optional[List[Any]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        audit_log_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        rating: Optional[bool] = None,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict] = None,
        reasoning: Optional[str] = None,
        structured: Optional[Dict[str, Any]] = None,
    ):
        self.id = id or f"msg_{uuid4().hex[:16]}"
        self.parent_id = parent_id
        self.role = role
        self.content = content
        if status is None:
            self.status = MessageStatus.PENDING if role == "assistant" else MessageStatus.COMPLETED
        else:
            self.status = status if isinstance(status, MessageStatus) else MessageStatus(status)
        self.error = error
        self.tokens = tokens or {}
        self.duration_ms = duration_ms
        self.model = model
        self.agent_id = agent_id
        self.task_type = task_type
        self.agents_used = agents_used or []
        self.execution_flow = execution_flow or []
        self.tool_calls = tool_calls or []
        self.audit_log_id = audit_log_id
        self.correlation_id = correlation_id
        self.rating = rating
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.metadata = metadata or {}
        self.reasoning = reasoning or ""
        self.structured = structured or {}

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "role": self.role,
            "content": self.content,
            "status": self.status.value if isinstance(self.status, MessageStatus) else self.status,
            "error": self.error,
            "tokens": self.tokens,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "agents_used": self.agents_used,
            "execution_flow": self.execution_flow,
            "tool_calls": self.tool_calls,
            "audit_log_id": self.audit_log_id,
            "correlation_id": self.correlation_id,
            "rating": self.rating,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "reasoning": self.reasoning,
            "structured": self.structured,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        status_raw = data.get("status")
        if status_raw:
            try:
                status = MessageStatus(status_raw)
            except ValueError:
                status = MessageStatus.COMPLETED
        else:
            status = MessageStatus.COMPLETED
        return cls(
            id=data.get("id"),
            parent_id=data.get("parent_id"),
            role=data["role"],
            content=data["content"],
            status=status,
            error=data.get("error"),
            tokens=data.get("tokens"),
            duration_ms=data.get("duration_ms"),
            model=data.get("model"),
            agent_id=data.get("agent_id"),
            task_type=data.get("task_type"),
            agents_used=data.get("agents_used"),
            execution_flow=data.get("execution_flow"),
            tool_calls=data.get("tool_calls"),
            audit_log_id=data.get("audit_log_id"),
            correlation_id=data.get("correlation_id"),
            rating=data.get("rating"),
            timestamp=data.get("timestamp"),
            metadata=data.get("metadata", {}),
            reasoning=data.get("reasoning", ""),
            structured=data.get("structured", {}),
        )


class Session:
    """会话对象

    文件拆分说明（设计正确，保留）：
    - {session_id}.json            元数据小文件（列表页、会话卡片用，体积小读取快）
    - {session_id}_messages.json   消息大文件（进入会话详情页才按需加载）

    元数据新增：
    - schema_version:              结构版本，未来迁移用
    - tags / pinned:               标签 / 置顶，会话管理 UI
    - last_message_preview / last_message_role: 列表页卡片直接看最后一条内容
    - error_count:                 失败计数（会话列表用红色角标提醒）
    - total_tokens:                累计 Token 用量（可选计费 / 配额展示）
    """

    SCHEMA_VERSION = 2

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: str = "default",
        agent_id: str = "dfecrab",
        client_type: ClientType = ClientType.API,
        topic: Optional[str] = None,
        tags: Optional[List[str]] = None,
        pinned: bool = False,
    ):
        self.id = session_id or f"session_{uuid4().hex[:12]}"
        self.user_id = user_id
        self.agent_id = agent_id
        self.client_type = client_type
        self.messages = []
        self.status = SessionStatus.ACTIVE
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.topic = topic or "未命名会话"
        self.summary = ""
        self.message_count = 0
        self.summary_generated = False
        self.tags = tags or []
        self.pinned = pinned
        self.metadata: Dict[str, Any] = {}  # ★ v4.0: 会话元数据（如 pending_clarification）

    def to_dict(self, messages: Optional[List["Message"]] = None) -> Dict:
        def _fmt_time(t):
            if not t:
                return ""
            try:
                return datetime.fromisoformat(t.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                return t

        messages = messages or []
        last_msg = messages[-1] if messages else None

        error_count = 0
        total_tokens = 0
        for m in messages:
            if not isinstance(m, Message):
                continue
            if m.error:
                error_count += 1
            if m.tokens:
                total_tokens += int(m.tokens.get("total", 0) or 0)

        last_message_preview = ""
        last_message_role = ""
        if isinstance(last_msg, Message):
            last_message_preview = (last_msg.content or "").replace("\n", " ")[:80]
            last_message_role = last_msg.role

        return {
            "schema_version": Session.SCHEMA_VERSION,
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "client_type": self.client_type.value,
            "status": self.status.value,
            "topic": self.topic,
            "summary": self.summary,
            "tags": self.tags,
            "pinned": self.pinned,
            "created_at": _fmt_time(self.created_at),
            "last_active": _fmt_time(self.last_active),
            "message_count": self.message_count,
            "summary_generated": self.summary_generated,
            "last_message_preview": last_message_preview,
            "last_message_role": last_message_role,
            "error_count": error_count,
            "total_tokens": total_tokens,
        }


class SessionManager:
    """会话管理器"""
    
    def __init__(
        self,
        storage_dir: str = "data/sessions",
        max_messages_per_session: int = 100,
        session_timeout_minutes: int = 120
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_messages = max_messages_per_session
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        
        # 内存缓存
        self._sessions: Dict[str, Session] = {}
        self._messages: Dict[str, List[Message]] = {}
        
        # 加载已有会话
        self._load_sessions()
        
        logger.info(f"✅ SessionManager 初始化完成")
        logger.info(f"   ├─ 存储目录: {self.storage_dir}")
        logger.info(f"   ├─ 最大消息数: {self.max_messages}")
        logger.info(f"   └─ 会话超时: {session_timeout_minutes} 分钟")
    
    def _load_sessions(self):
        """从文件系统加载会话"""
        if not self.storage_dir.exists():
            return
        
        # 加载所有会话文件（排除 _messages.json）
        all_files = sorted(
            [f for f in self.storage_dir.glob("*.json") if not f.name.endswith("_messages.json")],
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )[:500]  # 最多加载最近500个(保留更多历史会话)
        
        for session_file in all_files:
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    session = Session(
                        session_id=data["id"],
                        user_id=data.get("user_id", "default"),
                        agent_id=normalize_agent_id(data.get("agent_id", "dfecrab")),
                        client_type=ClientType(data.get("client_type", "api")),
                        topic=data.get("topic"),
                        tags=data.get("tags"),
                        pinned=bool(data.get("pinned", False)),
                    )
                    session.status = SessionStatus(data.get("status", "active"))
                    session.created_at = data.get("created_at", session.created_at)
                    session.last_active = data.get("last_active", session.last_active)
                    session.summary = data.get("summary", "")
                    session.summary_generated = data.get("summary_generated", False)
                    session.message_count = data.get("message_count", 0)

                    self._sessions[session.id] = session
                    self._messages[session.id] = None
            except Exception as e:
                logger.error(f"❌ 加载会话失败 {session_file}: {e}")
        
        logger.info(f"📂 已加载 {len(self._sessions)} 个会话（消息延迟加载）")
    
    def create_session(
        self,
        session_id: Optional[str] = None,
        user_id: str = "default",
        agent_id: str = "dfecrab",
        client_type: ClientType = ClientType.API,
        topic: Optional[str] = None,
        tags: Optional[List[str]] = None,
        pinned: bool = False,
    ) -> Session:
        """创建新会话"""
        # 兼容旧调用方传入的 "default" → 归一化为 "dfecrab"
        agent_id = normalize_agent_id(agent_id) or "dfecrab"
        session = Session(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            client_type=client_type,
            topic=topic,
            tags=tags,
            pinned=pinned,
        )

        self._sessions[session.id] = session
        self._messages[session.id] = []

        logger.info(f"🆕 创建新会话: {session.id}")
        logger.info(f"   ├─ 用户: {user_id}")
        logger.info(f"   ├─ 智能体: {agent_id}")
        logger.info(f"   └─ 主题: {topic or '未命名'}")

        return session

    def _mark_expired_if_needed(self, session: Session, session_id: str) -> Session:
        """仅用于内存驻留管理：超时才标记为已过期(EXPIRED)，但不阻止历史读取

        原实现会在超时后让 get_session 返回 None，导致历史会话无法查看。
        这里只更新状态，永远不让历史会话"消失"。
        """
        try:
            last_active = datetime.fromisoformat(session.last_active)
            if datetime.now() - last_active > self.session_timeout:
                if session.status == SessionStatus.ACTIVE:
                    session.status = SessionStatus.EXPIRED
                    logger.info(f"⏰ 会话已过期(历史仍可读): {session_id}")
        except Exception:
            # last_active 缺失/格式异常时不做过期判断，保证历史可读
            pass
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话（优先内存；未命中则从文件恢复；历史会话永久可读，不因超时判为不存在）

        注意：会话超时只用于内存驻留优化，绝不能导致历史消息不可查。
        """
        session = self._sessions.get(session_id)
        if session:
            session = self._mark_expired_if_needed(session, session_id)
            session.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return session

        session_file = self.storage_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            session = Session(
                session_id=data["id"],
                user_id=data.get("user_id", "default"),
                agent_id=normalize_agent_id(data.get("agent_id", "dfecrab")),
                client_type=ClientType(data.get("client_type", "api")),
                topic=data.get("topic"),
                tags=data.get("tags"),
                pinned=bool(data.get("pinned", False)),
            )
            session.status = SessionStatus(data.get("status", "active"))
            session.created_at = data.get("created_at", session.created_at)
            session.last_active = data.get("last_active", session.last_active)
            session.summary = data.get("summary", "")
            session.summary_generated = data.get("summary_generated", False)
            session.message_count = data.get("message_count", 0)

            session = self._mark_expired_if_needed(session, session_id)
            session.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self._sessions[session.id] = session
            self._messages[session.id] = None
            logger.info(f"📂 成功从文件恢复会话: {session_id}")
            return session
        except Exception as e:
            logger.error(f"❌ 从文件恢复会话失败 {session_id}: {e}")
            return None

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        user_id: str = "default",
        agent_id: str = "dfecrab",
        client_type: ClientType = ClientType.API,
        topic: Optional[str] = None,
        tags: Optional[List[str]] = None,
        pinned: bool = False,
    ) -> Session:
        """获取或创建会话"""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
            else:
                logger.warning(f"⚠️ 会话不存在或已过期: {session_id}，创建新会话 (使用指定的ID)")
                return self.create_session(
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    client_type=client_type,
                    topic=topic,
                    tags=tags,
                    pinned=pinned,
                )

        return self.create_session(
            user_id=user_id,
            agent_id=agent_id,
            client_type=client_type,
            topic=topic,
            tags=tags,
            pinned=pinned,
        )

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
        **message_extras,
    ) -> Message:
        """添加消息（向后兼容：旧调用只传 role/content/metadata 即可；新调用可透传任意 Message 字段）

        示例（新字段透传）：
            session_mgr.add_message(
                session_id, "assistant", content,
                status=MessageStatus.COMPLETED,
                error=None,
                tokens={"prompt": 120, "completion": 40, "total": 160},
                duration_ms=1523,
                model="qwen3_32b",
                agent_id="kunming",
                task_type="query",
                agents_used=["kunming", "dfecrab"],
                execution_flow=[...],
                tool_calls=[...],
                audit_log_id="audit_xxx",
                correlation_id="bubble_xxx",
                parent_id="msg_prev_xxx",
            )
        """
        if session_id not in self._messages:
            self._messages[session_id] = []
        elif self._messages[session_id] is None:
            self._load_messages_for_session(session_id)
            if self._messages.get(session_id) is None:
                self._messages[session_id] = []

        message = Message(
            role=role,
            content=content,
            metadata=metadata,
            **message_extras,
        )

        self._messages[session_id].append(message)

        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.message_count = len(self._messages[session_id])
            session.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if len(self._messages[session_id]) > self.max_messages:
            self._messages[session_id] = self._messages[session_id][-self.max_messages:]

        return message

    def update_message(
        self,
        session_id: str,
        message_id: str,
        **fields,
    ) -> Optional[Message]:
        """按 message_id 更新已有消息（流式结束后补全 content/status/error/tokens/duration_ms 等）

        Returns:
            更新后的 Message 对象；找不到则返回 None
        """
        if self._messages.get(session_id) is None:
            self._load_messages_for_session(session_id)

        messages = self._messages.get(session_id) or []
        for idx, m in enumerate(messages):
            if m.id == message_id:
                for k, v in fields.items():
                    if hasattr(m, k):
                        setattr(m, k, v)
                return messages[idx]
        return None

    def session_to_dict(self, session: Session, load_messages: bool = True) -> Dict:
        """把 Session 转成完整 dict（含最后一条预览、错误计数、累计 Token 等）

        Args:
            load_messages: 是否加载消息（列表页可传 False 用内存里已有的，详情页传 True 保证统计准确）
        """
        messages: List[Message] = []
        if load_messages:
            messages = self.get_messages(session.id, limit=self.max_messages)
        else:
            cached = self._messages.get(session.id)
            messages = cached if isinstance(cached, list) else []
        return session.to_dict(messages=messages)
    
    def get_messages(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Message]:
        """获取消息历史"""
        # 延迟加载消息
        if self._messages.get(session_id) is None:
            self._load_messages_for_session(session_id)
        
        messages = self._messages.get(session_id, [])
        return messages[-limit:]
    
    def _load_messages_for_session(self, session_id: str):
        """按需加载单个会话的消息"""
        messages_file = self.storage_dir / f"{session_id}_messages.json"
        if messages_file.exists():
            try:
                with open(messages_file, 'r', encoding='utf-8') as mf:
                    messages_data = json.load(mf)
                    if isinstance(messages_data, dict):
                        messages_data = messages_data.get("messages", [])
                    self._messages[session_id] = [
                        Message.from_dict(m) for m in messages_data if isinstance(m, dict)
                    ]
            except Exception as e:
                logger.error(f"❌ 加载消息失败 {session_id}: {e}")
                self._messages[session_id] = []
        else:
            self._messages[session_id] = []
    
    def get_messages_as_dicts(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """获取消息历史（字典格式）"""
        messages = self.get_messages(session_id, limit)
        return [m.to_dict() for m in messages]
    
    def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.status = SessionStatus.CLOSED
        session.last_active = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"🔒 会话已关闭: {session_id}")
        return True
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话（包括消息）"""
        if session_id not in self._sessions:
            return False
        
        del self._sessions[session_id]
        self._messages.pop(session_id, None)
        
        # 删除文件
        session_file = self.storage_dir / f"{session_id}.json"
        messages_file = self.storage_dir / f"{session_id}_messages.json"
        
        if session_file.exists():
            session_file.unlink()
        if messages_file.exists():
            messages_file.unlink()
        
        logger.info(f"🗑️ 会话已删除: {session_id}")
        return True
    
    def list_sessions(
        self,
        status: Optional[SessionStatus] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        include_empty: bool = False,
    ) -> List[Session]:
        """列出会话（默认只返回活跃会话）

        Args:
            status: 仅当显式传入时才按状态精确过滤；否则返回全部会话(含历史/已过期)
            user_id: 按用户过滤
            limit: 返回条数上限
            include_empty: 是否包含空会话（message_count==0）。
                默认 False：空会话只在内存暂存、列表页不展示（参考成熟平台：发了第一条消息才真正出现在列表）；
                管理员/草稿场景可传 True 查看。
        """
        sessions = list(self._sessions.values())

        # 过滤：默认返回全部会话(含历史/已过期)，便于长期回看历史；
        # 仅当显式传入 status 时才按状态精确过滤
        if status is not None:
            sessions = [s for s in sessions if s.status == status]

        # 空会话（仅新建、未发任何消息）默认不展示
        if not include_empty:
            sessions = [s for s in sessions if s.message_count > 0]

        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]

        # 按最后活跃时间排序
        sessions.sort(key=lambda s: s.last_active, reverse=True)

        return sessions[:limit]
    
    def set_summary(self, session_id: str, summary: str):
        """设置会话摘要"""
        if session_id in self._sessions:
            self._sessions[session_id].summary = summary
            self._sessions[session_id].summary_generated = True
            logger.info(f"📝 会话摘要已设置: {session_id}")
            logger.info(f"   └─ 摘要: {summary[:100]}...")
    
    def set_metadata(self, session_id: str, key: str, value: Any):
        """★ v4.0: 设置会话元数据

        Args:
            session_id: 会话 ID
            key: 元数据键
            value: 元数据值
        """
        if session_id not in self._sessions:
            logger.warning(f"[Session] set_metadata 失败: 会话 {session_id} 不存在")
            return
        self._sessions[session_id].metadata[key] = value

    def get_metadata(self, session_id: str, key: str) -> Optional[Any]:
        """★ v4.0: 获取会话元数据

        Args:
            session_id: 会话 ID
            key: 元数据键

        Returns:
            元数据值，不存在返回 None
        """
        if session_id not in self._sessions:
            return None
        return self._sessions[session_id].metadata.get(key)

    def delete_metadata(self, session_id: str, key: str):
        """★ v4.0: 删除会话元数据

        Args:
            session_id: 会话 ID
            key: 元数据键
        """
        if session_id not in self._sessions:
            return
        self._sessions[session_id].metadata.pop(key, None)

    def save_session(self, session_id: str):
        """保存会话到文件"""
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        messages = self._messages.get(session_id) or []

        session_file = self.storage_dir / f"{session_id}.json"
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session.to_dict(messages=messages), f, ensure_ascii=False, indent=2)

        messages_file = self.storage_dir / f"{session_id}_messages.json"
        messages_data = [m.to_dict() for m in messages]
        with open(messages_file, 'w', encoding='utf-8') as f:
            json.dump(messages_data, f, ensure_ascii=False, indent=2)
    
    def cleanup_expired(self) -> int:
        """清理过期会话"""
        now = datetime.now()
        expired_ids = []
        
        for session_id, session in self._sessions.items():
            if session.status != SessionStatus.ACTIVE:
                continue
            
            last_active = datetime.fromisoformat(session.last_active)
            if now - last_active > self.session_timeout:
                expired_ids.append(session_id)
        
        for session_id in expired_ids:
            self.close_session(session_id)
            logger.info(f"🧹 清理过期会话: {session_id}")
        
        return len(expired_ids)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total = len(self._sessions)
        active = sum(1 for s in self._sessions.values() if s.status == SessionStatus.ACTIVE)
        closed = sum(1 for s in self._sessions.values() if s.status == SessionStatus.CLOSED)
        expired = sum(1 for s in self._sessions.values() if s.status == SessionStatus.EXPIRED)
        total_messages = sum(len(msgs) for msgs in self._messages.values())
        
        return {
            "total_sessions": total,
            "active_sessions": active,
            "closed_sessions": closed,
            "expired_sessions": expired,
            "total_messages": total_messages
        }


# 全局单例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局 SessionManager 单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(session_timeout_minutes=72*60)  # 72小时
    return _session_manager
