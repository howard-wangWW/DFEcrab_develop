import os
from dotenv import load_dotenv

load_dotenv()

class DMConfig:
    HOST = os.getenv("DM_HOST", "172.20.42.247")
    PORT = int(os.getenv("DM_PORT", 5236))
    USER = os.getenv("DM_USER", "XOPENS")
    PASSWORD = os.getenv("DM_PASSWORD", "ytdf000000")   # 从环境变量读取
    SCHEMA = os.getenv("DM_SCHEMA", "XOPENS")
    
    @property
    def conn_str(self):
        # 仅用于日志，不要打印密码
        return f"dm://{self.USER}:****@{self.HOST}:{self.PORT}"