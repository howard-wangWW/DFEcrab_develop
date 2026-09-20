"""
DFEcrab Config Module - 配置模块

统一配置入口见 src.config.config_loader（读取 config/gateway.yaml）：
    from src.config.config_loader import config
    config.gateway_port / config.zk_hosts / ...

旧版 src/config/config.py（dataclass + 硬编码模型/密钥）已移除，
请勿再从本包直接 import 旧 config / ModelConfig 等。
"""
