"""
配置文件 - 集中管理所有 API 配置和系统参数
所有敏感信息请通过环境变量设置
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


LOG_DIR = "/agent_logs"

class Config:
    """配置类 - 统一管理所有配置项"""

    # ============== Agent API 配置 ==============
    # Agent API 密钥 - 从环境变量获取
    # 获取地址: https://platform.deepseek.com/api_keys
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

    # Agent API 基础 URL
    DEEPSEEK_BASE_URL = "http://10.176.174.28:8080/apis/ais-v2"

    # Agent 模型名称
    # 推荐使用 deepseek-chat，支持 function calling
    DEEPSEEK_MODEL = "qwen3-14b-dfdz-test"
    DEEPSEEK_MODEL2 = "qwen3-14b-dfdz-56"
    # 温度参数 - 控制输出随机性 (0.0-2.0)
    # 较低的值使输出更确定，较高的值使输出更随机
    TEMPERATURE = 0.0  # 微调模型通常建议较低温度以保证格式稳定

    # 最大 token 数 - 控制单次响应的最大长度（与微调时的 max_length 匹配）
    MAX_TOKENS = 8192


    # ============== Tavily API 配置 ==============
    # Tavily API 密钥 - 用于网络搜索
    # 获取地址: https://tavily.com/
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

    # ============== Dify API 配置 ==============
    # Dify 工作流 API 配置（保留以备后用）
    TAIZHANG_API_KEY = "app-QuvM7MPQWopzRRAvzAxtwW5x"
    DIAODULOG_API_KEY = "app-zN99rBkuT8NeI00weQwpUULy"
    CAOZUO_TICKETS_API_KEY = "app-cxPBtXUz0llwhcGqfkyxBZUw"
    DIFY_WORKFLOW_URL = "http://172.20.42.72/v1/workflows/run"
    
    # ============== 新服务 API 配置 ==============
    # 台账服务 API
    TAIZHANG_SERVICE_URL = "http://localhost:5000/query_line"
    # 日志服务 API
    DIAODULOG_SERVICE_URL = "http://localhost:5005/query_log"
    # 操作票服务 API
    CAOZUO_TICKETS_SERVICE_URL = "http://localhost:5006/query_ticket"
    # 带电作业工单服务 API
    LIVEWORK_TICKETS_SERVICE_URL = "http://localhost:5007/query_livework"
    #带电作业工单
    # SEARCH_LIVEWORK_TICKET_SERVICE_URL = "http://localhost:5010/query_ddgzp"


    # ============== 日志配置 ==============
    # 调用记录/会话 JSON 日志输出目录
    LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

    # 任务处理日志（agent-task.log）输出目录
    # 约定：与项目根目录或 config.py 同级的 agent_logs 目录
    TASK_LOG_DIR = os.path.join(os.path.dirname(__file__), "agent_logs")

    # 是否在控制台打印详细日志
    VERBOSE = True

    # 是否保存每次调用的完整记录（用于微调数据收集）
    SAVE_CALL_LOGS = True

    # 日志文件格式 - 使用时间戳命名
    LOG_FILE_FORMAT = "agent_call_{timestamp}.json"

    # 任务处理日志文件名（相对于 TASK_LOG_DIR）
    TASK_LOG_FILE = "agent-task.log"

    # 任务日志内容预览长度，避免超长日志影响排查效率
    TASK_LOG_PREVIEW_CHARS = 800


    # ============== Agent 配置 ==============
    # Agent 系统提示词 - 定义 Agent 的行为和角色
#     SYSTEM_PROMPT = """
# 可用工具
# 你拥有以下工具，请根据需要调用对应的工具：
# 1. search_taizhang: 查询站点台账信息。参数定义: {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}, "bus_name": {"type": "string", "description": "母线名称"}}, "required": ["station", "line_name", "bus_name"]}
# 2. search_diaodulog: 根据信号日期、站点名称，搜索调度日志。参数定义: {"type": "object", "properties": {"date": {"type": "string", "description": "信号日期"}, "station": {"type": "string", "description": "站点名称"}}, "required": ["date", "station"]}
# 3. search_caozuotickets: 查询操作票信息。参数定义: {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}}, "required": ["station", "line_name"]}
# 4. search_livework_tickets: 查询带电作业工单信息。参数定义: {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}}, "required": ["station", "line_name"]}

# ## 判断逻辑
# 1. 分析告警内容，从alert_content字段中提取对应的厂站名称、日期、母线名称、馈线名称。
# 2. 如果需要调用台账，则调用 search_taizhang 工具查询该站点的台账信息。
# 3. 如果需要调用日志，则调用 search_diaodulog 工具查询站点的调度日志。
# 4. 如果需要调用操作票，则调用 search_caozuotickets 工具查询站点的操作票。
# 5. 如果需要调用带电作业工单，则调用 search_livework_tickets 工具查询站点的带电作业工单。
# 6. 最后综合判断告警是正常信号、异常信号还是需人工审核的信号，给出最终结论。
# 7. 最终结论必须以 "Final Answer:" 开头。"""

    # SYSTEM_PROMPT = """可用工具\n你拥有以下工具，请根据需要调用对应的工具：\n1. search_taizhang: 查询站点台账信息。参数定义: {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}, \"bus_name\": {\"type\": \"string\", \"description\": \"母线名称\"}}, \"required\": [\"station\", \"line_name\", \"bus_name\"]}\n2. search_diaodulog: 根据信号日期、站点名称，搜索调度日志。参数定义: {\"type\": \"object\", \"properties\": {\"date\": {\"type\": \"string\", \"description\": \"信号日期\"}, \"station\": {\"type\": \"string\", \"description\": \"站点名称\"}}, \"required\": [\"date\", \"station\"]}\n3. search_caozuotickets: 查询操作票信息。参数定义: {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}}, \"required\": [\"station\", \"line_name\"]}\n4. search_livework_ticket: 查询带电作业工单信息。参数定义: {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}}, \"required\": [\"station\", \"line_name\"]}\n## 判断逻辑\n1. 分析告警内容，从alert_content字段中提取对应的厂站名称、日期、母线名称、馈线名称。\n2. 如果需要调用台账，则调用 search_taizhang 工具查询该站点的台账信息。\n3. 如果需要调用日志，则调用 search_diaodulog 工具查询站点的调度日志。\n4. 如果需要调用操作票，则调用 search_caozuotickets 工具查询站点的操作票。\n5. 如果需要调用带电作业工单，则调用 search_livework_ticket 工具查询站点的带电作业工单。\n6. 最后综合判断告警是正常信号、异常信号还是需人工审核的信号，给出最终结论。\n7. 最终结论必须以 \"Final Answer:\" 开头。"""
