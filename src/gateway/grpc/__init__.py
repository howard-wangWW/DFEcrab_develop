"""
gRPC服务模块

包含：
- Zookeeper服务注册与发现
- gRPC服务定义（自动生成的代码）
- Worker Agent和Manager Agent的gRPC实现
"""
# 延迟导入 zk_registry，避免 kazoo 依赖缺失影响其他模块
# from .zk_registry import ZKServiceRegistry, ZKServiceDiscovery

__all__ = []  # 具体模块请按需 from src.gateway.grpc.xxx import
