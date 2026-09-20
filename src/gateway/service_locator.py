"""
服务定位器 - 轻量级依赖注入容器
"""

from typing import Dict, List, Type, Any, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class ServiceRegistration:
    """服务注册信息"""
    
    def __init__(
        self,
        name: str,
        service: Type,
        service_type: Type,
        instance: Any = None,
        factory: Optional[Callable] = None,
        singleton: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.service = service
        self.service_type = service_type
        self.instance = instance
        self.factory = factory
        self.singleton = singleton
        self.metadata = metadata or {}


class ServiceLocator:
    """服务定位器"""
    
    _instance: Optional['ServiceLocator'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._services: Dict[str, ServiceRegistration] = {}
        self._dependencies: Dict[str, List[str]] = {}  # 服务依赖关系
        self._initialized = True
        logger.info("服务定位器初始化完成")
    
    def register(
        self,
        name=None,
        service_type: Type = None,
        instance: Any = None,
        factory: Optional[Callable] = None,
        singleton: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None
    ) -> bool:
        """
        注册服务
        
        Args:
            name: 服务名称（可选，如果只传入实例则自动推断）
            service_type: 服务类型
            instance: 服务实例（单例模式）
            factory: 服务工厂函数
            singleton: 是否单例
            metadata: 元数据
            dependencies: 依赖的其他服务
            
        Returns:
            是否注册成功
        """
        try:
            # 支持简化调用：register(instance)
            if name is None and instance is not None:
                instance_param = instance
                name = instance_param.__class__.__name__
                service_type = type(instance_param)
            elif name is not None and service_type is None and instance is not None:
                # 支持 register(name='xxx', instance=obj)
                pass
            elif name is not None and service_type is not None:
                # 完整调用：register(name='xxx', service_type=Cls, instance=obj)
                pass
            else:
                logger.error(f"register() 参数错误：name={name}, service_type={service_type}, instance={instance}")
                return False
            
            if name in self._services:
                logger.warning(f"服务已注册：{name}")
                return False
            
            registration = ServiceRegistration(
                name=name,
                service=service_type,
                service_type=service_type,
                instance=instance,
                factory=factory,
                singleton=singleton,
                metadata=metadata or {}
            )
            
            self._services[name] = registration
            self._dependencies[name] = dependencies or []
            
            logger.info(f"服务注册成功：{name}")
            return True
        except Exception as e:
            logger.error(f"服务注册失败 [{name}]: {e}")
            return False
    
    def unregister(self, name: str) -> bool:
        """
        注销服务
        
        Args:
            name: 服务名称
            
        Returns:
            是否注销成功
        """
        try:
            if name not in self._services:
                logger.warning(f"服务不存在：{name}")
                return False
            
            del self._services[name]
            if name in self._dependencies:
                del self._dependencies[name]
            
            logger.info(f"服务注销成功：{name}")
            return True
        except Exception as e:
            logger.error(f"服务注销失败 [{name}]: {e}")
            return False
    
    def get(self, name: str) -> Optional[Any]:
        """
        获取服务实例
        
        Args:
            name: 服务名称
            
        Returns:
            服务实例
        """
        try:
            if name not in self._services:
                logger.warning(f"服务不存在：{name}")
                return None
            
            registration = self._services[name]
            
            # 单例模式
            if registration.singleton:
                if registration.instance is None:
                    # 如果没有实例，尝试创建
                    if registration.factory:
                        registration.instance = registration.factory()
                    elif registration.service:
                        registration.instance = registration.service()
                
                return registration.instance
            else:
                # 非单例模式，每次创建新实例
                if registration.factory:
                    return registration.factory()
                elif registration.service:
                    return registration.service()
                return None
        except Exception as e:
            logger.error(f"获取服务失败 [{name}]: {e}")
            return None
    
    def has(self, name: str) -> bool:
        """
        检查服务是否存在
        
        Args:
            name: 服务名称
            
        Returns:
            是否存在
        """
        return name in self._services
    
    def list_services(self) -> List[str]:
        """
        列出所有服务
        
        Returns:
            服务名称列表
        """
        return list(self._services.keys())
    
    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取服务元数据
        
        Args:
            name: 服务名称
            
        Returns:
            元数据
        """
        if name not in self._services:
            return None
        
        return self._services[name].metadata
    
    def check_dependencies(self) -> Dict[str, List[str]]:
        """
        检查服务依赖
        
        Returns:
            未满足的依赖列表
        """
        unsatisfied = {}
        
        for name, deps in self._dependencies.items():
            missing = [dep for dep in deps if dep not in self._services]
            if missing:
                unsatisfied[name] = missing
        
        return unsatisfied
    
    async def initialize_all(self) -> bool:
        """
        初始化所有服务
        
        Returns:
            是否全部初始化成功
        """
        try:
            # 检查依赖
            unsatisfied = self.check_dependencies()
            if unsatisfied:
                logger.error(f"服务依赖未满足：{unsatisfied}")
                return False
            
            # 初始化所有服务
            for name, registration in self._services.items():
                if registration.instance and hasattr(registration.instance, 'initialize'):
                    if not await registration.instance.initialize():
                        logger.error(f"服务初始化失败：{name}")
                        return False
            
            logger.info("所有服务初始化完成")
            return True
        except Exception as e:
            logger.error(f"服务初始化失败：{e}")
            return False
    
    async def shutdown_all(self) -> None:
        """关闭所有服务"""
        for name, registration in self._services.items():
            if registration.instance and hasattr(registration.instance, 'shutdown'):
                try:
                    await registration.instance.shutdown()
                except Exception as e:
                    logger.error(f"服务关闭失败 [{name}]: {e}")
        
        self._services.clear()
        self._dependencies.clear()
        self._initialized = False
        
        logger.info("所有服务已关闭")
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        获取服务健康状态
        
        Returns:
            健康状态
        """
        status = {}
        
        for name, registration in self._services.items():
            service_status = {
                "name": name,
                "type": registration.service_type.__name__,
                "singleton": registration.singleton,
                "metadata": registration.metadata
            }
            
            if registration.instance:
                if hasattr(registration.instance, 'get_health_status'):
                    service_status["health"] = registration.instance.get_health_status()
                elif hasattr(registration.instance, 'status'):
                    service_status["status"] = registration.instance.status
                else:
                    service_status["status"] = "running"
            else:
                service_status["status"] = "not_initialized"
            
            status[name] = service_status
        
        return status


# 全局单例
_service_locator_instance: Optional[ServiceLocator] = None


def get_service_locator() -> ServiceLocator:
    """获取全局服务定位器实例"""
    global _service_locator_instance
    if _service_locator_instance is None:
        _service_locator_instance = ServiceLocator()
    return _service_locator_instance
