"""
DFEcrab Gateway 启动脚本 - gRPC版本

启动Gateway，对外提供HTTP服务，内部通过gRPC + Zookeeper调用Manager和Workers
"""

import sys
import asyncio
import logging
import signal
from pathlib import Path

# 设置路径 - 确保项目根目录在sys.path中（必须在所有项目导入之前）
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 统一日志模块（在路径设置后导入）
from src.utils.logging_setup import setup_root_logging, setup_service_logging

# 确保日志目录存在
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 配置日志（root → gateway_grpc.log；dfecrab.manager → manager_agent.log；dfecrab.react → worker_agents.log）
# 统一封装了：启动 Banner、单文件滚动、第三方库降级。
setup_root_logging(LOG_DIR / "gateway_grpc.log", service_name="gateway")
setup_service_logging("dfecrab.manager", LOG_DIR / "manager_agent.log")
setup_service_logging("dfecrab.react", LOG_DIR / "worker_agents.log")

logger = logging.getLogger(__name__)

# 全局变量
gw = None
running = False


async def shutdown():
    """优雅关闭"""
    global running, gw

    logger.info("[BYE] 正在关闭 DFEcrab V2 Gateway (gRPC)...")
    running = False

    if gw:
        await gw.stop()

    logger.info("[OK] Gateway 已关闭")


def signal_handler(sig, frame):
    """信号处理"""
    logger.info(f"收到信号 {sig}，准备关闭...")
    global running
    running = False


async def main():
    global gw, running

    print("=" * 60)
    print("[START] 正在启动 DFEcrab V2 Gateway (gRPC)...")
    print("=" * 60)

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 从统一配置读取
        from config.config_loader import config
        
        # 实例化 V2 Gateway (gRPC版本)
        from src.gateway.grpc_server import GatewayV2GRPC
        
        gw = GatewayV2GRPC(
            host=config.gateway_host,
            port=config.gateway_port,
            ws_port=config.websocket_port,
            zk_hosts=config.zk_hosts
        )

        # 初始化
        if not await gw.initialize():
            print("[FAIL] V2 Gateway (gRPC) 初始化失败")
            return

        print("[OK] V2 Gateway (gRPC) 初始化成功")

        # 启动 Gateway
        if not await gw.start():
            print("[FAIL] V2 Gateway (gRPC) 启动失败")
            return

        running = True
        print("[OK] V2 Gateway (gRPC) 启动成功!")
        print(f"[HTTP] 对外HTTP: http://{config.gateway_host}:{config.gateway_port}")
        print(f"[gRPC] 内部gRPC: via Zookeeper({config.zk_hosts})")
        print(f"\n按 Ctrl+C 停止")

        # 保持运行
        try:
            while running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到 KeyboardInterrupt")
        except asyncio.CancelledError:
            logger.info("主循环被取消")
        except Exception as e:
            logger.error(f"主循环异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await shutdown()

    except Exception as e:
        logger.error(f"启动失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[BYE] 再见！")
    except Exception as e:
        print(f"[FAIL] 未捕获的异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