#     SYSTEM_PROMPT = """可用工具
# 你拥有以下工具，请根据需要调用对应的工具：
# 1. search_taizhang: 查询站点台账信息。参数定义: {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}, "bus_name": {"type": "string", "description": "母线名称"}}, "required": ["station", "line_name", "bus_name"]}
# 2. search_diaodulog: 根据信号日期、站点名称，搜索调度日志。参数定义: {"type": "object", "properties": {"date": {"type": "string", "description": "信号日期"}, "station": {"type": "string", "description": "站点名称"}}, "required": ["date", "station"]}
# 3. search_caozuotickets: 查询操作票信息，支持批量查询多条馈线。参数定义: {"type": "object", "properties": {"queries": {"type": "array", "description": "查询条件列表，可包含多条馈线", "items": {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}}, "required": ["station", "line_name"]}}}, "required": ["queries"]}
# 4. search_livework_ticket: 查询带电作业工单信息。参数定义: {"type": "object", "properties": {"station": {"type": "string", "description": "站点名称，例如：光明站"}, "line_name": {"type": "string", "description": "馈线名称"}}, "required": ["station", "line_name"]}
# ## 判断逻辑
# 1. 分析告警内容，综合判断告警是正常信号、异常信号还是需人工审核的信号，给出最终结论。
# 2. 电压越限标准值为8.00。
# 3. 最终结论必须以 "Final Answer:" 开头。"""

    SYSTEM_PROMPT = """可用工具\n你拥有以下工具，请根据需要调用对应的工具：\n1. search_taizhang: 查询站点台账信息。参数定义: {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}, \"bus_name\": {\"type\": \"string\", \"description\": \"母线名称\"}}, \"required\": [\"station\", \"line_name\", \"bus_name\"]}\n2. search_diaodulog: 根据信号日期、站点名称，搜索调度日志。参数定义: {\"type\": \"object\", \"properties\": {\"date\": {\"type\": \"string\", \"description\": \"信号日期\"}, \"station\": {\"type\": \"string\", \"description\": \"站点名称\"}}, \"required\": [\"date\", \"station\"]}\n3. search_caozuotickets: 查询操作票信息，支持批量查询多条馈线。参数定义: {\"type\": \"object\", \"properties\": {\"queries\": {\"type\": \"array\", \"description\": \"查询条件列表，可包含多条馈线\", \"items\": {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}}, \"required\": [\"station\", \"line_name\"]}}}, \"required\": [\"queries\"]}\n4. search_livework_ticket: 查询带电作业工单信息。参数定义: {\"type\": \"object\", \"properties\": {\"station\": {\"type\": \"string\", \"description\": \"站点名称，例如：光明站\"}, \"line_name\": {\"type\": \"string\", \"description\": \"馈线名称\"}}, \"required\": [\"station\", \"line_name\"]}\n## 判断逻辑\n1. 分析告警内容，综合判断告警是正常信号、异常信号还是需人工审核的信号，给出最终结论。\n2. 电压越限标准值为8.00。\n3. 最终结论必须以 \"Final Answer:\" 开头。"""
    # 最大对话轮数 - 防止无限循环
    MAX_CONVERSATION_ROUNDS = 10

    # 是否在每次工具调用后打印详细信息
    PRINT_TOOL_CALLS = True


    # ============== 验证配置 ==============
    @classmethod
    def validate(cls):
        """验证必要的配置是否已设置"""
        errors = []

        # 如果使用自定义 API 地址（自己部署的微调模型），则不强制要求 API Key
        if "api.deepseek.com" in cls.DEEPSEEK_BASE_URL:
            if not cls.DEEPSEEK_API_KEY:
                errors.append("DEEPSEEK_API_KEY 未设置，请在 .env 文件中配置")
        else:
            # 使用自定义 API 或本地部署时，可以不设置 API Key
            if not cls.DEEPSEEK_API_KEY:
                print("使用自定义 API 地址，API Key 为空（如果是本地部署可忽略此警告）")

        if errors:
            print("\n配置检查结果:")
            for error in errors:
                print(error)
            print("\n请参考 .env.example 文件创建 .env 并填入正确的 API 密钥\n")

            if "dify.ai" in cls.DIFY_WORKFLOW_URL:
                raise ValueError("Agent API Key 是必需的")

        # 确保日志目录存在
        os.makedirs(cls.LOG_DIR, exist_ok=True)

        print("配置验证通过")
        return True


# 导出配置实例
config = Config()
