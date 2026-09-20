"""
api_base 规范化工具

背景：现场配置时容易把网关文档里的"完整接口地址"直接粘进 api_base
（如 http://ip:8080/apis/ais-v2/chat/completions），而代码统一在
api_base 后拼接 /chat/completions、/models，导致路径重复 → 404 → 模型误判不可达。

约定：全项目 api_base 恒为"根地址"（到 /v1 或网关根路径为止），
本函数是唯一清洗入口，加载 / 写入配置时统一调用。
"""

import logging
import re

logger = logging.getLogger(__name__)

# 已知的 OpenAI 兼容端点后缀（误填完整地址时剥掉；长后缀优先，避免剥错位）
_KNOWN_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/chat/completion",
    "/responses",
    "/completions",
    "/embeddings",
    "/models",
    "/rerank",
)

# 重复版本段（如 http://host/v1/v1 → http://host/v1；vLLM/网关常见误填）
_RE_DUP_VERSION_SEG = re.compile(r"/(v\d+)/\1$", re.IGNORECASE)


def normalize_api_base(api_base: str) -> str:
    """规范化 api_base：去空白、去尾斜杠、剥误填的端点后缀与重复版本段。

    幂等：对已经是根地址的输入返回原值（如 http://host:port/v1、http://host:port/apis/ais-v2）。

    Examples:
        >>> normalize_api_base("http://10.176.174.28:8080/apis/ais-v2/chat/completions")
        'http://10.176.174.28:8080/apis/ais-v2'
        >>> normalize_api_base("http://172.20.41.86:8089/v1/")
        'http://172.20.41.86:8089/v1'
        >>> normalize_api_base("http://172.20.41.86:8089/v1/v1")
        'http://172.20.41.86:8089/v1'
        >>> normalize_api_base("http://host:8080/apis/ais-v2/models")
        'http://host:8080/apis/ais-v2'
    """
    if not api_base:
        return ""
    base = (api_base or "").strip().rstrip("/")

    # 1) 循环剥端点后缀（while 处理双重后缀，如 .../chat/completions/chat/completions）
    changed = True
    while changed:
        changed = False
        for suffix in sorted(_KNOWN_ENDPOINT_SUFFIXES, key=len, reverse=True):
            if base.lower().endswith(suffix.lower()):
                base = base[: -len(suffix)].rstrip("/")
                logger.warning(f"⚠️ api_base 含完整端点后缀，已自动剥离 → {base}")
                changed = True
                break  # 一轮只剥一个最长的，避免误剥嵌套路径

    # 2) 剥重复版本段（/v1/v1 → /v1；/v2/v2 → /v2）
    while True:
        m = _RE_DUP_VERSION_SEG.search(base)
        if not m:
            break
        base = base[: m.start()] + "/" + m.group(1)
        logger.warning(f"⚠️ api_base 含重复版本段，已自动合并 → {base}")

    return base
