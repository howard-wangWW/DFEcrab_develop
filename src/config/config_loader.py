"""
统一配置加载器

所有组件从此处读取配置，避免各启动脚本和组件中散落硬编码值。
只需修改 config/gateway.yaml 即可全局生效。

用法:
    from src.config.config_loader import config
    
    zk_hosts = config.zk_hosts          # Zookeeper 地址
    gateway_port = config.gateway_port   # Gateway HTTP 端口
"""

import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """自动定位项目根目录（包含 config/gateway.yaml 的目录）"""
    current = Path(__file__).resolve().parent.parent.parent  # src/config -> src -> root
    for parent in [current] + list(current.parents):
        if (parent / "config" / "gateway.yaml").exists():
            return parent
    logger.warning("⚠️ 未找到项目根目录(config/gateway.yaml)，使用当前工作目录")
    return Path.cwd()


class Config:
    """全局配置单例"""
    _instance = None
    _config: Optional[dict] = None
    _project_root: Optional[Path] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def project_root(self) -> Path:
        if self._project_root is None:
            self._project_root = _find_project_root()
            logger.info(f"📁 项目根目录: {self._project_root}")
        return self._project_root

    @property
    def raw_config(self) -> dict:
        """原始 YAML 配置"""
        if self._config is None:
            config_path = self.project_root / "config" / "gateway.yaml"
            if not config_path.exists():
                logger.warning(f"⚠️ 配置文件不存在: {config_path}，使用空配置")
                self._config = {}
            else:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info(f"✅ 已加载配置: {config_path}")
        return self._config

    # ---- 便捷属性 ----

    @property
    def zk_hosts(self) -> str:
        """ZooKeeper 地址，如 'localhost:2181'"""
        return self.raw_config.get("zookeeper", {}).get("hosts", "localhost:2181")

    @property
    def zk_namespace(self) -> str:
        """ZooKeeper 命名空间"""
        return self.raw_config.get("zookeeper", {}).get("namespace", "dfecrab")

    @property
    def gateway_host(self) -> str:
        """Gateway 监听地址"""
        return self.raw_config.get("gateway", {}).get("host", "0.0.0.0")

    @property
    def gateway_port(self) -> int:
        """Gateway HTTP 端口"""
        return self.raw_config.get("gateway", {}).get("port", 6789)

    @property
    def websocket_port(self) -> int:
        """Gateway WebSocket 端口"""
        return self.raw_config.get("gateway", {}).get("ws_port", 6790)

    def reload(self):
        """重新加载配置（修改 gateway.yaml 后调用）"""
        self._config = None
        logger.info("🔄 配置已重新加载")


# 全局单例
config = Config()
