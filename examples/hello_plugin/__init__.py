"""
Hello Plugin - 示例插件
演示如何创建 DFEcrab 插件
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime

from src.plugin_framework.base import BasePlugin, PluginMetadata, ToolDefinition
from src.plugin_framework.context import create_plugin_context

# 插件全局实例（插件加载器通过此变量查找插件）
plugin = None


class HelloPlugin(BasePlugin):
    """
    Hello 示例插件
    
    功能：
    - 演示插件生命周期
    - 展示工具注册
    - 展示事件订阅
    - 展示配置使用
    """
    
    def __init__(self):
        super().__init__()
        self.context = None
        self.message_count = 0
        self.event_subscription_id = None
        self.background_task = None
    
    def _create_metadata(self) -> PluginMetadata:
        """创建插件元数据"""
        return PluginMetadata(
            name="hello",
            version="1.0.0",
            author="DFEcrab Team",
            description="示例插件，演示插件系统的基本功能",
            tags=["example", "demo", "tutorial"],
            dependencies=["skill"]  # 依赖技能插件
        )
    
    async def on_load(self) -> bool:
        """加载插件"""
        try:
            # 创建插件上下文
            self.context = create_plugin_context("hello", "1.0.0")
            self.context.logger.info("HelloPlugin 正在加载...")
            
            # 访问配置
            config = self.context.config
            self.greeting = config.get("greeting", "Hello")
            self.max_count = config.get("max_count", 100)
            
            self.context.logger.info(f"插件配置: greeting={self.greeting}, max_count={self.max_count}")
            return True
            
        except Exception as e:
            self.context.logger.error(f"HelloPlugin 加载失败: {e}")
            return False
    
    async def on_start(self) -> bool:
        """启动插件"""
        try:
            self.context.logger.info("HelloPlugin 正在启动...")
            
            # 订阅消息事件
            self.event_subscription_id = self.context.subscribe_event(
                "message.received",
                self._on_message_received,
                lambda event_data: event_data.get("agent_id") == "default"
            )
            
            # 启动后台任务
            self.background_task = asyncio.create_task(self._background_task())
            
            # 发布自定义事件
            self.context.publish_event("hello.started", {
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0"
            })
            
            self.context.logger.info(f"HelloPlugin 已启动")
            return True
            
        except Exception as e:
            self.context.logger.error(f"HelloPlugin 启动失败: {e}")
            return False
    
    async def on_stop(self) -> bool:
        """停止插件"""
        try:
            self.context.logger.info("HelloPlugin 正在停止...")
            
            # 停止后台任务
            if self.background_task and not self.background_task.done():
                self.background_task.cancel()
                try:
                    await self.background_task
                except asyncio.CancelledError:
                    pass
            
            # 取消事件订阅
            if self.event_subscription_id:
                self.context.unsubscribe_event(self.event_subscription_id)
            
            # 发布停止事件
            self.context.publish_event("hello.stopped", {
                "timestamp": datetime.now().isoformat(),
                "message_count": self.message_count
            })
            
            self.context.logger.info("HelloPlugin 已停止")
            return True
            
        except Exception as e:
            self.context.logger.error(f"HelloPlugin 停止失败: {e}")
            return False
    
    async def on_initialize(self) -> bool:
        """初始化插件（可选）"""
        return True
    
    def get_tools(self) -> List[ToolDefinition]:
        """获取插件提供的工具"""
        return [
            ToolDefinition(
                name="hello_say_hello",
                description="打招呼工具",
                parameters={
                    "name": {"type": "string", "description": "姓名", "default": "World"},
                    "times": {"type": "integer", "description": "重复次数", "default": 1, "minimum": 1, "maximum": 10}
                }
            ),
            ToolDefinition(
                name="hello_get_stats",
                description="获取插件统计信息",
                parameters={
                    "reset": {"type": "boolean", "description": "是否重置计数器", "default": False}
                }
            ),
            ToolDefinition(
                name="hello_trigger_event",
                description="触发自定义事件",
                parameters={
                    "event_type": {"type": "string", "description": "事件类型", "default": "hello.custom"},
                    "message": {"type": "string", "description": "事件消息", "default": "Hello from plugin!"}
                }
            )
        ]
    
    def get_memory_prompts(self) -> Dict[str, str]:
        """获取记忆提示词"""
        return {
            "hello_usage": "This agent uses the HelloPlugin for demonstration purposes. "
                          "It can greet users and provide basic plugin functionality.",
            "hello_tools": "Available tools from HelloPlugin: hello_say_hello, hello_get_stats, hello_trigger_event"
        }
    
    async def on_message(self, message: Dict[str, Any]):
        """消息处理事件（基础类提供）"""
        # 这里不需要实现，因为我们通过事件订阅处理消息
        pass
    
    async def on_agent_start(self, agent_id: str):
        """智能体启动事件"""
        self.context.logger.info(f"智能体启动: {agent_id}")
        self.context.publish_event("hello.agent_started", {"agent_id": agent_id})
    
    async def on_agent_stop(self, agent_id: str):
        """智能体停止事件"""
        self.context.logger.info(f"智能体停止: {agent_id}")
        self.context.publish_event("hello.agent_stopped", {"agent_id": agent_id})
    
    # 工具实现
    
    async def hello_say_hello(self, name: str = "World", times: int = 1) -> str:
        """
        打招呼工具
        
        Args:
            name: 姓名
            times: 重复次数
            
        Returns:
            问候语
        """
        result = f"{self.greeting}, {name}!"
        if times > 1:
            result = " ".join([result] * times)
        
        self.context.logger.info(f"打招呼: {result}")
        return result
    
    async def hello_get_stats(self, reset: bool = False) -> Dict[str, Any]:
        """
        获取插件统计信息
        
        Args:
            reset: 是否重置计数器
            
        Returns:
            统计信息
        """
        stats = {
            "plugin_name": "hello",
            "version": "1.0.0",
            "message_count": self.message_count,
            "config": {
                "greeting": self.greeting,
                "max_count": self.max_count
            },
            "timestamp": datetime.now().isoformat()
        }
        
        if reset:
            old_count = self.message_count
            self.message_count = 0
            stats["reset_from"] = old_count
            self.context.logger.info(f"计数器已重置: {old_count} -> 0")
        
        return stats
    
    async def hello_trigger_event(self, event_type: str = "hello.custom", message: str = "Hello from plugin!") -> bool:
        """
        触发自定义事件
        
        Args:
            event_type: 事件类型
            message: 事件消息
            
        Returns:
            是否成功
        """
        try:
            self.context.publish_event(event_type, {
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "plugin": "hello"
            })
            self.context.logger.info(f"事件已触发: {event_type} - {message}")
            return True
        except Exception as e:
            self.context.logger.error(f"触发事件失败: {e}")
            return False
    
    # 内部方法
    
    async def _on_message_received(self, event_data: Dict[str, Any]):
        """处理消息事件"""
        if self.message_count >= self.max_count:
            return
        
        self.message_count += 1
        message = event_data.get("message", {})
        
        self.context.logger.debug(f"收到消息 #{self.message_count}: {message.get('content', '')[:50]}...")
        
        # 每10条消息触发事件
        if self.message_count % 10 == 0:
            self.context.publish_event("hello.milestone", {
                "count": self.message_count,
                "timestamp": datetime.now().isoformat()
            })
    
    async def _background_task(self):
        """后台任务示例"""
        try:
            self.context.logger.info("后台任务已启动")
            
            counter = 0
            while True:
                try:
                    # 每秒检查一次
                    await asyncio.sleep(10)
                    counter += 10
                    
                    # 每60秒记录一次
                    if counter >= 60:
                        self.context.logger.debug(f"后台任务运行中... 已运行 {counter} 秒")
                        counter = 0
                        
                except asyncio.CancelledError:
                    self.context.logger.info("后台任务已取消")
                    break
                    
        except Exception as e:
            self.context.logger.error(f"后台任务错误: {e}")
    
    # 事件回调（可选）
    async def on_session_start(self, session_id: str, agent_id: str):
        """会话开始时调用"""
        self.context.logger.info(f"会话开始: {session_id}, 智能体: {agent_id}")
    
    async def on_session_end(self, session_id: str, agent_id: str):
        """会话结束时调用"""
        self.context.logger.info(f"会话结束: {session_id}, 智能体: {agent_id}")
    
    async def on_error(self, error: Exception, context: Dict[str, Any]):
        """错误发生时调用"""
        self.context.logger.error(f"插件错误: {error}", exc_info=error)


# 创建插件实例
plugin = HelloPlugin()