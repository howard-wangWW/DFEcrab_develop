"""
Zookeeper服务注册与发现

职责：
1. 服务注册：启动时将自己的信息注册到Zookeeper
2. 服务发现：从Zookeeper获取其他服务的地址
3. 健康检查：通过临时节点实现服务心跳
"""

import json
import logging
import socket
import time
from typing import Dict, List, Optional
from kazoo.client import KazooClient
from kazoo.recipe.watchers import ChildrenWatch

logger = logging.getLogger(__name__)


class ZKServiceRegistry:
    """Zookeeper服务注册器"""
    
    def __init__(self, zk_hosts: str = None, namespace: str = "dfecrab"):
        """
        初始化Zookeeper注册器
        
        Args:
            zk_hosts: Zookeeper地址，如 "127.0.0.1:2181"
            namespace: 命名空间，用于隔离不同环境的服务
        """
        from src.config.config_loader import config as _cfg
        if zk_hosts is None:
            zk_hosts = _cfg.zk_hosts
        self.zk_hosts = zk_hosts
        self.namespace = namespace
        self.base_path = f"/{namespace}/services"
        self.zk: Optional[KazooClient] = None
        self._registered = False
        
    def connect(self) -> bool:
        """连接到Zookeeper"""
        try:
            self.zk = KazooClient(hosts=self.zk_hosts, timeout=10.0)
            self.zk.start()
            logger.info(f"✅ 已连接到 Zookeeper: {self.zk_hosts}")
            
            # 确保基础路径存在
            self._ensure_path(self.base_path)
            
            return True
        except Exception as e:
            logger.error(f"❌ Zookeeper连接失败: {e}")
            return False
    
    def register_service(
        self,
        service_name: str,
        service_id: str,
        host: str,
        port: int,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        注册服务到Zookeeper
        
        Args:
            service_name: 服务名称，如 "worker_agent", "manager_agent"
            service_id: 服务实例ID，通常包含主机名和时间戳
            host: 服务主机地址
            port: 服务端口
            metadata: 额外元数据（版本、权重等）
        """
        if not self.zk or not self.zk.connected:
            logger.error("Zookeeper未连接")
            return False
        
        try:
            # 创建服务路径
            service_path = f"{self.base_path}/{service_name}"
            self._ensure_path(service_path)
            
            # 创建临时节点（服务断开连接时自动删除）
            instance_path = f"{service_path}/{service_id}"
            instance_data = {
                "service_name": service_name,
                "service_id": service_id,
                "host": host,
                "port": port,
                "metadata": metadata or {},
                "registered_at": time.time(),
                "hostname": socket.gethostname()
            }
            
            # 创建临时节点
            self.zk.create(
                instance_path,
                value=json.dumps(instance_data).encode(),
                ephemeral=True,
                makepath=True
            )
            
            self._registered = True
            logger.info(f"✅ 服务已注册: {service_name}/{service_id} -> {host}:{port}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 服务注册失败: {e}")
            return False
    
    def deregister_service(self, service_name: str, service_id: str) -> bool:
        """注销服务"""
        if not self.zk or not self.zk.connected:
            return False
        
        try:
            instance_path = f"{self.base_path}/{service_name}/{service_id}"
            if self.zk.exists(instance_path):
                self.zk.delete(instance_path)
                logger.info(f"👋 服务已注销: {service_name}/{service_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ 服务注销失败: {e}")
            return False
    
    def discover_service(self, service_name: str) -> List[Dict]:
        """
        发现服务实例
        
        Args:
            service_name: 服务名称
            
        Returns:
            服务实例列表，每个实例包含host、port、metadata等信息
        """
        if not self.zk or not self.zk.connected:
            logger.error("Zookeeper未连接")
            return []
        
        try:
            service_path = f"{self.base_path}/{service_name}"
            if not self.zk.exists(service_path):
                logger.warning(f"服务未找到: {service_name}")
                return []
            
            # 获取所有实例
            children = self.zk.get_children(service_path)
            instances = []
            
            for child in children:
                instance_path = f"{service_path}/{child}"
                data, _ = self.zk.get(instance_path)
                if data:
                    instance_info = json.loads(data.decode())
                    instances.append(instance_info)
            
            logger.debug(f"🔍 发现 {len(instances)} 个 {service_name} 实例")
            return instances
            
        except Exception as e:
            logger.error(f"❌ 服务发现失败: {e}")
            return []
    
    def get_service(self, service_name: str, strategy: str = "random") -> Optional[Dict]:
        """
        获取单个服务实例（带负载均衡策略）
        
        Args:
            service_name: 服务名称
            strategy: 负载均衡策略，"random" 或 "first"
        """
        instances = self.discover_service(service_name)
        
        if not instances:
            return None
        
        if strategy == "random":
            import random
            return random.choice(instances)
        else:
            return instances[0]
    
    def _ensure_path(self, path: str):
        """确保路径存在"""
        if not self.zk.exists(path):
            self.zk.create(path, makepath=True)
    
    def close(self):
        """关闭连接"""
        if self.zk and self.zk.connected:
            self.zk.stop()
            self.zk.close()
            logger.info("👋 Zookeeper连接已关闭")


class ZKServiceDiscovery:
    """Zookeeper服务发现（轻量级客户端，只读）"""
    
    def __init__(self, zk_hosts: str = None, namespace: str = "dfecrab"):
        from src.config.config_loader import config as _cfg
        if zk_hosts is None:
            zk_hosts = _cfg.zk_hosts
        self.zk_hosts = zk_hosts
        self.namespace = namespace
        self.base_path = f"/{namespace}/services"
        self.zk: Optional[KazooClient] = None
        self._watchers: Dict[str, ChildrenWatch] = {}
    
    def connect(self) -> bool:
        """连接到Zookeeper"""
        try:
            self.zk = KazooClient(hosts=self.zk_hosts, timeout=10.0)
            self.zk.start()
            logger.info(f"✅ 服务发现客户端已连接到 Zookeeper: {self.zk_hosts}")
            return True
        except Exception as e:
            logger.error(f"❌ Zookeeper连接失败: {e}")
            return False
    
    def discover_service(self, service_name: str) -> List[Dict]:
        """发现服务实例"""
        if not self.zk or not self.zk.connected:
            return []
        
        try:
            service_path = f"{self.base_path}/{service_name}"
            if not self.zk.exists(service_path):
                return []
            
            children = self.zk.get_children(service_path)
            instances = []
            
            for child in children:
                instance_path = f"{service_path}/{child}"
                data, _ = self.zk.get(instance_path)
                if data:
                    instances.append(json.loads(data.decode()))
            
            return instances
        except Exception as e:
            logger.error(f"❌ 服务发现失败: {e}")
            return []
    
    def watch_service(self, service_name: str, callback):
        """
        监听服务变化（当服务上线/下线时自动通知）
        
        Args:
            service_name: 服务名称
            callback: 回调函数，接收服务列表参数
        """
        if not self.zk or not self.zk.connected:
            return
        
        service_path = f"{self.base_path}/{service_name}"
        
        def watcher(children):
            instances = []
            for child in children:
                instance_path = f"{service_path}/{child}"
                try:
                    data, _ = self.zk.get(instance_path)
                    if data:
                        instances.append(json.loads(data.decode()))
                except:
                    pass
            callback(instances)
        
        try:
            self._watchers[service_name] = ChildrenWatch(self.zk, service_path, watcher)
            logger.info(f"👀 已开始监听服务: {service_name}")
        except Exception as e:
            logger.error(f"❌ 设置监听失败: {e}")
    
    def close(self):
        """关闭连接"""
        if self.zk and self.zk.connected:
            self.zk.stop()
            self.zk.close()
